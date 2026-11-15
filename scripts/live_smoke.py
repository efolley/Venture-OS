"""Live smoke check: research real companies with Tavily and Gemini and score each pack.

Makes live, billed calls. Not part of the test suite. Packs are saved to runs/ (git-ignored).

    PYTHONPATH=src python3 scripts/live_smoke.py linear.app baseten.co vercel.com
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from research import MemoryStore, ResearchAgent  # noqa: E402
from research.pack import gtm_gaps  # noqa: E402
from research.providers import TavilySearch, default_model  # noqa: E402


def main(websites: list[str]) -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    out = ROOT / "runs"
    out.mkdir(exist_ok=True)
    store = MemoryStore()
    agent = ResearchAgent(default_model(), TavilySearch(), store)
    ready = 0
    for website in websites:
        started = time.time()
        result = agent.run("", website)
        pack = result.pack
        assert pack is not None
        gaps = gtm_gaps(pack)
        ready += not gaps
        rounds = store.list_rounds(result.run_id)
        (out / f"{website.replace('/', '_')}.json").write_text(json.dumps(pack, indent=2))
        print(f"\n== {pack['company']['name']} ({website}) status={pack['status']} "
              f"limits_hit={pack['limits_hit']} {time.time() - started:.0f}s "
              f"usage={store.get_run(result.run_id)['usage']}")  # type: ignore[index]
        print(f"   evidence={len(pack['evidence'])} sources={len(pack['sources'])} "
              f"competitors={[c['name'] for c in pack['competitors']]}")
        for field, cov in pack["coverage"].items():
            print(f"   {field:12} {cov['status']:9} missing={cov['missing'][:6]}")
        print(f"   GTM ready: {'yes' if not gaps else 'no, missing ' + ', '.join(gaps)}")
        for r in rounds[1:]:
            print(f"   r{r['number']} {r['gap'][:30]:30} err={r['error'] or ''} q={r['query'][:70]}")
            for note in r["dropped"][:3]:
                print(f"        dropped: {note[:110]}")
    print(f"\n{ready} of {len(websites)} packs are GTM ready.")
    return 0 if ready == len(websites) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or ["linear.app", "baseten.co", "vercel.com"]))
