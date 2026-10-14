"""Qt-independent presentation policy for recently used files."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from guy4ase.gui.application.recent_files import RecentKind


class RecentHistory(Protocol):
    """Read contract needed to choose the primary recent-file action."""

    last_kind: RecentKind | None

    def paths(self, kind: RecentKind) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class RecentLaunch:
    """The recent structure/output selected for the primary Continue action."""

    kind: RecentKind
    path: str

    @property
    def title(self) -> str:
        return f"Continue: {Path(self.path).name}"


def recent_launch(history: RecentHistory) -> RecentLaunch | None:
    """Return the preferred structure/output to continue with, if any."""
    paths = {
        "structure": history.paths("structure"),
        "output": history.paths("output"),
    }
    if not paths["structure"] and not paths["output"]:
        return None

    kind = history.last_kind
    if kind not in paths or not paths[kind]:
        kind = "output" if paths["output"] else "structure"
    return RecentLaunch(kind, paths[kind][0])
