# Architecture

## Current implementation

A standard-library Python package loads a validated business brief and returns a fixed workflow plan. Six role specifications live in the registry; Markdown contracts describe intended agent behavior. No LLM, tools, persistence, approval enforcement, or runtime evaluation is connected.

## Intended execution model

The harness will own task dependencies, shared evidence, artifacts, permissions, approval records, execution events, and cost accounting. Agents receive bounded tasks and return structured artifacts. Tool access is granted per task. Web pages and imported documents are untrusted evidence, never authority to change instructions or permissions.

The first workflow is research → strategy → ICP/offer → human review → proposal → customer validation → prototype → approved operations → outcomes. Revision returns to strategy. External outreach may be run as a separately approved validation action before building; it must not depend on finishing a prototype.

## Handoff contract

Each future artifact must include a run/task identifier, producing agent, artifact type, content, evidence references (URL and retrieval time), assumptions, unresolved questions, and evaluation result. Keep sourced facts, model inferences, and observed outcomes distinguishable. Downstream tasks consume accepted artifacts only.

## Acceptance criteria for the runtime

- Research: material factual claims have inspectable sources and dates.
- Strategy: alternatives and disconfirming evidence accompany the recommendation.
- Sales: targeting criteria and personalization are supported by evidence.
- Proposal: UVP, scope, assumptions, and measurable success criteria are explicit.
- Product: agreed acceptance checks pass; limitations are documented.
- Operations: actions are authorized and have receipts and idempotency keys.
- Outcomes: metrics include a baseline and observation period; generated artifacts do not count as ROI.

## Harness extension points

1. Provider and tool adapters behind explicit interfaces.
2. Persisted run ledger and resumable task states.
3. Evaluation before dependent tasks are released.
4. Recorded approval bound to the exact artifact/action being approved.
5. Bounded retries, deadlines, and cost budgets; escalate on exhaustion.
6. Duplicate-action prevention before enabling email, CRM writes, or deployment.

These are planned requirements. The preview command does not implement them.
