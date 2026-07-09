"""Per-run pipeline session with intermediate debug snapshots."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from log_guard.lg.storage import run_dir


class LgRunSession:
    """Writes numbered intermediate files under runs/<id>/intermediate/."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.phases: dict[str, Any] = {}
        self.metrics: dict[str, Any] = {"phases": {}}
        self.config: dict[str, Any] = {"skip_judge": True, "skip_judge_reason": "lg_cli"}
        self.intermediate_dir = run_dir(run_id) / "intermediate"
        self.intermediate_dir.mkdir(parents=True, exist_ok=True)
        self._distillation: str = ""

    def save_intermediate(self, name: str, content: str) -> Path:
        path = self.intermediate_dir / name
        path.write_text(content, encoding="utf-8")
        return path

    def record_phase(self, phase: str, payload: dict[str, Any]) -> None:
        self.phases[phase] = payload
        self.metrics["phases"][phase] = payload

    def flush_metrics(self) -> None:
        path = run_dir(self.run_id) / "phases.json"
        path.write_text(json.dumps(self.metrics, indent=2, default=str), encoding="utf-8")

    def save_distillation(self, text: str) -> None:
        self._distillation = text
        self.save_intermediate("distillation.md", text)

    @property
    def distillation(self) -> str:
        return self._distillation

    def save_phases_json(self) -> None:
        self.flush_metrics()
