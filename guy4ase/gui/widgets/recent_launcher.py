"""Qt rendering helpers for launching recently used structures and outputs."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QToolButton, QWidget

from guy4ase.gui.application.recent_files import RecentFiles, RecentKind
from guy4ase.gui.application.recent_presentation import RecentLaunch, recent_launch


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


def build_recent_launch_menu(
    parent: QWidget,
    history: RecentFiles,
    open_recent: Callable[[RecentKind, str], None],
    *,
    menu: QMenu | None = None,
    base: str | Path | None = None,
) -> QMenu:
    """Build or refresh the shared Structures/Outputs Continue menu.

    Reuse existing submenus when refreshing. ``QMenu.clear()`` removes their
    actions but does not destroy child menu objects immediately, so recreating
    the submenus on every history update would retain an ever-growing set of
    QObject children on the long-lived parent menu.
    """
    if menu is None and isinstance(parent, QToolButton):
        menu = parent.menu()
    if menu is None:
        menu = QMenu(parent)

    existing_submenus = {
        submenu.title(): submenu
        for action in menu.actions()
        if (submenu := action.menu()) is not None
    }
    menu.clear()

    for title, kind in (
        ("Structures", "structure"),
        ("Outputs", "output"),
    ):
        submenu = existing_submenus.pop(title, None)
        if submenu is None:
            submenu = QMenu(title, menu)
        populate_recent_menu(
            submenu,
            history,
            kind,
            lambda path, item_kind=kind: open_recent(item_kind, path),
            base=base,
        )
        menu.addMenu(submenu)

    for obsolete in existing_submenus.values():
        obsolete.deleteLater()
    return menu


__all__ = [
    "RecentLaunch",
    "build_recent_launch_menu",
    "populate_recent_menu",
    "recent_launch",
    "recent_path_label",
]
