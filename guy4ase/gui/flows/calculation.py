"""Stateless Qt workflow for running and adopting a calculation."""
from __future__ import annotations

from functools import partial

from PyQt6.QtWidgets import QMessageBox, QWidget

from guy4ase.gui.application.calculation_runs import ActiveRunRegistry
from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.result_loading import load_result
from guy4ase.gui.application.workspace_controller import Busy, WorkspaceController
from guy4ase.gui.dialogs.run_calculation import SprkkrRunWindow
from guy4ase.gui.misc.structure_wait import wait_for_structure


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
    active_runs: ActiveRunRegistry,
    parent: QWidget,
) -> SprkkrRunWindow | None:
    """Open a run window and adopt its result through the controller."""
    if active_runs.count and not _continue_with_parallel_run(parent):
        return None

    try:
        request = wait_for_structure(
            parent, controller.create_calculation_request
        )
    except ValueError:
        return None
    if isinstance(request, Busy):
        return None

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
        try:
            loaded = load_result(
                result,
                fallback_directory=request.directory,
            )
            adoption = wait_for_structure(
                parent,
                partial(
                    controller.adopt_calculation_result,
                    loaded,
                    expected_generation=request.generation,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - backend metadata varies
            QMessageBox.critical(
                parent,
                "Result Adoption Error",
                "The calculation finished, but its result could not be "
                f"adopted:\n{exc}",
            )
            return
        if not isinstance(adoption, Busy):
            adoption_completed(adoption)

    window = SprkkrRunWindow(
        request=request,
        structure_gate=controller.structure_gate,
        parent=parent,
        on_finished=finished,
        on_activity_started=active_runs.register,
        on_activity_ended=active_runs.unregister,
        on_prepared=controller.notify_structure_prepared,
    )
    window.show()
    return window
