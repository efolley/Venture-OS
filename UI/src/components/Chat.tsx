import { useCallback, useEffect, useRef, useState } from "react";
import { call, research, runGTM, runPM } from "../api";
import type { JobEvent, Pack, PMResult, Strategy } from "../types";
import { PackView } from "./PackView";
import { PMView } from "./PMView";
import { StrategyView } from "./StrategyView";
import { SourcesProvider } from "./ui";

type Progress = {
  id: number;
  role: "progress";
  title: string;
  doneTitle: string;
  lines: string[];
  status: "running" | "done" | "failed";
  started: number;
  ended?: number;
};
type Message =
  | { id: number; role: "user"; text: string }
  | { id: number; role: "assistant"; text: string; tone?: "error"; candidates?: { name: string; website: string }[]; quick?: string[] }
  | { id: number; role: "pack"; text: string; runId: string }
  | { id: number; role: "strategy"; runId: string }
  | { id: number; role: "pm"; text: string; runId: string; result: PMResult }
  | Progress;

type RunData = { pack?: Pack; strategy?: Strategy };

const SUGGESTIONS = [
  { name: "Vercel", site: "vercel.com", hint: "Frontend cloud" },
  { name: "Linear", site: "linear.app", hint: "Issue tracking" },
  { name: "Supabase", site: "supabase.com", hint: "Postgres platform" },
  { name: "Notion", site: "notion.so", hint: "Connected workspace" },
];
const STEP_LABELS: Record<string, string> = {
  understand: "Understanding the request",
  plan: "Planning the next search",
  collect: "Collecting pages",
  coverage: "Checking coverage",
  done: "Done",
  failed: "Failed",
};
const PM_MESSAGES: Record<string, string> = {
  hitl_required: "The strategy pack misses required information. Choose how to continue.",
  research_requested: "Gaps sent back to Research. Start a new research run in the chat to fill them.",
};

function eventLine(event: JobEvent): string {
  const data = event.data ?? {};
  if (event.step === "plan") return `Round ${data.round}: searching for ${data.gap}`;
  if (event.step === "collect") return `Round ${data.round}: kept ${data.kept} pages, skipped ${data.skipped}`;
  if (event.step === "coverage") return `Round ${data.round}: ${data.items} new evidence items`;
  return `${STEP_LABELS[event.step] ?? event.step}: ${event.status}`;
}

let nextId = 1;

