import { downloadJSON } from "../api";
import type { PMResult } from "../types";
import { Badge, Cites, Section, Tabs } from "./ui";

const PURPOSE: Record<string, { icon: string; tone: string }> = {
  validate: { icon: "🧪", tone: "cyan" },
  prepare: { icon: "🛠", tone: "violet" },
  deliver: { icon: "🚀", tone: "pink" },
};

export function PMView({
  result,
  onDecision,
  busy = false,
}: {
  result: PMResult;
  onDecision?: (decision: "research" | "proceed") => void;
  busy?: boolean;
}) {
  const { baseline, use_case: useCase } = result;
  const actions = result.action_plan ?? [];
  return (
    <Section
      icon="🎯"
      accent="pink"
      title={<>PM plan · {result.company.name}</>}
      meta={
        <>
          <Badge status={result.status} />
          <Badge status={baseline.status} label={`baseline ${baseline.status}`} />
          {result.decision && <Badge status="clarify" label={`decision ${result.decision}`} />}
        </>
      }
      actions={
        <button className="btn ghost" onClick={() => downloadJSON(result, `pm-plan-${result.input_run_id}.json`)}>
          Download PM JSON
        </button>
      }
    >
      {baseline.missing.length > 0 && (
        <p className="gaps-line">
          <span>Baseline gaps</span> {baseline.missing.join(", ")}
        </p>
      )}

      {result.status === "hitl_required" && result.hitl && (
        <div className="hitl">
          <div className="hitl-head">
            <span className="pulse" /> Human check (HITL 1)
          </div>
          <p>{result.hitl.question}</p>
          <p className="muted small">
            Research gaps that would fill it: {result.hitl.research_gaps.join(", ") || "none mapped"}
          </p>
          {onDecision && (
            <div className="hitl-actions">
              <button className="btn" disabled={busy} onClick={() => onDecision("research")}>
                Research more
              </button>
              <button className="btn primary" disabled={busy} onClick={() => onDecision("proceed")}>
                Proceed with gaps
              </button>
            </div>
          )}
        </div>
      )}

      {result.status === "research_requested" && result.research_request && (
        <div className="hitl">
          <div className="hitl-head">Sent back to Research</div>
          <p>Gaps to collect: {result.research_request.gaps.join(", ")}</p>
        </div>
      )}

      {useCase && (
        <div className="use-case">
          <span className="eyebrow">Use case</span>
          <p className="statement">{useCase.statement}</p>
          <dl>
            <dt>Ideal customer</dt>
            <dd>
              {useCase.icp.text} <Cites ids={useCase.icp.based_on} />
            </dd>
            <dt>Core problem</dt>
            <dd>
              {useCase.core_problem.text} <Cites ids={useCase.core_problem.based_on} />
            </dd>
            <dt>MVP solution</dt>
            <dd>
              {useCase.mvp_solution.text} <Cites ids={useCase.mvp_solution.based_on} />
            </dd>
            <dt>Why</dt>
            <dd>
              {useCase.why} <Cites ids={useCase.why_based_on} />
            </dd>
            <dt>Key assumption</dt>
            <dd className="assumption">{useCase.key_assumption}</dd>
            {useCase.alternatives?.map((alternative) => (
              <div key={alternative.statement} className="alt">
                <dt>Not chosen</dt>
                <dd>
                  {alternative.statement} <span className="muted">({alternative.why_not})</span>
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      {actions.length > 0 && (
        <>
          <h4>Action plan</h4>
          <ol className="timeline">
            {actions.map((action) => {
              const purpose = PURPOSE[action.purpose] ?? { icon: "•", tone: "gray" };
              return (
                <li key={action.id} className={`step purpose-${purpose.tone}`}>
                  <span className="step-dot">{purpose.icon}</span>
                  <div>
                    <div className="step-tags">
                      <span className={`badge tone-${purpose.tone}`}>{action.purpose}</span>
                      <span className="chip">P{action.priority}</span>
                      <span className="chip">{action.horizon}</span>
                      <span className="chip">{action.owner}</span>
                    </div>
                    <h5>{action.title}</h5>
                    <p>
                      {action.description} <Cites ids={action.based_on} />
                    </p>
                    <p className="metric">
                      <span>Success metric</span> {action.success_metric}
                    </p>
                  </div>
                </li>
              );
            })}
          </ol>
        </>
      )}

      {(result.one_pager || result.mvp_idea) && (
        <Tabs
          tabs={[
            {
              label: "1-pager",
              content: result.one_pager ? (
                <div className="doc">
                  <h3 className="doc-title">{result.one_pager.headline}</h3>
                  <p>
                    <span className="label">Problem</span> {result.one_pager.problem}
                  </p>
                  <p>
                    <span className="label">Value proposition</span> {result.one_pager.value_proposition}
                  </p>
                  <p>
                    <span className="label">Target customer</span> {result.one_pager.target_customer}
                  </p>
                  <div className="two-col">
                    <div>
                      <h5>Key points</h5>
                      <ul className="facts">
                        {result.one_pager.key_points.map((point) => (
                          <li key={point}>{point}</li>
                        ))}
                      </ul>
                    </div>
                    <div>
                      <h5>Proof points</h5>
                      <ul className="facts">
                        {result.one_pager.proof_points.map((point) => (
                          <li key={point}>{point}</li>
                        ))}
                      </ul>
                    </div>
                  </div>
                  <p className="cta">{result.one_pager.call_to_action}</p>
                </div>
              ) : (
                <p className="muted">No 1-pager.</p>
              ),
            },
            {
              label: "MVP idea",
              content: result.mvp_idea ? (
                <div className="doc">
                  <h3 className="doc-title">{result.mvp_idea.product_goal}</h3>
                  <p>
                    <span className="label">Target user</span> {result.mvp_idea.target_user}
                  </p>
                  <p>
                    <span className="label">Core job</span> {result.mvp_idea.core_job}
                  </p>
                  <h5>Must-have features</h5>
                  <div className="features">
                    {result.mvp_idea.must_have_features.map((feature) => (
                      <div key={feature.name} className="feature">
                        <strong>{feature.name}</strong>
                        <p>
                          {feature.why} <Cites ids={feature.based_on} />
                        </p>
                      </div>
                    ))}
                  </div>
                  <div className="two-col">
                    <div>
                      <h5>Out of scope</h5>
                      <ul className="facts">
                        {result.mvp_idea.out_of_scope.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </div>
                    <div>
                      <h5>Success criteria</h5>
                      <ul className="facts">
                        {result.mvp_idea.success_criteria.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </div>
                  </div>
                  <p>
                    <span className="label">How a user tries it</span> {result.mvp_idea.demo_scenario}
                  </p>
                  <p className="muted small">A proposal of what to build. Nothing has been built.</p>
                </div>
              ) : (
                <p className="muted">No MVP idea.</p>
              ),
            },
          ]}
        />
      )}
    </Section>
  );
}
