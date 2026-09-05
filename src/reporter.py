from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .models import QuestionResult


class RunReporter:
    def __init__(self) -> None:
        self.started_at = datetime.now(timezone.utc)
        self.results: list[QuestionResult] = []

    def add(self, result: QuestionResult) -> None:
        self.results.append(result)

    def save(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        filename = self.started_at.strftime("run_%Y%m%d_%H%M%S.json")
        path = directory / filename
        payload = {
            "started_at": self.started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "summary": {
                status: sum(item.status == status for item in self.results)
                for status in ("correct", "incorrect", "dry-run", "error")
            },
            "results": [item.to_dict() for item in self.results],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

