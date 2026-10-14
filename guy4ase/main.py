from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QObject, Qt
from PyQt6.QtWidgets import QApplication, QWidget

from guy4ase.gui.application.persistent_jobs import PersistentJobSource
from guy4ase.gui.application.projects import ProjectRepository
from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.settings import ApplicationSettings
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.dialogs.main_window import MainWindow
from guy4ase.gui.dialogs.project_browser import ProjectBrowserDialog
from guy4ase.gui.dialogs.workflow_window import WorkflowWindow
from guy4ase.gui.flows import calculation as calculation_flow


class GuiApplication(QObject):
    """Compose and own one shared GUI session and its top-level windows."""

    def __init__(
        self,
        *,
        workspace: WorkspaceState | None = None,
        recent_files_path: str | Path | None = None,
        settings_path: str | Path | None = None,
        project_repository: ProjectRepository | None = None,
        persistent_jobs: PersistentJobSource | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = WorkspaceController(workspace, parent=self)
        self.recent_files = RecentFiles(
            Path(recent_files_path) if recent_files_path is not None else None,
            parent=self,
        )
        self.recent_files.load()
        self.settings = ApplicationSettings(
            Path(settings_path) if settings_path is not None else None
        )
        self.settings.load()
        self._project_repository = project_repository
        self._persistent_jobs = persistent_jobs
        self._workflow_window: WorkflowWindow | None = None
        self._main_window: MainWindow | None = None
        self._project_browser: ProjectBrowserDialog | None = None

    @property
    def project_repository(self) -> ProjectRepository:
        """Return the application-owned project repository, creating it lazily."""
        repository = self._project_repository
        if repository is None:
            repository = ProjectRepository(parent=self)
            self._project_repository = repository
        return repository

    @property
    def persistent_jobs(self) -> PersistentJobSource:
        """Return the one application-owned persistent-job source."""
        source = self._persistent_jobs
        if source is None:
            source = PersistentJobSource(parent=self)
            self._persistent_jobs = source
        return source

    def create_workflow_window(self) -> WorkflowWindow:
        """Return the session's workflow view, creating it lazily."""
        if self._workflow_window is None:
            self._workflow_window = WorkflowWindow(
                self.controller,
                self.recent_files,
                open_expert=self.show_main_window,
                settings=self.settings,
            )
            self._wire_window(self._workflow_window)
        return self._workflow_window

    def create_main_window(self) -> MainWindow:
        """Return the session's expert view, creating it lazily."""
        if self._main_window is None:
            self._main_window = MainWindow(
                self.controller,
                self.recent_files,
                self.settings,
            )
            self._wire_window(self._main_window)
        return self._main_window

    def _wire_window(self, window: WorkflowWindow | MainWindow) -> None:
        """Connect application-owned actions exposed by a top-level window."""
        self._wire_result_actions(window)
        window.browser_panel.projectBrowserRequested.connect(
            self.show_project_browser
        )

    def _wire_result_actions(self, window: WorkflowWindow | MainWindow) -> None:
        """Connect explicit result actions and one authoritative result store."""
        widget = window.result_actions_widget
        if widget is None:
            return

        def refresh_result_context(*_args) -> None:
            widget.set_workspace_state(
                self.controller.structure_id,
                self.controller.state_id,
            )
            widget.set_results(self.controller.result_store)

        widget.useStateRequested.connect(self.controller.use_result_state)
        widget.recomputeRequested.connect(
            lambda result_id, target=window: calculation_flow.recompute_result(
                self.controller,
                self.recent_files,
                target,
                result_id,
            )
        )
        self.controller.structureChanged.connect(refresh_result_context)
        self.controller.resultChanged.connect(refresh_result_context)
        self.controller.resultSelectionRequested.connect(widget.select_result)
        self.recent_files.changed.connect(refresh_result_context)
        refresh_result_context()

    def show_workflow_window(self) -> None:
        """Show and activate the workflow view."""
        self._show_window(self.create_workflow_window())

    def show_main_window(self) -> None:
        """Show and activate the expert view."""
        self._show_window(self.create_main_window())

    def show_project_browser(self) -> None:
        """Show and activate the one application-owned project browser."""
        if self._project_browser is None:
            dialog = ProjectBrowserDialog(
                self.project_repository,
                self.persistent_jobs,
            )
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            dialog.destroyed.connect(self._project_browser_closed)
            self._project_browser = dialog
        self._show_window(self._project_browser)

    def _project_browser_closed(self, *_args) -> None:
        self._project_browser = None

    @staticmethod
    def _show_window(window: QWidget) -> None:
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
