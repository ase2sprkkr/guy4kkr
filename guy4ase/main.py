from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QObject, Qt
from PyQt6.QtWidgets import QApplication, QWidget

from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.result_action_policy import result_action_availability
from guy4ase.gui.application.result_loading import PotentialVersionChanged
from guy4ase.gui.application.result_presentation import present_result_tree
from guy4ase.gui.application.settings import ApplicationSettings
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.dialogs.calculation_history import CalculationHistoryDialog
from guy4ase.gui.dialogs.main_window import MainWindow
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
        self._workflow_window: WorkflowWindow | None = None
        self._main_window: MainWindow | None = None
        self._calculation_history: CalculationHistoryDialog | None = None

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
        window.browser_panel.calculationJobsRequested.connect(
            self.show_calculation_jobs
        )

    def _wire_result_actions(self, window: WorkflowWindow | MainWindow) -> None:
        """Resolve result policy outside widgets and connect explicit user intents."""
        widget = window.result_actions_widget
        if widget is None:
            return

        def refresh_result_context(
            *_args,
            selected_result_id: int | None = None,
        ) -> None:
            selected = (
                widget.selected_result_id
                if selected_result_id is None
                else selected_result_id
            )
            widget.set_model(
                present_result_tree(
                    self.controller.result_store,
                    current_structure_id=self.controller.structure_id,
                    current_state_id=self.controller.state_id,
                    selected_result_id=selected,
                )
            )

        def select_result(result_id: int) -> None:
            refresh_result_context(selected_result_id=result_id)

        def use_result_state(result_id: int) -> None:
            store = self.controller.result_store
            record = store.result(result_id)
            action = result_action_availability(
                store,
                record,
                current_structure_id=self.controller.structure_id,
                current_state_id=self.controller.state_id,
            ).use_state
            if action is None:
                refresh_result_context(selected_result_id=result_id)
                return
            try:
                self.controller.use_result_state(
                    result_id,
                    action.expected_potential,
                )
            except PotentialVersionChanged:
                # The controller remains the final TOCTOU boundary. If the file
                # changed after policy evaluation, refresh the offered action.
                refresh_result_context(selected_result_id=result_id)

        widget.selectionRequested.connect(select_result)
        widget.useStateRequested.connect(use_result_state)
        widget.recomputeRequested.connect(
            lambda result_id, target=window: calculation_flow.recompute_result(
                self.controller,
                self.recent_files,
                target,
                result_id,
            )
        )
        widget.historyRequested.connect(self.show_calculation_jobs)
        self.controller.structureChanged.connect(refresh_result_context)
        self.controller.resultChanged.connect(refresh_result_context)
        self.controller.resultSelectionRequested.connect(select_result)
        self.recent_files.changed.connect(refresh_result_context)
        refresh_result_context()

    def show_workflow_window(self) -> None:
        """Show and activate the workflow view."""
        self._show_window(self.create_workflow_window())

    def show_main_window(self) -> None:
        """Show and activate the expert view."""
        self._show_window(self.create_main_window())

    def show_calculation_jobs(self) -> None:
        """Show and activate the application-owned calculation-job browser."""
        if self._calculation_history is None:
            dialog = CalculationHistoryDialog()
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            dialog.destroyed.connect(self._calculation_history_closed)
            self._calculation_history = dialog
        self._show_window(self._calculation_history)

    def _calculation_history_closed(self, *_args) -> None:
        self._calculation_history = None

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