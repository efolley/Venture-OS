# Agent TODO lists

Checked items are implemented shared foundations. Unchecked agent items remain planned. Only the Research agent is implemented, as a standalone module that is not connected to the harness; the optional runtime currently supports trusted registered plugins and a local brief demo. Complete an item only when implemented and verified.

## Current State

VentureOS has shared runtime foundations and an optional PostgreSQL demo, The Research agent runs standalone (see [Research agent](research.md)); the other business agents and live integrations are not implemented.
From the repository root, run `PYTHONPATH=src python3 -m ventureos --brief examples/agency-brief.json` without credentials or extra dependencies.
Expect a JSON workflow preview showing planned tasks, agent assignments, and review checkpoints; this command does not research companies, call models, or perform external actions.

## Shared prerequisites

- [x] Define a common agent execution interface and typed task/artifact envelopes.
- [x] Implement model and tool interfaces with tenant-scoped authorization.
- [x] Add PostgreSQL persistence, task leases, checkpoints, and controlled recovery.
- [x] Add budgets, bounded retries, deadlines, HITL approval, and runtime validation.
- [x] Add content checks, audit records, OpenTelemetry tracing, and offline regression evals.
- [x] Preserve the credential-free preview while adding optional runtime execution.

## Web Intelligence

- [x] Define company research input and structured evidence output schemas.
- [ ] Add web search and fetch adapters with timeouts, rate limits, source timestamps, and safe URL handling.
- [ ] Gather company pages, news, job postings, and credible supporting sources.
- [x] Extract problems, trends, and buying signals with structured model output.
- [x] Attach evidence and distinguish observed facts from inferences and unknowns.
- [ ] Store runs, source records, and structured findings in PostgreSQL; use BlobStore for large snapshots.
- [ ] Implement tenant-scoped save, retrieve, and refresh operations without RAG.
- [ ] Validate evidence coverage, freshness, conflicting findings, and output structure.
- [ ] Integrate harness checkpoints, bounded retries, deadlines, budgets, and accepted handoffs.
- [ ] Add evals for extraction quality, stale sources, source failures, prompt injection, PII handling, and tenant isolation.

## Company Snapshot

- [x] Define the profile contract in agents/company_snapshot.md.
- [ ] Define the profile schema with claim-ID citations.
- [ ] Implement profile generation from an accepted evidence brief.
- [ ] Validate that every statement cites claim IDs and adds no new claims.
- [ ] Add evals for unsupported statements and empty-field handling.

## Competitive Strategy

- [ ] Define comparison and opportunity assessment schemas.
- [ ] Implement evidence-linked comparison of alternatives, pricing, and positioning.
- [ ] Rank hypotheses with explicit criteria, assumptions, and contradictory evidence.
- [ ] Add scoped persistence and feedback-driven revisions.
- [ ] Integrate harness acceptance checks and evals for unsupported gaps and stale pricing.

## Challenger Salesman

- [ ] Define ICP, offer, outreach, and customer-feedback schemas.
- [ ] Implement evidence-backed targeting and commercial insight generation.
- [ ] Generate tailored drafts without sending messages.
- [ ] Persist objections and revise ICP and offer versions.
- [ ] Add harness review and evals for unsupported personalization and commercial claims.

## Presentation Builder

- [ ] Define proposal schema and a simple template.
- [ ] Implement proposal generation from reviewed inputs.
- [ ] Validate UVP, scope, assumptions, proposed terms, and success criteria.
- [ ] Persist versions and artifact references through BlobStore.
- [ ] Add claim-grounding and rendered-layout checks before acceptance.

## Product Builder

- [ ] Define validated scope, prototype artifact, and acceptance-result schemas.
- [ ] Implement scoped code generation and artifact storage.
- [ ] Add an optional isolated execution adapter with resource and network limits.
- [ ] Run relevant acceptance tests when isolated execution is available; label unexecuted checks.
- [ ] Record limitations, dependencies, and build receipts without automatic deployment.
- [ ] Add evals for requirement coverage, execution boundaries, and acceptance reporting.

## Workflow Automation

- [ ] Define action specifications, approval bindings, and receipt schemas.
- [ ] Implement authorized email, CRM, and onboarding adapters behind the Tool Gateway.
- [ ] Persist action ledger entries and idempotency keys before side effects.
- [ ] Handle ambiguous timeouts through reconciliation instead of blind resends.
- [ ] Capture customer responses and operational outcomes with baselines where applicable.
- [ ] Add evals and integration checks for authorization, duplicates, partial failure, and tenant isolation.

See [agent information](agents_info.md) for purpose, inputs, outputs, and handoffs.
