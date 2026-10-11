"""Shared UI policy for launching recently used structures and outputs."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QToolButton, QWidget

from guy4ase.gui.application.recent_files import RecentFiles, RecentKind


@dataclass(frozen=True)
class RecentLaunch:
    """The recent file selected for the primary Continue action."""

    kind: RecentKind
    path: str

    @property
    def title(self) -> str:
        return f"Continue: {Path(self.path).name}"


def recent_launch(history: RecentFiles) -> RecentLaunch | None:
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


def build_recent_launch_menu(
    parent: QWidget,
    history: RecentFiles,
    open_recent: Callable[[RecentKind, str], None],
    *,
    menu: QMenu | None = None,
) -> QMenu:
    """Build or refresh the shared Structures/Outputs Continue menu."""
    if menu is None and isinstance(parent, QToolButton):
        menu = parent.menu()
    if menu is None:
        menu = QMenu(parent)
    else:
        menu.clear()

    for title, kind in (
        ("Structures", "structure"),
        ("Outputs", "output"),
    ):
        submenu = menu.addMenu(title)
        paths = history.paths(kind)
        if not paths:
            action = QAction("(No recent files)", submenu)
            action.setEnabled(False)
            submenu.addAction(action)
            continue

        for path in paths:
            action = QAction(path, submenu)
            action.triggered.connect(
                lambda _checked=False, item_kind=kind, item_path=path: open_recent(
                    item_kind, item_path
                )
            )
            submenu.addAction(action)
    return menu
