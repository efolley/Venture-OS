import { useCallback, useEffect, useState } from "react";
import { call } from "./api";
import { Chat } from "./components/Chat";
import { RunsView } from "./components/RunsView";
import type { RunSummary } from "./types";

type View = "chat" | "runs";

function Logo() {
  return (
    <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden>
      <defs>
        <linearGradient id="logo" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#8b5cf6" />
          <stop offset=".55" stopColor="#ec4899" />
          <stop offset="1" stopColor="#f59e0b" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="url(#logo)" />
      <path d="M9 10l7 13 7-13" fill="none" stroke="white" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function App() {
  const [view, setView] = useState<View>("chat");
  const [instructions, setInstructions] = useState("");
  const [resetKey, setResetKey] = useState(0);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [store, setStore] = useState("");
  const [online, setOnline] = useState<boolean | null>(null);
  const [runsError, setRunsError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const loadRuns = useCallback(async () => {
    try {
      const [list, health] = await Promise.all([
        call<{ runs: RunSummary[] }>("GET", "/api/runs?limit=200"),
        call<{ store: string }>("GET", "/api/health"),
      ]);
      setRuns(list.runs);
      setStore(health.store);
      setOnline(true);
      setRunsError(null);
    } catch (err) {
      setOnline(false);
      setRunsError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    void loadRuns();
  }, [loadRuns]);

  const openRun = (id: string) => {
    setSelected(id);
    setView("runs");
    setSidebarOpen(false);
  };

  return (
    <div className={`app ${sidebarOpen ? "sidebar-open" : ""}`}>
      <aside className="sidebar">
        <div className="brand">
          <Logo />
          <div>
            <strong>VentureOS</strong>
            <span>Research → GTM → PM</span>
          </div>
        </div>
        <button
          className="new-chat"
          onClick={() => {
            setView("chat");
            setResetKey((key) => key + 1);
            setSidebarOpen(false);
          }}
        >
          <span>✎</span> New chat
        </button>
        <nav>
          <button className={view === "chat" ? "nav active" : "nav"} onClick={() => setView("chat")}>
            <span>💬</span> Chat
          </button>
          <button
            className={view === "runs" ? "nav active" : "nav"}
            onClick={() => {
              setView("runs");
              void loadRuns();
            }}
          >
            <span>🗂</span> Stored research
          </button>
        </nav>
        <div className="recent">
          <h6>Recent runs</h6>
          {runs.length === 0 && <p className="muted small">No runs yet.</p>}
          {runs.slice(0, 12).map((run) => (
            <button key={run.id} className={`recent-item ${run.id === selected && view === "runs" ? "active" : ""}`} onClick={() => openRun(run.id)}>
              <span className={`dot status-${run.status}`} />
              <span className="recent-name">{run.company || run.website}</span>
            </button>
          ))}
        </div>
        <div className="sidebar-foot">
          <span className={`dot ${online ? "status-complete" : online === false ? "status-failed" : ""}`} />
          {online ? `Backend online · ${store}` : online === false ? "Backend offline" : "Connecting"}
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <button className="menu" aria-label="Open menu" onClick={() => setSidebarOpen(!sidebarOpen)}>
            ☰
          </button>
          <span className="topbar-title">VentureOS</span>
        </header>
        <div hidden={view !== "chat"} className="view">
          <Chat
            instructions={instructions}
            setInstructions={setInstructions}
            resetKey={resetKey}
            onRunsChanged={() => void loadRuns()}
          />
        </div>
        {view === "runs" && (
          <div className="view scroll">
            <RunsView
              runs={runs}
              store={store}
              error={runsError}
              selected={selected}
              onSelect={setSelected}
              onRefresh={() => void loadRuns()}
            />
          </div>
        )}
      </main>
      <div className="scrim" onClick={() => setSidebarOpen(false)} />
    </div>
  );
}
