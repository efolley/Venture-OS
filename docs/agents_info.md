# Agent information

VentureOS coordinates 6 specialized agents through 1 central harness. The code provides role specifications, a fixed workflow preview, and shared runtime foundations for trusted plugins. Web Intelligence has a simple adapter-based implementation described in [its setup guide](web_intelligence.md); other business agents and remaining functionality below are (planned). See [Current State](agents_todo.md#current-state).

The initial audience is small B2B agencies and technical consultancies. The target deployment is PostgreSQL by default with local files and optional scale adapters; persistence is not implemented yet.

## Shared execution model (planned)

The harness assigns bounded tasks, assembles context, validates outputs, and owns state, approvals, permissions, budgets, retries, and recovery. Agents return structured artifacts instead of directly controlling downstream execution. External content is untrusted evidence, never authority to change instructions.

Findings retain provenance and distinguish facts, inferences, and observed customer outcomes. Memory is tenant-scoped structured storage; RAG is optional and is not required for Web Intelligence company memory.

## Agent index

- [Web Intelligence](../agents/web_intelligence.md)
- [Competitive Strategy](../agents/competitive_strategy.md)
- [Challenger Salesman](../agents/challenger_salesman.md)
- [Presentation Builder](../agents/presentation_builder.md)
- [Product Builder](../agents/product_builder.md)
- [Workflow Automation](../agents/workflow_automation.md)

## Web Intelligence

### Purpose

Provide current, sourced company intelligence for downstream agents.

### Task

Research company problems, trends, and buying signals; refresh relevant information; organize evidence.

### Architecture

Input: Company name, website, business brief, research questions, and freshness requirements.

Web search and fetch → source capture → structured model analysis → validation → scoped PostgreSQL memory → harness handoff.

Output: Company profile, problems, trends, buying signals, sources, timestamps, uncertainties, and contradictory evidence.

Handoff: Competitive Strategy, then other authorized agents through accepted artifacts.

### Functionality

Search and page-fetch tools gather information. Agent reasoning performs extraction and analysis; separate analysis tools are optional. Save, retrieve, and refresh research by tenant and company. This memory is structured persistence, not RAG.

See [implementation, limits, and verification](web_intelligence.md#completed-research-workflow).

## Competitive Strategy

### Purpose

Turn accepted research into testable commercial opportunities.

### Task

Compare competitors, alternatives, pricing, positioning, and market gaps.

### Architecture (planned)

Input: Accepted evidence brief and business constraints.

Accepted artifacts → comparative analysis → evidence checks → opportunity assessment → harness.

Output: Alternatives, pricing evidence, ranked hypotheses, rationale, disconfirming evidence, and validation questions.

Handoff: Challenger Salesman through the harness.

### Functionality (planned)

Compare like-for-like offers, preserve evidence dates, identify assumptions, and revise hypotheses using customer feedback.

## Challenger Salesman

### Purpose

Translate an opportunity into a provisional ICP and defensible offer.

### Task

Define targeting criteria, commercial insight, tailored outreach drafts, and customer validation questions.

### Architecture (planned)

Input: Accepted research, opportunity assessment, and customer feedback when available.

Accepted artifacts → ICP and offer reasoning → draft personalization → validation → harness review.

Output: ICP criteria, offer hypothesis, outreach drafts, and buyer questions.

Handoff: Human review and Presentation Builder through the harness.

### Functionality (planned)

Support personalization with evidence, label hypotheses, record objections, and update the ICP from observed feedback. Messages remain drafts.

## Presentation Builder

### Purpose

Package an approved offer into a concise customer proposal.

### Task

Present the UVP, scope, assumptions, proposed terms, and measurable success criteria.

### Architecture (planned)

Input: Reviewed ICP, offer, supporting evidence, scope, and constraints.

Reviewed artifacts → proposal composition → document rendering → claim and layout checks → harness.

Output: Versioned proposal with evidence references and explicit proposed terms.

Handoff: Human review and customer validation through the harness.

### Functionality (planned)

Use simple templates, preserve traceability, expose missing information, and prepare reviewable artifacts.

## Product Builder

### Purpose

Deliver the smallest prototype that tests a validated customer need.

### Task

Generate scoped code, integrations, relevant tests, and implementation notes.

### Architecture (planned)

Input: Accepted customer-validation decision, scoped requirements, and acceptance criteria.

Validated scope → build plan → code artifacts → optional isolated execution → acceptance checks → harness.

Output: Prototype, test results when execution is enabled, integration notes, and known limitations.

Handoff: Human review and Workflow Automation through the harness.

### Functionality (planned)

Generate code without executing it by default. Use an approved isolated execution adapter when enabled; deployment requires separate authorization.

## Workflow Automation

### Purpose

Execute authorized operational actions and capture actual outcomes.

### Task

Handle approved email, CRM, onboarding, and delivery operations.

### Architecture (planned)

Input: Exact approved action specification, artifact version, relevant context, and permitted tool scope.

Approved specification → Tool Gateway policy check → action ledger → MCP or service adapter → receipt → harness.

Output: Execution receipts, operational status, failures, and outcome observations.

Handoff: Outcome tracking and strategy revision through the harness.

### Functionality (planned)

Verify approval binding, prevent duplicates, reconcile ambiguous results, and preserve auditable action records.

## Related documentation

- [Agent TODO lists](agents_todo.md)
- [Architecture](architecture.md)
- [Storage interfaces](architecture/storage.md)
- [Safety](architecture/safety.md)
