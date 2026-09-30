"""Stateless Qt workflow for running and adopting a calculation."""
from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox, QWidget

from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.dialogs.run_calculation import SprkkrRunWindow


def run_calculation(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    parent: QWidget,
) -> SprkkrRunWindow | None:
    """Open a run window and adopt its result through the controller."""
    workspace = controller.workspace
    if (
        workspace.atoms is None
        or workspace.input_parameters is None
        or not workspace.directory
    ):
        return None

    def finished(result) -> None:
        adoption = controller.adopt_result(result)
        if adoption.output_path is not None:
            recent_files.remember("output", adoption.output_path)
        if adoption.potential_error is not None:
            QMessageBox.warning(
                parent,
                "Potential Load Warning",
                "The calculation finished, but its potential could not be "
                f"loaded:\n{adoption.potential_error}",
            )

    window = SprkkrRunWindow(
        atoms=workspace.atoms,
        input_parameters=workspace.input_parameters,
        directory=workspace.directory,
        parent=parent,
        on_finished=finished,
    )
    window.show()
    return window
