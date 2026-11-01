# Testing shared prerequisites

## Setup

Use a virtual environment and install `python3 -m pip install -e '.[runtime,test]'`. The preview alone needs no optional dependencies.

For the full suite, set `VENTUREOS_TEST_DSN` to a disposable PostgreSQL database. Tests initialize ventureos_tasks and ventureos_audit and write isolated test tenants. Never use a production database. Without this variable, database tests skip; this is not a complete runtime verification.

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m ventureos.evals tests/fixtures/content_evals.json
PYTHONPATH=src python3 -S -m ventureos --brief examples/agency-brief.json
```

## Pre/post cases

Reports in reports/ preserve the existing per-task pre-implementation failures and post-implementation results. Do not regenerate historical pre reports against completed code. verified_post.txt is the latest full rerun with 34 tests passing against local PostgreSQL. Fixture evaluations are saved in verified_evals.json.

| Task | Tests | Reports |
| --- | --- | --- |
| 1: execution contracts | test_envelopes.py | 01_pre.txt, 01_post.txt |
| 2: tenant-scoped gateways | test_gateways.py | 02_pre.txt, 02_post.txt |
| 3: persistence and recovery | test_store.py | 03_pre.txt, 03_post.txt |
| 4: runtime policies | test_runtime.py | 04_pre.txt, 04_post.txt |
| 5: safety, evals, tracing | test_safety.py, test_telemetry.py | 05_pre.txt, 05_post.txt |
| 6: preview and optional execution | test_preview.py, test_runtime_cli.py | 06_pre.txt, 06_post.txt |

Tests cover negative authorization, invalid artifacts, duplicate submission, competing claims, locked rows, expired leases, restart checkpoints, atomic budget reservations, approval changes, retries, deadlines, content filtering, and payload-free tracing. The offline fixtures are a small content-policy regression set, not a benchmark of business agent quality.

.github/workflows/tests.yml runs tests with PostgreSQL, offline fixtures, and a dependency-free preview on Python 3.10. Hosted CI has not been run locally. Exporters, live providers, external writes, and production deployment are not tested by this suite.

## Web Intelligence

All 12 module cases live in test_web_intelligence.py. Reports web_intelligence_pre.txt, web_intelligence_contracts_post.txt, web_intelligence_execution_post.txt, and web_intelligence_full_post.txt preserve incremental results. The final full suite passed 46 tests including real PostgreSQL persistence with fake web/model adapters. Earlier partial reports intentionally include pending failures or skips.

Live adapter and research CLI coverage stays in test_web_intelligence.py. Reports web_intelligence_live_pre.txt and web_intelligence_live_full_post.txt capture before/after results. The full suite passed 54 cases; paid provider calls remain unverified.