function Elapsed({ started, ended }: { started: number; ended?: number }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (ended) return;
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

export function Chat({
  instructions,
  setInstructions,
  resetKey,
  onRunsChanged,
}: {
  instructions: string;
  setInstructions: (value: string) => void;
  resetKey: number;
  onRunsChanged: () => void;
}) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [runs, setRuns] = useState<Record<string, RunData>>({});
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState("");
  const [showInstructions, setShowInstructions] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);

  const startSession = useCallback(async () => {
    setError(null);
    setMessages([]);
    setRuns({});
    try {
      const { session_id } = await call<{ session_id: string }>("POST", "/api/sessions");
      setSessionId(session_id);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    void startSession();
  }, [startSession, resetKey]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  const add = (message: Message) => setMessages((list) => [...list, message]);
  const update = (id: number, change: Partial<Progress>) =>
    setMessages((list) => list.map((m) => (m.id === id ? ({ ...m, ...change } as Message) : m)));
  const progress = (title: string, doneTitle: string): number => {
    const id = nextId++;
    add({ id, role: "progress", title, doneTitle, lines: [], status: "running", started: Date.now() });
    return id;
  };
  const finish = (id: number, status: "done" | "failed", doneTitle?: string) =>
    update(id, { status, ended: Date.now(), ...(doneTitle ? { doneTitle } : {}) });

  async function planWithPM(runId: string, decision?: "proceed" | "research") {
    const step = progress(
      "PM: checking the baseline and establishing the use case",
      "PM plan ready",
    );
    try {
      const result = await runPM(runId, instructions, decision);
      const label = { hitl_required: "PM needs your decision", research_requested: "PM sent the gaps back to Research" }[
        result.status
      ];
      finish(step, "done", label);
      add({ id: nextId++, role: "pm", runId, result, text: PM_MESSAGES[result.status] ?? "Here is the use case and action plan." });
    } catch (err) {
      finish(step, "failed", "PM failed");
      add({ id: nextId++, role: "assistant", tone: "error", text: `PM failed: ${(err as Error).message}` });
    }
  }

  async function send(text: string) {
    const message = text.trim();
    if (!message || !sessionId || busy) return;
    setBusy(true);
    setDraft("");
    add({ id: nextId++, role: "user", text: message });
    const step = progress("Researching the web", "Research finished");
    try {
      const reply = await research(sessionId, message, instructions, (event) =>
        setMessages((list) =>
          list.map((m) => (m.id === step && m.role === "progress" ? { ...m, lines: [...m.lines, eventLine(event)] } : m)),
        ),
      );
      finish(step, reply.kind === "error" ? "failed" : "done", reply.kind === "error" ? "Research failed" : undefined);
      onRunsChanged();
      if (reply.kind === "pack" && reply.pack && reply.run_id) {
        const runId = reply.run_id;
        const pack = reply.pack;
        setRuns((all) => ({ ...all, [runId]: { pack } }));
        add({ id: nextId++, role: "pack", runId, text: reply.message });
        // Research finished with an evidence pack: hand it to GTM, then to PM.
        const gtmStep = progress("Building the GTM strategy: 3 specialists, merge, snapshot", "GTM strategy ready");
        let strategy: Strategy;
        try {
          strategy = await runGTM(runId, instructions);
        } catch (err) {
          finish(gtmStep, "failed", "GTM failed");
          add({ id: nextId++, role: "assistant", tone: "error", text: `GTM failed: ${(err as Error).message}` });
          return;
        }
        finish(gtmStep, "done");
        setRuns((all) => ({ ...all, [runId]: { ...all[runId], strategy } }));
        add({ id: nextId++, role: "strategy", runId });
        await planWithPM(runId);
      } else {
        const quick = reply.message.includes("Reply yes") ? ["yes"] : undefined;
        add({
          id: nextId++,
          role: "assistant",
          text: reply.message,
          tone: reply.kind === "error" ? "error" : undefined,
          candidates: reply.kind === "clarify" ? reply.candidates : undefined,
          quick,
        });
      }
    } catch (err) {
      finish(step, "failed", "Research failed");
      add({ id: nextId++, role: "assistant", tone: "error", text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }

  async function decide(runId: string, decision: "research" | "proceed") {
    if (busy) return;
    setBusy(true);
    add({ id: nextId++, role: "user", text: decision === "proceed" ? "Proceed with gaps" : "Research more" });
    try {
      await planWithPM(runId, decision);
    } finally {
      setBusy(false);
    }
  }

  const empty = messages.length === 0;
  const composer = (
    <div className="composer-wrap">
      <form
        className="composer"
        onSubmit={(event) => {
          event.preventDefault();
          void send(draft);
        }}
      >
        <textarea
          rows={1}
          value={draft}
          placeholder={busy ? "Working on it…" : "Company name or website"}
          disabled={!sessionId}
          maxLength={300}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void send(draft);
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
          <button type="submit" className="send" disabled={busy || !draft.trim() || !sessionId} aria-label="Send">
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
      <p className="fineprint">VentureOS proposes; a person decides. Every claim cites its source. Review before sharing.</p>
    </div>
  );

  return (
    <div className={`chat ${empty ? "is-empty" : ""}`}>
      {error && (
        <div className="banner">
          {error}{" "}
          <button className="btn small" onClick={() => void startSession()}>
            Retry
          </button>
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
              <button key={item.site} className="suggestion" disabled={!sessionId} onClick={() => void send(item.site)}>
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
              if (message.role === "progress")
                return (
                  <div key={message.id} className="msg assistant">
                    <ProgressCard item={message} />
                  </div>
                );
              const data = "runId" in message ? runs[message.runId] : undefined;
              return (
                <div key={message.id} className="msg assistant">
                  <div className="avatar" aria-hidden />
                  <div className="msg-body">
                    <SourcesProvider evidence={data?.pack?.evidence} recommendations={data?.strategy?.recommendations}>
                      {message.role === "assistant" && (
                        <>
                          <p className={message.tone === "error" ? "error-text" : "pre"}>{message.text}</p>
                          {(message.candidates?.length || message.quick) && (
                            <div className="quick">
                              {message.candidates?.map((candidate, index) => (
                                <button key={candidate.website} className="chip-btn" disabled={busy} onClick={() => void send(String(index + 1))}>
                                  {candidate.name} · {candidate.website}
                                </button>
                              ))}
                              {message.quick?.map((text) => (
                                <button key={text} className="chip-btn" disabled={busy} onClick={() => void send(text)}>
                                  {text === "yes" ? "Research the missing items" : text}
                                </button>
                              ))}
                            </div>
                          )}
                        </>
                      )}
                      {message.role === "pack" && data?.pack && (
                        <>
                          <p>{message.text}</p>
                          <PackView pack={data.pack} />
                        </>
                      )}
                      {message.role === "strategy" && data?.strategy && (
                        <>
                          <p>Here is the GTM strategy and company snapshot.</p>
                          <StrategyView strategy={data.strategy} />
                        </>
                      )}
                      {message.role === "pm" && (
                        <>
                          <p>{message.text}</p>
                          <PMView
                            result={message.result}
                            busy={busy}
                            onDecision={(decision) => void decide(message.runId, decision)}
                          />
                        </>
                      )}
                    </SourcesProvider>
                  </div>
                </div>
              );
            })}
            <div ref={bottom} />
          </div>
          {composer}
        </>
      )}
    </div>
  );
}
