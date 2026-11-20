# Example outputs

Real, unedited VentureOS runs from 18 November 2026, each made with 1 command such as:

```bash
ventureos-pipeline Vercel --website vercel.com
```

| Company | Use case VentureOS proposed | Sourced facts | Specialist recommendations |
| --- | --- | --- | --- |
| [Vercel](vercel.md) | A preview-gated release check for agent-written frontend changes | 25 | 16 |
| [Linear](linear.md) | A live cross-team initiative roll-up for organizations replacing Jira | 23 | 18 |
| [Baseten](baseten.md) | A pre-launch production readiness check for model endpoints | 25 | 16 |

Each report starts with what a person acts on (use case, action plan, 1-pager, MVP idea), then the company snapshot, the ranked hypotheses, and the known gaps. The Sources section at the end resolves every cited ID: `e` IDs to the word-for-word quote and its URL, and `r` IDs to the specialist recommendation.

These are not polished samples. They show the known limits too: for example, the Linear report finds a mission line while a specialist still lists the mission as missing (see the output-quality TODO list in the main README). Model output differs on every run, and nothing here was reviewed by the companies named.

To render a report from your own run's JSON files:

```bash
ventureos-report runs/linear-pm.json --strategy runs/linear-gtm.json --research runs/linear-research.json --output runs/linear-report.md
```
