"""Stateless Qt workflow for running and adopting a calculation."""
from __future__ import annotations

from functools import partial

from PyQt6.QtWidgets import QMessageBox, QWidget

from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.dialogs.run_calculation import SprkkrRunWindow
from guy4ase.gui.misc.qt_workspace_access import QtWorkspaceAccess
from guy4ase.gui.misc.workspace_wait import wait_for_workspace


def _continue_with_parallel_run(parent: QWidget) -> bool:
    message = QMessageBox(parent)
    message.setIcon(QMessageBox.Icon.Warning)
    message.setWindowTitle("Calculation Already Running")
    message.setText("A calculation is already running in this workspace.")
    message.setInformativeText(
        "Another run will share the selected directory. Potential file "
        "collisions are not isolated automatically."
    )
    cancel = message.addButton(QMessageBox.StandardButton.Cancel)
    proceed = message.addButton(
        "Run Anyway", QMessageBox.ButtonRole.AcceptRole
    )
    message.setDefaultButton(cancel)
    message.exec()
    return message.clickedButton() is proceed


def run_calculation(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    parent: QWidget,
) -> SprkkrRunWindow | None:
    """Open a run window and adopt its result through the controller."""
    if controller.active_run_count and not _continue_with_parallel_run(parent):
        return None

    try:
        request_result = wait_for_workspace(
            parent, controller.create_calculation_request
        )
    except ValueError:
        return None
    if not request_result.completed:
        return None
    request = request_result.value
    assert request is not None
    workspace_access = QtWorkspaceAccess(controller, parent)

    def adoption_completed(adoption) -> None:
        if adoption.output_path is not None:
            recent_files.remember("output", adoption.output_path)
        if not adoption.adopted:
            QMessageBox.information(
                parent,
                "Calculation Result Not Adopted",
                "The document changed after this calculation was requested. "
                "The result remains available in this run window, but it did "
                "not replace the current workspace.",
            )
        if adoption.potential_error is not None:
            QMessageBox.warning(
                parent,
                "Potential Load Warning",
                "The calculation finished, but its potential could not be "
                f"loaded:\n{adoption.potential_error}",
            )

    def finished(result) -> None:
        workspace_access.retry_call(
            partial(
                controller.adopt_calculation_result,
                result,
                expected_generation=request.generation,
            ),
            on_completed=adoption_completed,
        )

    def prepared(atoms) -> None:
        workspace_access.retry_call(
            partial(controller.try_publish_preparation_refresh, atoms)
        )

    window = SprkkrRunWindow(
        request=request,
        access_gate=controller.access_gate,
        parent=parent,
        on_finished=finished,
        on_activity_started=controller.register_active_run,
        on_activity_ended=controller.unregister_active_run,
        on_prepared=prepared,
    )
    window.show()
    return window
