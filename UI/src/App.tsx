import { useCallback, useEffect, useState } from "react";
import { ApiKeyError, call, getApiKey, listChats, setApiKey } from "./api";
import { Chat } from "./components/Chat";
import { RunsView } from "./components/RunsView";
import type { ChatSummary, RunSummary } from "./types";

type View = "chat" | "runs";
type Health = { store: string; sessions?: string; short_term?: string; queue?: string };

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

/** The chat ID in the address bar (#/chat/<id>), so a reload or a shared link reopens it. */
function chatFromHash(): string | null {
  const match = /^#\/chat\/([0-9a-f-]{36})$/i.exec(window.location.hash);
  return match ? match[1] : null;
}

function when(iso: string): string {
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
  if (!Number.isFinite(seconds)) return "";
  if (seconds < 60) return "now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h`;
  return new Date(iso).toLocaleDateString();
}

function KeyPrompt({ onSaved }: { onSaved: () => void }) {
  const [value, setValue] = useState(getApiKey());
  return (
    <form
      className="banner key-prompt"
      onSubmit={(event) => {
        event.preventDefault();
        setApiKey(value.trim());
        onSaved();
      }}
    >
      This server needs an API key.
      <input
        type="password"
        value={value}
        placeholder="X-API-Key"
        autoComplete="off"
        onChange={(event) => setValue(event.target.value)}
        aria-label="API key"
      />
      <button className="btn small" type="submit">
        Save
      </button>
    </form>
  );
}

export default function App() {
  const [view, setView] = useState<View>("chat");
  const [instructions, setInstructions] = useState("");
  const [chatId, setChatId] = useState<string | null>(chatFromHash());
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [online, setOnline] = useState<boolean | null>(null);
  const [needKey, setNeedKey] = useState(false);
  const [runsError, setRunsError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const [chatList, runList, status] = await Promise.all([
        listChats(),
        call<{ runs: RunSummary[] }>("GET", "/api/runs?limit=200"),
        call<Health>("GET", "/api/health"),
      ]);
      setChats(chatList);
      setRuns(runList.runs);
      setHealth(status);
      setOnline(true);
      setNeedKey(false);
      setRunsError(null);
    } catch (err) {
      if (err instanceof ApiKeyError) setNeedKey(true);
      else setOnline(false);
      setRunsError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const onHash = () => {
      setChatId(chatFromHash());
      setView("chat");
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const openChat = (id: string | null) => {
    window.location.hash = id ? `#/chat/${id}` : "";
    setChatId(id);
    setView("chat");
    setSidebarOpen(false);
  };

  const openRun = (id: string) => {
    setSelected(id);
    setView("runs");
    setSidebarOpen(false);
  };

  // For example "Postgres · Redis · Kafka", or "Memory · InProcess" with no infrastructure.
  const backends = health
    ? [...new Set(
        [health.store, health.sessions, health.short_term, health.queue]
          .filter(Boolean)
          .map((name) => String(name).replace(/(SessionStore|Store|ShortTerm|Queue)$/, "")),
      )].join(" · ")
    : "";

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
        <button className="new-chat" onClick={() => openChat(null)}>
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
              void load();
            }}
          >
            <span>🗂</span> Stored research
          </button>
        </nav>
        <div className="recent">
          <h6>Chats</h6>
          {chats.length === 0 && <p className="muted small">No chats yet.</p>}
          {chats.slice(0, 30).map((chat) => (
            <button
              key={chat.id}
              className={`recent-item ${chat.id === chatId && view === "chat" ? "active" : ""}`}
              onClick={() => openChat(chat.id)}
              title={chat.title || "New chat"}
            >
              <span className={`dot ${chat.active_job_id ? "status-running" : ""}`} />
              <span className="recent-name">{chat.title || "New chat"}</span>
              <span className="recent-time">{when(chat.updated_at)}</span>
            </button>
          ))}
          <h6>Recent runs</h6>
          {runs.length === 0 && <p className="muted small">No runs yet.</p>}
          {runs.slice(0, 8).map((run) => (
            <button key={run.id} className={`recent-item ${run.id === selected && view === "runs" ? "active" : ""}`} onClick={() => openRun(run.id)}>
              <span className={`dot status-${run.status}`} />
              <span className="recent-name">{run.company || run.website}</span>
            </button>
          ))}
        </div>
        <div className="sidebar-foot" title={backends}>
          <span className={`dot ${online ? "status-complete" : online === false ? "status-failed" : ""}`} />
          {online ? `Backend online · ${backends}` : online === false ? "Backend offline" : "Connecting"}
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <button className="menu" aria-label="Open menu" onClick={() => setSidebarOpen(!sidebarOpen)}>
            ☰
          </button>
          <span className="topbar-title">VentureOS</span>
        </header>
        {needKey && <KeyPrompt onSaved={() => void load()} />}
        <div hidden={view !== "chat"} className="view">
          <Chat
            chatId={chatId}
            instructions={instructions}
            setInstructions={setInstructions}
            onChatCreated={(id) => {
              window.location.hash = `#/chat/${id}`;
              setChatId(id);
            }}
            onChanged={() => void load()}
          />
        </div>
        {view === "runs" && (
          <div className="view scroll">
            <RunsView
              runs={runs}
              store={health?.store ?? ""}
              error={runsError}
              selected={selected}
              onSelect={setSelected}
              onRefresh={() => void load()}
            />
          </div>
        )}
      </main>
      <div className="scrim" onClick={() => setSidebarOpen(false)} />
    </div>
  );
}
