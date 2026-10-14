from __future__ import annotations

import logging
import sys
from pathlib import Path

from PyQt6.QtCore import QObject, Qt
from PyQt6.QtWidgets import QApplication, QWidget

from guy4ase.gui.application.persistent_jobs import PersistentJobSource
from guy4ase.gui.application.projects import (
    ProjectConflictError,
    ProjectRepository,
    ProjectRepositoryError,
)
from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.settings import ApplicationSettings
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.dialogs.main_window import MainWindow
from guy4ase.gui.dialogs.project_browser import ProjectBrowserDialog
from guy4ase.gui.dialogs.workflow_window import WorkflowWindow
from guy4ase.gui.flows import calculation as calculation_flow

logger = logging.getLogger(__name__)


class GuiApplication(QObject):
    """Compose and own one shared GUI session and its top-level windows."""

    def __init__(
        self,
        *,
        workspace: WorkspaceState | None = None,
        recent_files_path: str | Path | None = None,
        settings_path: str | Path | None = None,
        persistent_jobs: PersistentJobSource | None = None,
        project_repository: ProjectRepository | None = None,
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
        self.persistent_jobs = (
            persistent_jobs if persistent_jobs is not None else PersistentJobSource()
        )
        self.projects = (
            project_repository
            if project_repository is not None
            else ProjectRepository()
        )
        self._active_project_id: str | None = None
        self._workflow_window: WorkflowWindow | None = None
        self._main_window: MainWindow | None = None
        self._project_browser: ProjectBrowserDialog | None = None

    @property
    def active_project_id(self) -> str | None:
        return self._active_project_id

    def create_workflow_window(self) -> WorkflowWindow:
        """Return the session's workflow view, creating it lazily."""
        if self._workflow_window is None:
            self._workflow_window = WorkflowWindow(
                self.controller,
                self.recent_files,
                open_expert=self.show_main_window,
                settings=self.settings,
                persistent_job_changed=self._persistent_job_changed,
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
                persistent_job_changed=self._persistent_job_changed,
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
                persistent_job_changed=self._persistent_job_changed,
            )
        )
        self.controller.structureChanged.connect(refresh_result_context)
        self.controller.resultChanged.connect(refresh_result_context)
        self.controller.resultSelectionRequested.connect(widget.select_result)
        self.recent_files.changed.connect(refresh_result_context)
        refresh_result_context()

    def set_active_project(self, project_id: str | None) -> None:
        """Select the project that receives subsequently created persistent runs."""
        if project_id is not None:
            try:
                project_id = self.projects.project(str(project_id)).id
            except (KeyError, ProjectRepositoryError, ValueError):
                project_id = None
        self._active_project_id = project_id
        if self._project_browser is not None:
            self._project_browser.set_active_project(project_id)

    def _persistent_job_changed(self, job_id: str) -> None:
        """Reload a live job and idempotently assign it to the active project."""
        job = self.persistent_jobs.job_changed(job_id)
        project_id = self._active_project_id
        if job is None or project_id is None:
            return

        # This is a concrete idempotent application operation, not repository
        # merge policy. If another instance edits the project concurrently, read
        # the new snapshot and retry this one add-run operation once.
        for attempt in range(2):
            try:
                project = self.projects.project(project_id)
            except KeyError:
                self.set_active_project(None)
                return
            except (ProjectRepositoryError, ValueError):
                logger.exception(
                    "Cannot load active project %s for persistent run %s",
                    project_id,
                    job_id,
                )
                return

            if job_id in project.persistent_refs:
                return
            try:
                self.projects.save(
                    project.add_run(job_id),
                    expected_generation=project.generation,
                )
                return
            except ProjectConflictError:
                if attempt == 0:
                    continue
                logger.warning(
                    "Active project %s changed repeatedly while assigning run %s",
                    project_id,
                    job_id,
                )
            except (ProjectRepositoryError, KeyError, ValueError):
                logger.exception(
                    "Cannot assign persistent run %s to active project %s",
                    job_id,
                    project_id,
                )
                return

    def show_workflow_window(self) -> None:
        """Show and activate the workflow view."""
        self._show_window(self.create_workflow_window())

    def show_main_window(self) -> None:
        """Show and activate the expert view."""
        self._show_window(self.create_main_window())

    def show_project_browser(self) -> None:
        """Show and activate the application-owned project browser."""
        if self._project_browser is None:
            dialog = ProjectBrowserDialog(
                self.projects,
                self.persistent_jobs,
                active_project_id=self._active_project_id,
            )
            dialog.activeProjectRequested.connect(self.set_active_project)
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
