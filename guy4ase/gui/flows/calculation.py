"""Stateless Qt workflow for running and recording a calculation."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QFileDialog, QMessageBox, QWidget

from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.window_geometry import window_placement
from guy4ase.gui.application.workspace_controller import (
    CalculationNotReady,
    WorkspaceController,
)
from guy4ase.gui.dialogs.guided_input import (
    GuidedInputParametersDialog,
    select_guided_input_parameters,
)
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
    start_directory = controller.directory or str(Path.home())
    directory = QFileDialog.getExistingDirectory(parent, title, start_directory)
    if not directory:
        return False
    controller.change_directory(str(directory))
    return True


def _position_like_window(window: QWidget, window_id: str | None) -> None:
    if window_id is None:
        return
    placement = window_placement(
        window,
        window_id,
        default_size=(window.width(), window.height()),
    )
    window.move(placement.geometry.topLeft())


def _select_profile(
    parent: QWidget,
    *,
    position_like_window: str | None = None,
) -> tuple[bool, str | None]:
    dialog = ProfileSelectionDialog(parent)
    _position_like_window(dialog, position_like_window)
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
    position_like_window: str | None = None,
) -> SprkkrRunWindow | None:
    task = controller.current_task()
    if task is not None and not controller.can_run_task(task):
        QMessageBox.information(
            parent,
            "Task Not Available",
            f"{task.upper()} cannot be run with the current workspace state.",
        )
        return None

    try:
        request = controller.create_calculation_request()
    except CalculationNotReady:
        return None

    if select_profile:
        accepted, profile_name = _select_profile(
            parent,
            position_like_window=position_like_window,
        )
        if not accepted:
            return None

    def adoption_completed(adoption) -> None:
        if adoption.output_path is not None:
            recent_files.remember("output", adoption.output_path)
        if adoption.potential_error is not None:
            QMessageBox.warning(
                parent,
                "Potential Load Warning",
                "The calculation finished and was recorded, but its potential "
                f"could not be loaded:\n{adoption.potential_error}",
            )

    def finished(loaded) -> None:
        adoption = controller.adopt_calculation_result(loaded, request=request)
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
    _position_like_window(window, position_like_window)
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
    try:
        if not controller.can_run_task(task):
            QMessageBox.information(
                parent,
                "Task Not Available",
                f"{str(task).upper()} cannot be run with the current workspace state.",
            )
            return None

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
            QMessageBox.information(parent, "No Structure", "Load or create a structure first.")
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
            position_like_window="guided-input",
        )
    except (ImportError, ModuleNotFoundError) as exc:
        QMessageBox.critical(
            parent,
            "Task Unavailable",
            f"The {task.upper()} task is not available:\n{exc}",
        )
        return None


def recompute_result(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    parent: QWidget,
    result_id: int,
) -> SprkkrRunWindow | None:
    """Re-run historical settings on the state active in the workspace."""
    record = controller.result_history.result(result_id)
    task = record.task_name
    if not task or record.input_parameters is None:
        return None

    if not controller.can_run_task(task):
        QMessageBox.information(
            parent,
            "Task Not Available",
            (
                f"{task.upper()} cannot be run with the potential currently active "
                "in the workspace."
            ),
        )
        return None

    if not controller.directory and not choose_working_directory(
        controller,
        parent,
        title="Choose the directory for this calculation",
    ):
        return None

    generation = controller.generation
    atoms = controller.atoms
    if atoms is None:
        return None

    try:
        parameters = record.input_parameters.copy(copy_values=True)
    except AttributeError:
        return None
    dialog = GuidedInputParametersDialog(
        task,
        parameters,
        parent=parent,
        atoms=atoms,
    )
    if dialog.exec() != dialog.DialogCode.Accepted:
        return None

    if not document_change_applied(
        parent,
        controller.replace_input_parameters(
            dialog.parameters(),
            expected_generation=generation,
        ),
    ):
        return None
    return run_calculation(
        controller,
        recent_files,
        parent,
        position_like_window="guided-input",
    )
