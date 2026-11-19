import { useCallback, useEffect, useState } from "react";
import { call, runGTM, runPM } from "../api";
import type { Pack, PMResult, Round, RunSummary, SourceRow, Strategy } from "../types";
import { PackView } from "./PackView";
import { PMView } from "./PMView";
import { StrategyView } from "./StrategyView";
import { Badge, Collapsible, ExternalLink, SourcesProvider, Tabs } from "./ui";

type Detail = {
  run: RunSummary & { candidates?: { name: string; website: string }[]; error?: string };
  pack: Pack | null;
};

function Working({ label }: { label: string }) {
  return (
    <div className="progress running inline">
      <div className="progress-head">
        <span className="spinner" />
        <span className="shimmer">{label}</span>
      </div>
    </div>
  );
}

function GTMSection({ runId, hasPack, onChange }: { runId: string; hasPack: boolean; onChange: (s: Strategy | null) => void }) {
  const [state, setState] = useState<{ strategy: Strategy | null; running: string | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      const result = await call<{ strategy: Strategy | null; running_job_id: string | null }>("GET", `/api/gtm/runs/${runId}`);
      setState({ strategy: result.strategy, running: result.running_job_id });
      onChange(result.strategy);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [runId, onChange]);
  useEffect(() => {
    void load();
  }, [load]);
  if (error) return <p className="error-text">{error}</p>;
  if (!state) return <Working label="Loading" />;
  if (state.running) return <p className="muted">A GTM run is in progress for this research run. Refresh in a minute.</p>;
  if (!state.strategy && !hasPack) return <p className="muted">This run has no evidence pack, so there is nothing for GTM to analyze.</p>;
  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      await runGTM(runId, "");
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      {state.strategy ? <StrategyView strategy={state.strategy} /> : <p className="muted">No GTM strategy for this run yet.</p>}
      {busy ? (
        <Working label="Building the GTM strategy: 3 specialists, merge, snapshot" />
      ) : (
        <button className="btn" onClick={() => void start()}>
          {state.strategy ? "Run GTM again" : "Run GTM strategy"}
        </button>
      )}
    </>
  );
}

