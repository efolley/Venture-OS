// The UI only calls the pipeline API and renders what it returns. No processing here.
import type { ChatJob, ChatSummary, ChatView, JobEvent, PMResult, Strategy } from "./types";

const BASE = (import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "");
const KEY_STORAGE = "ventureos.apiKey";

/** Thrown when the gateway asks for an API key (HTTP 401). */
export class ApiKeyError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ApiKeyError";
  }
}

export function getApiKey(): string {
  try {
    return localStorage.getItem(KEY_STORAGE) ?? "";
  } catch {
    return "";
  }
}

export function setApiKey(value: string): void {
  try {
    if (value) localStorage.setItem(KEY_STORAGE, value);
    else localStorage.removeItem(KEY_STORAGE);
  } catch {
    /* private mode: the key is not kept */
  }
}

export async function call<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const key = getApiKey();
  if (key) headers["X-API-Key"] = key;
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new Error("Cannot reach the backend. Start it with: ventureos-api");
  }
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const data = await response.json();
      if (typeof data.detail === "string") detail = data.detail;
    } catch {
      /* keep the status text */
    }
    if (response.status === 401) throw new ApiKeyError(detail);
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

// ---- chats: the server runs Research, then GTM, then PM, and stores the transcript ----

export const createChat = () => call<{ chat_id: string }>("POST", "/api/chats").then((r) => r.chat_id);

export const listChats = () => call<{ chats: ChatSummary[] }>("GET", "/api/chats?limit=100").then((r) => r.chats);

export const getChat = (chatId: string) => call<ChatView>("GET", `/api/chats/${chatId}`);

export const sendMessage = (chatId: string, message: string, instructions: string) =>
  call<{ job_id: string }>("POST", `/api/chats/${chatId}/messages`, { message, instructions }).then((r) => r.job_id);

export const sendDecision = (
  chatId: string,
  runId: string,
  decision: "proceed" | "research",
  instructions: string,
) =>
  call<{ job_id: string }>("POST", `/api/chats/${chatId}/decisions`, { run_id: runId, decision, instructions }).then(
    (r) => r.job_id,
  );

/** Follow a chat turn's progress events until it finishes, or until stopped() says to quit. */
export async function followJob(
  jobId: string,
  onEvent: (event: JobEvent) => void,
  stopped: () => boolean,
): Promise<ChatJob | null> {
  let after = 0;
  while (!stopped()) {
    let job: ChatJob;
    try {
      job = await call<ChatJob>("GET", `/api/chat-jobs/${jobId}?after=${after}`);
    } catch (err) {
      if ((err as Error).message === "Unknown job.") return null; // expired: the transcript has the result
      throw err;
    }
    job.events.forEach(onEvent);
    after = job.next;
    if (job.status === "done" || job.status === "failed") return job;
    await sleep(1000);
  }
  return null;
}

// ---- stored runs: GTM and PM again on a Research run (the Stored research view) ----

/** Start GTM on a stored evidence pack and wait for the strategy pack. */
export async function runGTM(runId: string, instructions: string): Promise<Strategy> {
  const { job_id } = await call<{ job_id: string }>("POST", "/api/gtm/runs", {
    research_run_id: runId,
    instructions,
  });
  for (;;) {
    const job = await call<{ status: string; error: string; strategy: Strategy | null }>(
      "GET",
      `/api/gtm/jobs/${job_id}`,
    );
    if (job.status !== "running") {
      if (job.status !== "done" || !job.strategy) throw new Error(job.error || "GTM returned no result.");
      return job.strategy;
    }
    await sleep(2000);
  }
}

/** Run PM on the saved strategy pack, with an optional HITL 1 decision. */
export async function runPM(
  runId: string,
  instructions: string,
  decision?: "proceed" | "research",
): Promise<PMResult> {
  const { job_id } = await call<{ job_id: string }>("POST", "/api/pm/runs", {
    research_run_id: runId,
    instructions,
    ...(decision ? { decision } : {}),
  });
  for (;;) {
    const job = await call<{ status: string; error: string; result: PMResult | null }>(
      "GET",
      `/api/pm/jobs/${job_id}`,
    );
    if (job.status !== "running") {
      if (job.status !== "done" || !job.result) throw new Error(job.error || "PM returned no result.");
      return job.result;
    }
    await sleep(2000);
  }
}

export function downloadJSON(value: unknown, fileName: string): void {
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(url);
}

/** Only https links from the data become clickable. */
export function safeUrl(url: string | undefined | null): string | null {
  return url && /^https:\/\/[^\s"'<>]+$/.test(url) ? url : null;
}
