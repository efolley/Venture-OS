"""GTM and PM results saved as JSON files, 1 per Research run.

`runs/gtm/<research run id>.json` holds the strategy pack and `runs/pm/<research run id>.json`
the PM result, so they survive a restart and the Stored research view can reopen them.
"""

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from research.contracts import JsonObject

DEFAULT_RESULTS_DIR = Path("runs") / "gtm"
DEFAULT_PM_RESULTS_DIR = Path("runs") / "pm"


def _safe_id(research_run_id: str) -> str:
    """Only a UUID becomes a file name, so a request can never point outside the folder."""
    return str(uuid.UUID(research_run_id))


@dataclass
class ResultFiles:
    gtm_dir: Path = field(default_factory=lambda: DEFAULT_RESULTS_DIR)
    pm_dir: Path = field(default_factory=lambda: DEFAULT_PM_RESULTS_DIR)

    @staticmethod
    def _write(path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    @staticmethod
    def _read(path: Path) -> JsonObject | None:
        if not path.exists():
            return None
        return cast(JsonObject, json.loads(path.read_text(encoding="utf-8")))

    def save_strategy(self, research_run_id: str, strategy: object) -> None:
        self._write(self.gtm_dir / f"{_safe_id(research_run_id)}.json", strategy)

    def load_strategy(self, research_run_id: str) -> JsonObject | None:
        return self._read(self.gtm_dir / f"{_safe_id(research_run_id)}.json")

    def save_pm(self, research_run_id: str, result: object) -> None:
        self._write(self.pm_dir / f"{_safe_id(research_run_id)}.json", result)

    def load_pm(self, research_run_id: str) -> JsonObject | None:
        return self._read(self.pm_dir / f"{_safe_id(research_run_id)}.json")
