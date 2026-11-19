// Shapes returned by the pipeline API. Only the fields the UI reads are typed.

export type Evidence = {
  id: string;
  statement: string;
  excerpt: string;
  basis: string;
  tags: string[];
  url: string;
  retrieved_at: string;
  round: number;
};

export type Coverage = Record<string, { status: string; missing: string[] }>;

export type Competitor = {
  name: string;
  website: string;
  positioning: string[];
  pricing: string[];
  pricing_status: "found" | "not_published" | "not_checked";
};

export type Pack = {
  run_id: string;
  status: string;
  company: { name: string; website: string } & Record<string, string[] | string>;
  market: Record<string, string[]>;
  sales: Record<string, string[]>;
  competitors: Competitor[];
  evidence: Evidence[];
  sources: unknown[];
  coverage: Coverage;
  limits_hit: string[];
  uncertainties: string[];
};

export type Recommendation = {
  id: string;
  agent: string;
  title: string;
  recommendation: string;
  rationale?: string;
  basis: string;
  evidence_ids: string[];
  rank?: number;
  score?: number;
  sub_scores?: Record<string, number>;
  validation_question?: string;
};

export type SnapshotLine = {
  status: string;
  text: string;
  basis: string;
  evidence_ids: string[];
  recommendation_ids: string[];
};

export type Strategy = {
  input_run_id: string;
  status: string;
  company: { name: string; website: string };
  gaps: string[];
  sub_agents: Record<string, { status: string; error?: string }>;
  recommendations: Recommendation[];
  themes: { title: string; recommendation_ids: string[]; agents: string[] }[];
  snapshot: {
    status: string;
    company: { name: string; website: string };
    lines: Record<string, SnapshotLine>;
    line_errors?: Record<string, string>;
  };
};

export type Cited = { text: string; based_on: string[] };

export type Action = {
  id: string;
  purpose: string;
  title: string;
  description: string;
  owner: string;
  priority: number;
  horizon: string;
  success_metric: string;
  based_on: string[];
};

export type PMResult = {
  input_run_id: string;
  status: string;
  company: { name: string; website: string };
  decision: string | null;
  baseline: { status: string; missing: string[] };
  hitl: { question: string; research_gaps: string[] } | null;
  research_request: { gaps: string[] } | null;
  use_case: {
    statement: string;
    icp: Cited;
    core_problem: Cited;
    mvp_solution: Cited;
    why: string;
    why_based_on: string[];
    key_assumption: string;
    alternatives?: { statement: string; why_not: string }[];
  } | null;
  action_plan: Action[];
  one_pager: {
    headline: string;
    problem: string;
    value_proposition: string;
    target_customer: string;
    key_points: string[];
    proof_points: string[];
    call_to_action: string;
  } | null;
  mvp_idea: {
    product_goal: string;
    target_user: string;
    core_job: string;
    must_have_features: { name: string; why: string; based_on: string[] }[];
    out_of_scope: string[];
    success_criteria: string[];
    demo_scenario: string;
  } | null;
};

export type JobEvent = { step: string; status: string; data: Record<string, unknown> };

export type Reply = {
  kind: "pack" | "clarify" | "text" | "error";
  message: string;
  run_id?: string;
  pack?: Pack;
  candidates?: { name: string; website: string }[];
};

export type RunSummary = {
  id: string;
  parent_run_id: string | null;
  company: string;
  website: string;
  status: string;
  usage: Record<string, number>;
  created_at: string;
};

export type Round = {
  number: number;
  gap: string;
  query: string;
  site: string;
  model_calls: number;
  error: string;
  dropped?: unknown;
  coverage?: unknown;
};

export type SourceRow = {
  url: string;
  round: number;
  rejection_reason: string | null;
  id: string | null;
  kind: string | null;
};
