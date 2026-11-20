import { useCallback, useEffect, useRef, useState } from "react";
import { createChat, followJob, getChat, sendDecision, sendMessage } from "../api";
import type { ChatMessage, ChatView, JobEvent, Pack, Strategy } from "../types";
import { PackView } from "./PackView";
import { PMView } from "./PMView";
import { StrategyView } from "./StrategyView";
import { SourcesProvider } from "./ui";

type Phase = "research" | "gtm" | "pm";
type Progress = {
  title: string;
  doneTitle: string;
  lines: string[];
  status: "running" | "done" | "failed";
  started: number;
  ended?: number;
};
type Live = { phase: Phase | null; lines: string[]; started: number };

const SUGGESTIONS = [
  { name: "Vercel", site: "vercel.com", hint: "Frontend cloud" },
  { name: "Linear", site: "linear.app", hint: "Issue tracking" },
  { name: "Supabase", site: "supabase.com", hint: "Postgres platform" },
  { name: "Notion", site: "notion.so", hint: "Connected workspace" },
];
const PHASE_TITLES: Record<Phase, string> = {
  research: "Researching the web",
  gtm: "Building the GTM strategy: 3 specialists, merge, snapshot",
  pm: "PM: checking the baseline and establishing the use case",
};
const STEP_LABELS: Record<string, string> = {
  understand: "Understanding the request",
  plan: "Planning the next search",
  collect: "Collecting pages",
  coverage: "Checking coverage",
  baseline: "Checking the baseline",
  hitl: "Human check",
  done: "Done",
  failed: "Failed",
};

function eventLine(event: JobEvent): string {
  const data = event.data ?? {};
  if (event.step === "plan" && data.round !== undefined) return `Round ${data.round}: searching for ${data.gap}`;
  if (event.step === "plan" && data.tool) return `Planner: ${data.tool}`;
  if (event.step === "collect") return `Round ${data.round}: kept ${data.kept} pages, skipped ${data.skipped}`;
  if (event.step === "coverage") return `Round ${data.round}: ${data.items} new evidence items`;
  return `${STEP_LABELS[event.step] ?? event.step}: ${event.status}`;
}

function Elapsed({ started, ended }: { started: number; ended?: number }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (ended !== undefined) return;
    const timer = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(timer);
  }, [ended]);
  return <>{Math.max(0, Math.round(((ended ?? now) - started) / 1000))}s</>;
}

