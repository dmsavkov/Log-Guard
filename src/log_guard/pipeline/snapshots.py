"""Save numbered intermediate line snapshots after each pipeline phase."""

from __future__ import annotations

from typing import Protocol


class SnapshotSession(Protocol):
    def save_intermediate(self, name: str, content: str) -> object: ...


def save_phase_lines(session: SnapshotSession, filename: str, lines: list[str]) -> None:
    session.save_intermediate(filename, "\n".join(lines))