function PMSection({ runId }: { runId: string }) {
  const [state, setState] = useState<{ result: PMResult | null; running: string | null; hasStrategy: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      const [pm, gtm] = await Promise.all([
        call<{ result: PMResult | null; running_job_id: string | null }>("GET", `/api/pm/runs/${runId}`),
        call<{ strategy: Strategy | null }>("GET", `/api/gtm/runs/${runId}`),
      ]);
      setState({ result: pm.result, running: pm.running_job_id, hasStrategy: Boolean(gtm.strategy) });
    } catch (err) {
      setError((err as Error).message);
    }
  }, [runId]);
  useEffect(() => {
    void load();
  }, [load]);
  const start = async (decision?: "proceed" | "research") => {
    setBusy(true);
    setError(null);
    try {
      await runPM(runId, "", decision);
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  if (!state) return error ? <p className="error-text">{error}</p> : <Working label="Loading" />;
  if (state.running) return <p className="muted">A PM run is in progress for this research run. Refresh in a minute.</p>;
  if (!state.result && !state.hasStrategy) return <p className="muted">Run GTM first; PM plans from the GTM strategy.</p>;
  return (
    <>
      {error && <p className="error-text">{error}</p>}
      {state.result ? (
        <PMView result={state.result} busy={busy} onDecision={(decision) => void start(decision)} />
      ) : (
        <p className="muted">No PM plan for this run yet.</p>
      )}
      {busy ? (
        <Working label="PM: checking the baseline and establishing the use case" />
      ) : (
        <button className="btn" onClick={() => void start()}>
          {state.result ? "Run PM again" : "Run PM"}
        </button>
      )}
    </>
  );
}

function RunDetail({ runId }: { runId: string }) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [trail, setTrail] = useState<{ rounds: Round[]; sources: SourceRow[] } | null>(null);
  const [strategy, setStrategy] = useState<Strategy | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setDetail(null);
    setTrail(null);
    setStrategy(null);
    setError(null);
    Promise.all([
      call<Detail>("GET", `/api/runs/${runId}`),
      call<{ rounds: Round[]; sources: SourceRow[] }>("GET", `/api/runs/${runId}/rounds`),
    ])
      .then(([d, t]) => {
        setDetail(d);
        setTrail(t);
      })
      .catch((err: Error) => setError(err.message));
  }, [runId]);
  if (error) return <p className="error-text">{error}</p>;
  if (!detail || !trail) return <Working label="Loading run" />;
  const { run, pack } = detail;
  return (
    <SourcesProvider evidence={pack?.evidence} recommendations={strategy?.recommendations}>
      <Tabs
        tabs={[
          {
            label: "Evidence pack",
            content: pack ? (
              <PackView pack={pack} />
            ) : (
              <div>
                <p className="muted">No pack stored. Run status: {run.status}.</p>
                {run.candidates && run.candidates.length > 0 && (
                  <ul className="facts">
                    {run.candidates.map((c) => (
                      <li key={c.website}>
                        {c.name} · <ExternalLink url={c.website} label={c.website} />
                      </li>
                    ))}
                  </ul>
                )}
                {run.error && <p className="error-text">{run.error}</p>}
              </div>
            ),
          },
          { label: "GTM strategy", content: <GTMSection runId={runId} hasPack={Boolean(pack)} onChange={setStrategy} /> },
          { label: "PM plan", content: <PMSection runId={runId} /> },
          {
            label: "Rounds",
            count: trail.rounds.length,
            content: (
              <div className="rounds">
                {trail.rounds.map((round) => (
                  <Collapsible
                    key={round.number}
                    title={round.number === 0 ? "Round 0: understand" : `Round ${round.number}: ${round.gap}`}
                  >
                    <pre className="json">
                      {JSON.stringify(
                        {
                          query: round.query,
                          site: round.site,
                          "model calls": round.model_calls,
                          error: round.error,
                          ...(round.dropped ? { "dropped or adjusted": round.dropped } : {}),
                          ...(round.coverage ? { "coverage after this round": round.coverage } : {}),
                        },
                        null,
                        2,
                      )}
                    </pre>
                  </Collapsible>
                ))}
              </div>
            ),
          },
          {
            label: "Sources",
            count: trail.sources.length,
            content: (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Kind</th>
                      <th>Round</th>
                      <th>URL</th>
                      <th>Rejected because</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trail.sources.map((source, index) => (
                      <tr key={`${source.url}-${index}`}>
                        <td className="mono">{source.id ?? ""}</td>
                        <td>{source.kind ?? ""}</td>
                        <td>{source.round}</td>
                        <td className="url">
                          <ExternalLink url={source.url} label={source.url} />
                        </td>
                        <td className="small">{source.rejection_reason ?? ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ),
          },
        ]}
      />
    </SourcesProvider>
  );
}

export function RunsView({
  runs,
  store,
  error,
  selected,
  onSelect,
  onRefresh,
}: {
  runs: RunSummary[];
  store: string;
  error: string | null;
  selected: string | null;
  onSelect: (id: string) => void;
  onRefresh: () => void;
}) {
  const statuses = [...new Set(runs.map((run) => run.status))].sort();
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const visible = runs.filter((run) => !hidden.has(run.status));
  const current = runs.find((run) => run.id === selected);
  return (
    <div className="runs">
      <header className="page-head">
        <div>
          <h1>Stored research</h1>
          <p className="muted">
            {runs.length} runs in {store || "the store"}. GTM and PM results are saved to runs/.
          </p>
        </div>
        <button className="btn" onClick={onRefresh}>
          Refresh
        </button>
      </header>
      {error && <p className="error-text">{error}</p>}
      {runs.length === 0 && !error && <div className="empty-note">No runs yet. Start one in the chat.</div>}
      {statuses.length > 0 && (
        <div className="filters">
          {statuses.map((status) => (
            <button
              key={status}
              className={`chip-btn ${hidden.has(status) ? "" : "on"}`}
              onClick={() => {
                const next = new Set(hidden);
                if (next.has(status)) next.delete(status);
                else next.add(status);
                setHidden(next);
              }}
            >
              {status}
            </button>
          ))}
        </div>
      )}
      {visible.length > 0 && (
        <div className="table-wrap">
          <table className="runs-table">
            <thead>
              <tr>
                <th>Company</th>
                <th>Website</th>
                <th>Status</th>
                <th>Rounds</th>
                <th>Sources</th>
                <th>Model calls</th>
                <th>Created</th>
                <th>Re-run of</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((run) => (
                <tr key={run.id} className={run.id === selected ? "selected" : ""} onClick={() => onSelect(run.id)}>
                  <td>
                    <strong>{run.company || "unknown"}</strong>
                  </td>
                  <td className="small">{run.website}</td>
                  <td>
                    <Badge status={run.status} />
                  </td>
                  <td>{run.usage.rounds ?? 0}</td>
                  <td>{run.usage.sources ?? 0}</td>
                  <td>{run.usage.model_calls ?? 0}</td>
                  <td className="small">{run.created_at.slice(0, 16).replace("T", " ")}</td>
                  <td className="mono small">{(run.parent_run_id ?? "").slice(0, 8)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {current && (
        <div className="run-detail">
          <h2>
            {current.company || current.website} <Badge status={current.status} />
          </h2>
          <RunDetail key={current.id} runId={current.id} />
        </div>
      )}
    </div>
  );
}
