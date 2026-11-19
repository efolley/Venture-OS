import { createContext, useContext, useState, type ReactNode } from "react";
import { safeUrl } from "../api";
import type { Evidence, Recommendation } from "../types";

// ----- citations ------------------------------------------------------------------------

type Sources = { evidence: Map<string, Evidence>; recommendations: Map<string, Recommendation> };
const SourcesContext = createContext<Sources>({ evidence: new Map(), recommendations: new Map() });

export function SourcesProvider({
  evidence = [],
  recommendations = [],
  children,
}: {
  evidence?: Evidence[];
  recommendations?: Recommendation[];
  children: ReactNode;
}) {
  const value = {
    evidence: new Map(evidence.map((item) => [item.id, item])),
    recommendations: new Map(recommendations.map((item) => [item.id, item])),
  };
  return <SourcesContext.Provider value={value}>{children}</SourcesContext.Provider>;
}

/** Keep the popover on screen: open it below near the top, and align it to the nearer side. */
function placePopover(event: { currentTarget: HTMLElement }) {
  const pill = event.currentTarget;
  const rect = pill.getBoundingClientRect();
  pill.dataset.below = String(rect.top < 260);
  const third = window.innerWidth / 3;
  pill.dataset.align = rect.left > 2 * third ? "right" : rect.left < third ? "left" : "center";
}

/** Cited IDs as pills. Hovering an evidence ID shows its word-for-word quote and source. */
export function Cites({ ids }: { ids?: string[] }) {
  const { evidence, recommendations } = useContext(SourcesContext);
  if (!ids?.length) return null;
  return (
    <span className="cites">
      {ids.map((id) => {
        const item = evidence.get(id);
        const rec = recommendations.get(id);
        const url = safeUrl(item?.url);
        return (
          <span
            key={id}
            className={`cite ${id.startsWith("r") ? "cite-rec" : ""}`}
            tabIndex={0}
            onMouseEnter={placePopover}
            onFocus={placePopover}
          >
            {id}
            {(item || rec) && (
              <span className="cite-pop" role="tooltip">
                {item && (
                  <>
                    <strong>{item.statement}</strong>
                    <em>“{item.excerpt}”</em>
                    {url ? (
                      <a href={url} target="_blank" rel="noreferrer noopener">
                        {new URL(url).hostname}
                      </a>
                    ) : (
                      <span className="muted">{item.url}</span>
                    )}
                  </>
                )}
                {rec && (
                  <>
                    <strong>{rec.title}</strong>
                    <span>{rec.recommendation}</span>
                    <span className="muted">
                      {AGENT_LABELS[rec.agent] ?? rec.agent} · {rec.basis.replace("_", " ")}
                    </span>
                  </>
                )}
              </span>
            )}
          </span>
        );
      })}
    </span>
  );
}

export const AGENT_LABELS: Record<string, string> = {
  market_analysis: "Market analyst",
  competitive_strategy: "Competitive strategist",
  challenger_salesman: "Challenger salesperson",
};

// ----- small pieces ---------------------------------------------------------------------

const STATUS_TONES: Record<string, string> = {
  complete: "green",
  pass: "green",
  done: "green",
  found: "green",
  partial: "amber",
  fallback: "red",
  fail: "red",
  failed: "red",
  hitl_required: "pink",
  research_requested: "violet",
  clarify: "cyan",
  running: "cyan",
};

export function Badge({ status, label }: { status: string; label?: string }) {
  return (
    <span className={`badge tone-${STATUS_TONES[status] ?? "gray"}`}>
      {label ?? status.replaceAll("_", " ")}
    </span>
  );
}

export function Hypothesis({ basis }: { basis?: string }) {
  return basis === "hypothesis" ? <span className="badge tone-amber subtle">hypothesis</span> : null;
}

export function Tabs({ tabs }: { tabs: { label: string; content: ReactNode; count?: number }[] }) {
  const [active, setActive] = useState(0);
  return (
    <div className="tabs">
      <div className="tab-list" role="tablist">
        {tabs.map((tab, index) => (
          <button
            key={tab.label}
            role="tab"
            aria-selected={index === active}
            className={index === active ? "tab active" : "tab"}
            onClick={() => setActive(index)}
          >
            {tab.label}
            {tab.count !== undefined && <span className="tab-count">{tab.count}</span>}
          </button>
        ))}
      </div>
      <div className="tab-panel" role="tabpanel">
        {tabs[active]?.content}
      </div>
    </div>
  );
}

export function Section({
  title,
  icon,
  meta,
  accent = "violet",
  children,
  actions,
}: {
  title: ReactNode;
  icon?: string;
  meta?: ReactNode;
  accent?: string;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <section className={`card accent-${accent}`}>
      <header className="card-head">
        <div className="card-title">
          {icon && <span className="card-icon">{icon}</span>}
          <h3>{title}</h3>
        </div>
        {meta && <div className="card-meta">{meta}</div>}
      </header>
      <div className="card-body">{children}</div>
      {actions && <footer className="card-foot">{actions}</footer>}
    </section>
  );
}

export function Collapsible({ title, children, open = false }: { title: ReactNode; children: ReactNode; open?: boolean }) {
  return (
    <details className="collapsible" open={open}>
      <summary>{title}</summary>
      <div className="collapsible-body">{children}</div>
    </details>
  );
}

export function ExternalLink({ url, label }: { url: string; label?: string }) {
  const safe = safeUrl(url);
  if (!safe) return <span className="muted">{label ?? url}</span>;
  return (
    <a href={safe} target="_blank" rel="noreferrer noopener">
      {label ?? new URL(safe).hostname.replace(/^www\./, "")}
    </a>
  );
}
