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


def recent_path_label(path: str | Path, base: str | Path | None = None) -> str:
    """Prefer a short descendant path; never display ``..``-based relatives."""
    absolute = Path(path).expanduser().resolve()
    absolute_text = str(absolute)
    base_path = Path.cwd() if base is None else Path(base).expanduser().resolve()
    try:
        relative = absolute.relative_to(base_path)
    except ValueError:
        return absolute_text
    relative_text = str(relative)
    return relative_text if len(relative_text) < len(absolute_text) else absolute_text


def populate_recent_menu(
    menu: QMenu,
    history: RecentFiles,
    kind: RecentKind,
    open_recent: Callable[[str], None],
    *,
    base: str | Path | None = None,
) -> QMenu:
    """Populate one recent-file menu using the shared presentation policy."""
    menu.clear()
    paths = history.paths(kind)
    if not paths:
        action = QAction("(No recent files)", menu)
        action.setEnabled(False)
        menu.addAction(action)
        return menu

    for path in paths:
        action = QAction(recent_path_label(path, base), menu)
        action.setToolTip(path)
        action.triggered.connect(
            lambda _checked=False, item_path=path: open_recent(item_path)
        )
        menu.addAction(action)
    return menu


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
    base: str | Path | None = None,
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
        populate_recent_menu(
            submenu,
            history,
            kind,
            lambda path, item_kind=kind: open_recent(item_kind, path),
            base=base,
        )
    return menu
