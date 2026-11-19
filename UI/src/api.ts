// The UI only calls the pipeline API and renders what it returns. No processing here.
import type { JobEvent, PMResult, Reply, Strategy } from "./types";

const BASE = (import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "");

export async function call<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
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
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** Send a chat message to Research and stream its progress events until it finishes. */
export async function research(
  sessionId: string,
  message: string,
  instructions: string,
  onEvent: (event: JobEvent) => void,
): Promise<Reply> {
  const { job_id } = await call<{ job_id: string }>("POST", `/api/sessions/${sessionId}/messages`, {
    message,
    instructions,
  });
  let after = 0;
  for (;;) {
    const job = await call<{ status: string; events: JobEvent[]; next: number; reply: Reply | null }>(
      "GET",
      `/api/jobs/${job_id}?after=${after}`,
    );
    job.events.forEach(onEvent);
    after = job.next;
    if (job.status !== "running") return job.reply ?? { kind: "error", message: "No reply." };
    await sleep(1000);
  }
}

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
