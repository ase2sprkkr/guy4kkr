"""Qt-independent semantic presentation vocabulary shared by GUI views."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

ActionCategory = Literal[
    "structure", "load", "calculation", "destructive", "neutral"
]
RecentLaunchKind = Literal["structure", "output"]


class RecentHistory(Protocol):
    """Read contract needed to choose the primary recent-file action."""

    @property
    def last_kind(self) -> str | None: ...

    def paths(self, kind: RecentLaunchKind) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class RecentLaunch:
    """The recent structure/output selected for the primary Continue action."""

    kind: RecentLaunchKind
    path: str

    def __post_init__(self) -> None:
        if self.kind not in {"structure", "output"}:
            raise ValueError("Recent launch kind must be 'structure' or 'output'.")

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

    last_kind = history.last_kind
    if last_kind == "structure" and paths["structure"]:
        kind: RecentLaunchKind = "structure"
    elif last_kind == "output" and paths["output"]:
        kind = "output"
    else:
        kind = "output" if paths["output"] else "structure"
    return RecentLaunch(kind, paths[kind][0])
