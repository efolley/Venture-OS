# Agent TODO lists

Checked items are implemented shared foundations. Unchecked agent items remain planned. Web Intelligence is implemented; the other 5 business agents remain planned. Complete an item only when implemented and verified.

## Current State

Web Intelligence now searches company, news, jobs, and supporting sources; produces quoted findings with fact/inference labels, freshness warnings, and conflicts; and saves reports, source/finding records, and parsed-text snapshots locally.
Run `PYTHONPATH=src:. python3 -m streamlit run UI/app.py --server.address 127.0.0.1` to research a company or browse Data Management, with Tavily, local Ollama qwen3:8b, and PostgreSQL configured in .env.
All Web Intelligence backlog items are complete for this bounded implementation and verified by 96 regression tests, 8 golden evidence evals, and a real Basecamp run; source coverage can be incomplete and quotation matches do not prove semantic accuracy.

## Shared prerequisites

- [x] Define a common agent execution interface and typed task/artifact envelopes.
- [x] Implement model and tool interfaces with tenant-scoped authorization.
- [x] Add PostgreSQL persistence, task leases, checkpoints, and controlled recovery.
- [x] Add budgets, bounded retries, deadlines, HITL approval, and runtime validation.
- [x] Add content checks, audit records, OpenTelemetry tracing, and offline regression evals.
- [x] Preserve the credential-free preview while adding optional runtime execution.

## Web Intelligence

- [x] Define company research input and structured evidence output schemas.
- [x] Add Tavily search and bounded HTTPS fetching with public-address pinning, bounded redirect validation, socket timeouts, local request pacing, and source timestamps.
- [x] Gather company pages, news, job postings, and credible supporting sources.
- [x] Extract problems, trends, and buying signals with validated structured model output through an injected provider.
- [x] Attach evidence and distinguish observed facts from inferences and unknowns.
- [x] Store runs, source records, and structured findings in PostgreSQL; use BlobStore for large snapshots.
- [x] Save accepted results through the runtime; retrieve tenant-scoped company memory with freshness limits and refresh via new tasks without RAG.
- [x] Validate evidence coverage, freshness, conflicting findings, and output structure.
- [x] Integrate runtime checkpoints, deadline/budget checks, and accepted artifact handoffs; retries use existing harness policy.
- [x] Add evals for extraction quality, stale sources, source failures, prompt injection, PII handling, and tenant isolation.

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
