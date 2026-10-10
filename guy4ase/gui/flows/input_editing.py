"""Expert-mode input-parameter use cases over the current workspace."""
from __future__ import annotations

from functools import partial
from typing import Any

from PyQt6.QtWidgets import QWidget

from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.workspace_controller import Busy, WorkspaceController
from guy4ase.gui.dialogs.expert_input import (
    edit_input_parameters,
    select_input_parameters,
)
from guy4ase.gui.flows import files as file_flows
from guy4ase.gui.flows.structures import copy_structure_snapshot
from guy4ase.gui.misc.structure_wait import (
    document_change_applied,
    wait_for_structure,
)


def create_input_parameters(
    controller: WorkspaceController,
    parent: QWidget,
    *,
    task: str = "scf",
) -> bool:
    """Create parameters for a task from a revision-tagged structure snapshot."""
    snapshot = wait_for_structure(
        parent,
        partial(
            controller.read_structure,
            copy_structure_snapshot,
            reason="reading the structure for the parameter editor",
        ),
    )
    if isinstance(snapshot, Busy):
        return False
    generation, atoms = snapshot
    parameters = select_input_parameters(atoms, parent=parent, task=task)
    if parameters is None:
        return False
    return document_change_applied(
        parent,
        controller.replace_input_parameters(
            parameters,
            expected_generation=generation,
        ),
    )


def edit_current_input_parameters(
    controller: WorkspaceController,
    parent: QWidget,
    *,
    create_task: str | None = "scf",
    show_changed_only: bool = False,
) -> bool:
    """Edit current parameters and commit only against the captured revision."""
    if controller.workspace.input_parameters is None:
        if create_task is None:
            return False
        return create_input_parameters(
            controller,
            parent,
            task=create_task,
        )

    def capture(atoms: Any) -> tuple[Any, Any]:
        parameters = controller.workspace.input_parameters
        return (
            copy_structure_snapshot(atoms),
            None
            if parameters is None
            else parameters.copy(copy_values=True),
        )

    snapshot = wait_for_structure(
        parent,
        partial(
            controller.read_structure,
            capture,
            reason="reading the structure for the parameter editor",
        ),
    )
    if isinstance(snapshot, Busy):
        return False
    generation, (atoms, parameters) = snapshot
    if parameters is None:
        return False

    edited = edit_input_parameters(
        parameters,
        parent=parent,
        show_changed_only=show_changed_only,
        atoms=atoms,
    )
    if edited is None:
        return False
    return document_change_applied(
        parent,
        controller.replace_input_parameters(
            edited,
            expected_generation=generation,
        ),
    )


def load_and_edit_input_parameters(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    parent: QWidget,
) -> bool:
    """Load workspace input parameters and immediately open the expert editor."""
    if not file_flows.choose_and_load_input_parameters(
        controller,
        recent_files,
        parent,
    ):
        return False
    return edit_current_input_parameters(
        controller,
        parent,
        create_task=None,
        show_changed_only=True,
    )
