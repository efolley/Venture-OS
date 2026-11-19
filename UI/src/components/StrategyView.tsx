import { downloadJSON } from "../api";
import type { Recommendation, Strategy } from "../types";
import { AGENT_LABELS, Badge, Cites, ExternalLink, Hypothesis, Section, Tabs } from "./ui";

const SNAPSHOT_GROUPS: [string, [string, string][]][] = [
  ["Mission and vision", [["mission", "Mission"], ["vision", "Vision"]]],
  ["Problem", [["problem", "Problem they solve"]]],
  ["Target market and ICP", [["target_market", "Target market"], ["icp", "Ideal customer profile"]]],
  ["Product", [["product", "Product"], ["client_value", "How it helps clients"]]],
  ["Market analysis", [["market_brief", "Market brief"]]],
  ["Competition", [["competitive_landscape", "Competition landscape"]]],
];

function byAgent(strategy: Strategy, agent: string): Recommendation[] {
  return strategy.recommendations.filter((item) => item.agent === agent);
}

function Recommendations({ strategy, agent }: { strategy: Strategy; agent: string }) {
  const items = byAgent(strategy, agent);
  if (!items.length) {
    const status = strategy.sub_agents[agent];
    return <p className="muted">No recommendations ({status?.error || status?.status || "missing"}).</p>;
  }
  return (
    <div className="rec-list">
      {items.map((item) => (
        <article key={item.id} className="rec">
          <h5>
            {item.title} <Hypothesis basis={item.basis} />
          </h5>
          <p>
            {item.recommendation} <Cites ids={item.evidence_ids} />
          </p>
        </article>
      ))}
    </div>
  );
}

function Hypotheses({ strategy }: { strategy: Strategy }) {
  const items = byAgent(strategy, "competitive_strategy").sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99));
  if (!items.length) return <p className="muted">No competitive hypotheses.</p>;
  return (
    <div className="rank-list">
      {items.map((item) => (
        <article key={item.id} className="rank">
          <div className="rank-score">
            <span className="rank-n">#{item.rank ?? "?"}</span>
            <span className="score">
              {item.score ?? "?"}
              <small>/20</small>
            </span>
            <div className="score-bar">
              <span style={{ width: `${((item.score ?? 0) / 20) * 100}%` }} />
            </div>
          </div>
          <div>
            <h5>
              {item.title} <Cites ids={[item.id]} />
            </h5>
            <p>
              {item.recommendation} <Cites ids={item.evidence_ids} />
            </p>
            {item.validation_question && (
              <p className="ask">
                <span>Validate by asking</span> {item.validation_question}
              </p>
            )}
          </div>
        </article>
      ))}
    </div>
  );
}

export function StrategyView({ strategy }: { strategy: Strategy }) {
  const { snapshot } = strategy;
  return (
    <Section
      icon="🧭"
      accent="violet"
      title={<>GTM strategy · {snapshot.company.name}</>}
      meta={
        <>
          <ExternalLink url={snapshot.company.website} />
          <Badge status={snapshot.status} label={`snapshot ${snapshot.status}`} />
          <Badge status={strategy.status} label={`strategy ${strategy.status}`} />
        </>
      }
      actions={
        <button
          className="btn ghost"
          onClick={() => downloadJSON(strategy, `gtm-strategy-${strategy.input_run_id}.json`)}
        >
          Download strategy JSON
        </button>
      }
    >
      <div className="snapshot">
        {SNAPSHOT_GROUPS.map(([group, keys]) => (
          <div key={group} className="snapshot-group">
            <h5>{group}</h5>
            {keys.map(([key, label]) => {
              const line = snapshot.lines[key];
              return (
                <p key={key}>
                  <span className="label">{label}</span>{" "}
                  {line?.status === "found" ? (
                    <>
                      {line.text} <Hypothesis basis={line.basis} />
                      <Cites ids={[...line.evidence_ids, ...line.recommendation_ids]} />
                    </>
                  ) : (
                    <span className="muted">unknown</span>
                  )}
                </p>
              );
            })}
          </div>
        ))}
      </div>
      {snapshot.line_errors && Object.keys(snapshot.line_errors).length > 0 && (
        <p className="muted small">Lines that failed validation: {Object.keys(snapshot.line_errors).join(", ")}</p>
      )}
      <Tabs
        tabs={[
          {
            label: "Competitive analysis",
            count: byAgent(strategy, "competitive_strategy").length,
            content: <Hypotheses strategy={strategy} />,
          },
          {
            label: "Sales strategy",
            count: byAgent(strategy, "challenger_salesman").length,
            content: <Recommendations strategy={strategy} agent="challenger_salesman" />,
          },
          {
            label: "Market analysis",
            count: byAgent(strategy, "market_analysis").length,
            content: <Recommendations strategy={strategy} agent="market_analysis" />,
          },
          {
            label: "Themes and gaps",
            content: (
              <div className="two-col">
                <div>
                  <h5>Themes (ideas the specialists agree on)</h5>
                  <ul className="facts">
                    {strategy.themes.length === 0 && <li className="muted">No themes.</li>}
                    {strategy.themes.map((theme) => (
                      <li key={theme.title}>
                        <strong>{theme.title}</strong>{" "}
                        <span className="muted small">
                          {theme.agents.map((agent) => AGENT_LABELS[agent] ?? agent).join(", ")}
                        </span>
                        <Cites ids={theme.recommendation_ids} />
                      </li>
                    ))}
                  </ul>
                </div>
                <div>
                  <h5>Gaps (missing evidence)</h5>
                  <ul className="facts">
                    {strategy.gaps.length === 0 && <li className="muted">No gaps listed.</li>}
                    {strategy.gaps.map((gap) => (
                      <li key={gap}>{gap}</li>
                    ))}
                  </ul>
                </div>
              </div>
            ),
          },
        ]}
      />
    </Section>
  );
}
