"""Stateless Qt workflow for running and adopting a calculation."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QFileDialog, QMessageBox, QWidget

from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.workspace_controller import (
    CalculationNotReady,
    WorkspaceController,
)
from guy4ase.gui.dialogs.guided_input import select_guided_input_parameters
from guy4ase.gui.dialogs.profiles import (
    ProfileSelectionDialog,
    profile_description,
)
from guy4ase.gui.dialogs.run_calculation import SprkkrRunWindow
from guy4ase.gui.misc.structure_wait import document_change_applied


def choose_working_directory(
    controller: WorkspaceController,
    parent: QWidget,
    *,
    title: str = "Select Calculation Directory",
) -> bool:
    """Choose and publish the workspace calculation directory."""
    start_directory = controller.directory or str(Path.home())
    directory = QFileDialog.getExistingDirectory(
        parent,
        title,
        start_directory,
    )
    if not directory:
        return False
    controller.change_directory(str(directory))
    return True


def _select_profile(parent: QWidget) -> tuple[bool, str | None]:
    """Run the post-parameter execution step and preserve automatic profiles."""
    dialog = ProfileSelectionDialog(parent)
    if dialog.exec() != dialog.DialogCode.Accepted:
        return False, None
    return True, dialog.profile_name()


def run_calculation(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    parent: QWidget,
    *,
    select_profile: bool = True,
    profile_name: str | None = None,
) -> SprkkrRunWindow | None:
    """Choose execution, open a run window and adopt its result."""
    try:
        request = controller.create_calculation_request()
    except CalculationNotReady:
        return None

    if select_profile:
        accepted, profile_name = _select_profile(parent)
        if not accepted:
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

    def finished(loaded) -> None:
        adoption = controller.adopt_calculation_result(
            loaded,
            expected_major=request.generation.major,
        )
        adoption_completed(adoption)

    try:
        description = profile_description(profile_name)
    except (KeyError, TypeError, ValueError):
        description = None

    window = SprkkrRunWindow(
        request=request,
        profile_name=profile_name,
        profile_description=description,
        parent=parent,
        on_finished=finished,
    )
    window.show()
    return window


def configure_and_run_task(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    parent: QWidget,
    task: str,
    *,
    dataset_default_mode: str,
) -> SprkkrRunWindow | None:
    """Configure one Guided task, commit it, choose execution, and run it."""
    try:
        if (
            not controller.directory
            and not choose_working_directory(
                controller,
                parent,
                title="Choose the directory for this calculation",
            )
        ):
            return None

        generation = controller.generation
        atoms = controller.atoms
        if atoms is None:
            QMessageBox.information(
                parent,
                "No Structure",
                "Load or create a structure first.",
            )
            return None

        parameters = select_guided_input_parameters(
            task,
            parent=parent,
            atoms=atoms,
            dataset_default_mode=dataset_default_mode,
        )
        if parameters is None:
            return None
        if not document_change_applied(
            parent,
            controller.replace_input_parameters(
                parameters,
                expected_generation=generation,
            ),
        ):
            return None
        return run_calculation(
            controller,
            recent_files,
            parent,
        )
    except (ImportError, ModuleNotFoundError) as exc:
        QMessageBox.critical(
            parent,
            "Task Unavailable",
            f"The {task.upper()} task is not available:\n{exc}",
        )
        return None