function ProgressCard({ item }: { item: Progress }) {
  const [open, setOpen] = useState(false);
  const running = item.status === "running";
  const lines = item.lines;
  return (
    <div className={`progress ${item.status}`}>
      <button className="progress-head" onClick={() => setOpen(!open)} disabled={running || !lines.length}>
        {running ? <span className="spinner" /> : <span className={`progress-icon ${item.status}`}>{item.status === "done" ? "✓" : "!"}</span>}
        <span className={running ? "shimmer" : ""}>{running ? item.title : item.doneTitle}</span>
        <span className="muted small">
          <Elapsed started={item.started} ended={item.ended} />
        </span>
        {!running && lines.length > 0 && <span className="chev">{open ? "▾" : "▸"}</span>}
      </button>
      {(running || open) && lines.length > 0 && (
        <ul className="progress-lines">
          {(running ? lines.slice(-6) : lines).map((line, index) => (
            <li key={index}>{line}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** A finished step from the transcript, shown like the live progress card it was. */
function stepProgress(message: ChatMessage): Progress {
  const seconds = message.payload.duration_s ?? 0;
  return {
    title: message.text,
    doneTitle: message.text,
    lines: (message.payload.events ?? []).map(eventLine),
    status: message.payload.status === "failed" ? "failed" : "done",
    started: 0,
    ended: seconds * 1000,
  };
}

export function Chat({
  chatId,
  instructions,
  setInstructions,
  onChatCreated,
  onChanged,
}: {
  chatId: string | null;
  instructions: string;
  setInstructions: (value: string) => void;
  onChatCreated: (chatId: string) => void;
  onChanged: () => void;
}) {
  const [view, setView] = useState<ChatView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState<Live | null>(null);
  const [sending, setSending] = useState(false);
  const [draft, setDraft] = useState("");
  const [showInstructions, setShowInstructions] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  const current = useRef<string | null>(chatId); // the chat on screen; older followers stop
  const following = useRef<string | null>(null);

  const refresh = useCallback(async (id: string) => {
    const next = await getChat(id);
    if (current.current === id) setView(next);
    return next;
  }, []);

  const follow = useCallback(
    async (id: string, jobId: string) => {
      if (following.current === jobId) return;
      following.current = jobId;
      setLive({ phase: null, lines: [], started: Date.now() });
      const stopped = () => current.current !== id || following.current !== jobId;
      try {
        await followJob(
          jobId,
          (event) => {
            if (stopped()) return;
            if (event.step === "phase") {
              const phase = event.data.phase as Phase;
              // Time the step from the server's clock, so a reopened chat shows the real elapsed time.
              const started = typeof event.at === "number" ? event.at * 1000 : Date.now();
              if (event.status === "running") setLive({ phase, lines: [], started });
              else void refresh(id); // the finished step and its result card are in the transcript now
              return;
            }
            setLive((value) => (value ? { ...value, lines: [...value.lines, eventLine(event)] } : value));
          },
          stopped,
        );
      } catch (err) {
        if (!stopped()) setError((err as Error).message);
      } finally {
        if (following.current === jobId) {
          following.current = null;
          if (current.current === id) {
            setLive(null);
            await refresh(id).catch(() => undefined);
            onChanged();
          }
        }
      }
    },
    [refresh, onChanged],
  );

  // Open the chosen chat, and keep following a turn that is still running.
  useEffect(() => {
    current.current = chatId;
    setError(null);
    setLive(null);
    if (!chatId) {
      setView(null);
      following.current = null;
      return;
    }
    if (view?.chat.id === chatId) return; // just created here: already on screen
    setView(null);
    refresh(chatId)
      .then((next) => {
        if (next.chat.active_job_id) void follow(chatId, next.chat.active_job_id);
      })
      .catch((err) => setError((err as Error).message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatId]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [view?.messages.length, live?.phase]);

  const busy = sending || live !== null || Boolean(view?.chat.active_job_id);

  async function run(start: (id: string) => Promise<string>, optimistic: string) {
    if (busy) return;
    setSending(true);
    setError(null);
    try {
      let id = chatId;
      if (!id) {
        id = await createChat();
        current.current = id;
        setView({ chat: { id, title: "", pending: null, active_job_id: null }, messages: [] });
        onChatCreated(id);
      }
      const chat = id;
      setView((value) =>
        value && value.chat.id === chat
          ? {
              ...value,
              messages: [
                ...value.messages,
                { id: `local-${Date.now()}`, seq: 0, role: "user", kind: "text", text: optimistic, run_id: null, payload: {}, created_at: "" },
              ],
            }
          : value,
      );
      const jobId = await start(chat);
      onChanged();
      void follow(chat, jobId);
    } catch (err) {
      setError((err as Error).message);
      if (chatId) void refresh(chatId).catch(() => undefined);
    } finally {
      setSending(false);
    }
  }

  const send = (text: string) => {
    const message = text.trim();
    if (!message) return;
    setDraft("");
    void run((id) => sendMessage(id, message, instructions), message);
  };
  const decide = (runId: string, decision: "proceed" | "research") =>
    void run((id) => sendDecision(id, runId, decision, instructions), decision === "proceed" ? "Proceed with gaps" : "Research more");

  const messages = view?.messages ?? [];
  const packs: Record<string, Pack> = {};
  const strategies: Record<string, Strategy> = {};
  messages.forEach((m) => {
    if (m.run_id && m.payload.pack) packs[m.run_id] = m.payload.pack;
    if (m.run_id && m.payload.strategy) strategies[m.run_id] = m.payload.strategy;
  });
  const last = messages[messages.length - 1];
  const lastPmSeq = Math.max(0, ...messages.filter((m) => m.kind === "pm").map((m) => m.seq));
  const empty = messages.length === 0 && !live;

  const composer = (
    <div className="composer-wrap">
      <form
        className="composer"
        onSubmit={(event) => {
          event.preventDefault();
          send(draft);
        }}
      >
        <textarea
          rows={1}
          value={draft}
          placeholder={busy ? "Working on it…" : "Company name or website"}
          maxLength={300}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              send(draft);
            }
          }}
          aria-label="Company name or website"
        />
        <div className="composer-row">
          <button
            type="button"
            className={`chip-btn ${instructions ? "on" : ""}`}
            onClick={() => setShowInstructions(!showInstructions)}
          >
            ＋ Instructions{instructions ? `: ${instructions.slice(0, 24)}` : ""}
          </button>
          <button type="submit" className="send" disabled={busy || !draft.trim()} aria-label="Send">
            {busy ? <span className="spinner small" /> : "↑"}
          </button>
        </div>
        {showInstructions && (
          <input
            className="instructions"
            value={instructions}
            maxLength={300}
            placeholder="Optional, for example: EU only"
            onChange={(event) => setInstructions(event.target.value)}
          />
        )}
      </form>
      <p className="fineprint">VentureOS proposes; a person decides. Every claim cites its source. Your chats are saved.</p>
    </div>
  );

  function quickReplies(message: ChatMessage) {
    if (message !== last || busy) return null;
    const pending = view?.chat.pending;
    const candidates = message.kind === "clarify" && pending === "clarify" ? message.payload.candidates ?? [] : [];
    const quick = message.kind === "pack" && pending === "rerun" ? message.payload.quick ?? [] : [];
    if (!candidates.length && !quick.length) return null;
    return (
      <div className="quick">
        {candidates.map((candidate, index) => (
          <button key={candidate.website} className="chip-btn" onClick={() => send(String(index + 1))}>
            {candidate.name} · {candidate.website}
          </button>
        ))}
        {quick.map((text) => (
          <button key={text} className="chip-btn" onClick={() => send(text)}>
            {text === "yes" ? "Research the missing items" : text}
          </button>
        ))}
      </div>
    );
  }

  return (
    <div className={`chat ${empty ? "is-empty" : ""}`}>
      {error && (
        <div className="banner">
          {error}{" "}
          {chatId && (
            <button className="btn small" onClick={() => void refresh(chatId).then(() => setError(null)).catch((err) => setError((err as Error).message))}>
              Retry
            </button>
          )}
        </div>
      )}
      {empty ? (
        <div className="hero">
          <h1>
            What company should we <span className="gradient-text">research</span>?
          </h1>
          <p className="muted">
            Research collects quoted evidence, 3 specialists build the go-to-market strategy, and the PM agent proposes a
            use case, an action plan, a 1-pager, and an MVP idea. About 3 minutes.
          </p>
          {composer}
          <div className="suggestions">
            {SUGGESTIONS.map((item) => (
              <button key={item.site} className="suggestion" disabled={busy} onClick={() => send(item.site)}>
                <strong>{item.name}</strong>
                <span>{item.hint}</span>
              </button>
            ))}
          </div>
        </div>
      ) : (
        <>
          <div className="thread">
            {messages.map((message) => {
              if (message.role === "user")
                return (
                  <div key={message.id} className="msg user">
                    <div className="bubble">{message.text}</div>
                  </div>
                );
              if (message.kind === "step")
                return (
                  <div key={message.id} className="msg assistant">
                    <ProgressCard item={stepProgress(message)} />
                  </div>
                );
              const runId = message.run_id ?? "";
              return (
                <div key={message.id} className="msg assistant">
                  <div className="avatar" aria-hidden />
                  <div className="msg-body">
                    <SourcesProvider evidence={packs[runId]?.evidence} recommendations={strategies[runId]?.recommendations}>
                      {(message.kind === "text" || message.kind === "clarify" || message.kind === "error") && (
                        <p className={message.kind === "error" ? "error-text" : "pre"}>{message.text}</p>
                      )}
                      {message.kind === "pack" && message.payload.pack && (
                        <>
                          <p>{message.text}</p>
                          <PackView pack={message.payload.pack} />
                        </>
                      )}
                      {message.kind === "strategy" && message.payload.strategy && (
                        <>
                          <p>{message.text}</p>
                          <StrategyView strategy={message.payload.strategy} />
                        </>
                      )}
                      {message.kind === "pm" && message.payload.result && (
                        <>
                          <p>{message.text}</p>
                          <PMView
                            result={message.payload.result}
                            busy={busy || message.seq !== lastPmSeq}
                            onDecision={(decision) => decide(runId, decision)}
                          />
                        </>
                      )}
                      {quickReplies(message)}
                    </SourcesProvider>
                  </div>
                </div>
              );
            })}
            {live && (
              <div className="msg assistant">
                <ProgressCard
                  item={{
                    title: live.phase ? PHASE_TITLES[live.phase] : "Waiting for a worker",
                    doneTitle: "",
                    lines: live.lines,
                    status: "running",
                    started: live.started,
                  }}
                />
              </div>
            )}
            <div ref={bottom} />
          </div>
          {composer}
        </>
      )}
    </div>
  );
}
