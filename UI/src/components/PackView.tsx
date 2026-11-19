import { downloadJSON } from "../api";
import type { Pack } from "../types";
import { Badge, Cites, Collapsible, ExternalLink, Section } from "./ui";

const FIELDS: [string, string][] = [
  ["company", "Company"],
  ["market", "Market"],
  ["competitors", "Competitors"],
  ["sales", "Sales"],
];
const ITEM_LABELS: Record<string, string> = {
  offering: "What they sell",
  mission: "Mission",
  vision: "Vision",
  problem: "Problem they solve",
  category: "Category",
  size_growth: "Size or growth",
  trends: "Trends",
  target_customer: "Target customer",
  buyer_role: "Buyer role",
  pricing_model: "Pricing model",
  channel: "Sales channel",
  buying_signals: "Buying signals",
};
const PRICING: Record<string, string> = {
  found: "",
  not_published: "pricing not published",
  not_checked: "pricing not checked",
};

function Facts({ ids, pack }: { ids: string[]; pack: Pack }) {
  const byId = new Map(pack.evidence.map((item) => [item.id, item]));
  const items = ids.map((id) => byId.get(id)).filter((item) => item !== undefined);
  if (!items.length) return <p className="muted small">missing</p>;
  return (
    <ul className="facts">
      {items.map((item) => (
        <li key={item.id}>
          {item.statement}
          {item.basis !== "fact" && <span className="badge tone-amber subtle">inference</span>}
          <Cites ids={[item.id]} />
        </li>
      ))}
    </ul>
  );
}

export function PackView({ pack }: { pack: Pack }) {
  const company = pack.company;
  return (
    <Section
      icon="🔎"
      accent="cyan"
      title={<>Evidence pack · {company.name}</>}
      meta={
        <>
          <ExternalLink url={company.website} />
          <Badge status={pack.status} />
          <span className="muted small">
            {pack.evidence.length} facts · {pack.sources.length} sources
          </span>
        </>
      }
      actions={
        <button className="btn ghost" onClick={() => downloadJSON(pack, `evidence-pack-${pack.run_id}.json`)}>
          Download JSON
        </button>
      }
    >
      <div className="coverage">
        {FIELDS.map(([field, label]) => {
          const entry = pack.coverage[field] ?? { status: "partial", missing: [] };
          return (
            <div key={field} className={`coverage-cell ${entry.status}`}>
              <span className="coverage-label">{label}</span>
              <Badge status={entry.status} />
              {entry.missing.length > 0 && <span className="muted small">missing {entry.missing.join(", ")}</span>}
            </div>
          );
        })}
      </div>
      <div className="fact-grid">
        {(["offering", "mission", "vision", "problem"] as const).map((key) => (
          <div key={key}>
            <h5>{ITEM_LABELS[key]}</h5>
            <Facts ids={(company[key] as string[]) ?? []} pack={pack} />
          </div>
        ))}
      </div>
      <Collapsible title="Market, sales, and competitors">
        {(["market", "sales"] as const).map((field) => (
          <div key={field} className="fact-grid">
            {Object.entries(pack[field]).map(([key, ids]) => (
              <div key={key}>
                <h5>{ITEM_LABELS[key] ?? key}</h5>
                <Facts ids={ids} pack={pack} />
              </div>
            ))}
          </div>
        ))}
        <h4>Competitors</h4>
        {pack.competitors.length === 0 && <p className="muted">none found</p>}
        <div className="fact-grid">
          {pack.competitors.map((rival) => (
            <div key={rival.name}>
              <h5>
                {rival.name}{" "}
                {rival.website ? <ExternalLink url={rival.website} /> : <span className="muted small">website unknown</span>}
                {PRICING[rival.pricing_status] && <span className="muted small"> · {PRICING[rival.pricing_status]}</span>}
              </h5>
              <Facts ids={[...new Set([...rival.positioning, ...rival.pricing])]} pack={pack} />
            </div>
          ))}
        </div>
        {pack.uncertainties?.length > 0 && (
          <>
            <h4>Notes</h4>
            <ul className="facts">
              {pack.uncertainties.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </>
        )}
      </Collapsible>
      <Collapsible title={`Evidence (${pack.evidence.length} items)`}>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Statement</th>
                <th>Quote</th>
                <th>Basis</th>
                <th>Tags</th>
                <th>Source</th>
                <th>Round</th>
              </tr>
            </thead>
            <tbody>
              {pack.evidence.map((item) => (
                <tr key={item.id}>
                  <td className="mono">{item.id}</td>
                  <td>{item.statement}</td>
                  <td className="quote">“{item.excerpt}”</td>
                  <td>{item.basis}</td>
                  <td className="small">{item.tags.join(", ")}</td>
                  <td>
                    <ExternalLink url={item.url} />
                  </td>
                  <td>{item.round}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Collapsible>
    </Section>
  );
}
