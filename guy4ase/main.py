from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QApplication

from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.dialogs.main_window import MainWindow
from guy4ase.gui.dialogs.workflow_window import WorkflowWindow
from guy4ase.gui.flows.operations import GuiOperations


class GuiApplication(QObject):
    """Compose and own one shared GUI session and its top-level windows."""

    def __init__(
        self,
        *,
        workspace: WorkspaceState | None = None,
        recent_files_path: str | Path | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = WorkspaceController(workspace, parent=self)
        self.recent_files = RecentFiles(
            Path(recent_files_path) if recent_files_path is not None else None
        )
        self.recent_files.load()
        self.operations = GuiOperations(
            self.controller,
            self.recent_files,
            parent=self,
        )
        self._workflow_window: WorkflowWindow | None = None
        self._main_window: MainWindow | None = None

    def create_workflow_window(self) -> WorkflowWindow:
        """Return the session's workflow view, creating it lazily."""
        if self._workflow_window is None:
            self._workflow_window = WorkflowWindow(
                self.controller,
                self.recent_files,
                self.operations,
                open_expert=self.show_main_window,
            )
        return self._workflow_window

    def create_main_window(self) -> MainWindow:
        """Return the session's expert view, creating it lazily."""
        if self._main_window is None:
            self._main_window = MainWindow(
                self.controller,
                self.recent_files,
                self.operations,
            )
        return self._main_window

    def show_workflow_window(self) -> None:
        """Show and activate the workflow view."""
        self._show_window(self.create_workflow_window())

    def show_main_window(self) -> None:
        """Show and activate the expert view."""
        self._show_window(self.create_main_window())

    @staticmethod
    def _show_window(window: WorkflowWindow | MainWindow) -> None:
        window.show()
        window.raise_()
        window.activateWindow()


def main() -> int:
    app = QApplication(sys.argv)
    gui = GuiApplication(parent=app)
    gui.show_workflow_window()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
