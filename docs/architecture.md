# Architecture

## Current implementation

The dependency-free preview loads a validated business brief and returns a fixed workflow plan. A separate optional RuntimeHarness supports typed plugin execution, tenant-scoped model/read-only tool interfaces, PostgreSQL tasks with leases and checkpoints, approval binding, budget reservations, runtime validation, audit, basic content checks, and optional OpenTelemetry instrumentation. The CLI offers a local persistent brief demo. The 6 business agents and live provider integrations remain planned. See [Current State](agents_todo.md#current-state) for tested scope and limits.

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

These are target runtime requirements. Shared foundations implement a subset; the preview command does not execute them. See Current State for limitations.
