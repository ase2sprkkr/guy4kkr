"""Stateless Qt workflows for creating and transforming structures."""
from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any

from ase2sprkkr.bindings.empty_spheres import add_empty_spheres
from PyQt6.QtWidgets import QMessageBox, QWidget

from guy4ase.ase.element_assignment import ElementAssignmentDraft
from guy4ase.gui.application.operation_results import EmptySpheresResult
from guy4ase.gui.application.workspace_controller import Busy, WorkspaceController
from guy4ase.gui.dialogs.structures.build_2d import select_build_2d_structure
from guy4ase.gui.dialogs.structures.database import select_structure_prototype
from guy4ase.gui.dialogs.structures.element_assignment import select_site_elements
from guy4ase.gui.dialogs.structures.empty_spheres import select_empty_spheres_parameters
from guy4ase.gui.dialogs.structures.online_database import select_online_structure
from guy4ase.gui.dialogs.structures.spacegroup_selector import (
    select_spacegroup,
    select_spacegroup_from_prototype,
)
from guy4ase.gui.misc.dialog_flow import DialogAction, chain_dialogs
from guy4ase.gui.misc.structure_wait import (
    document_change_applied,
    wait_for_structure,
)
from guy4ase.physics.lattice import detect_structure_kind


def copy_structure_snapshot(atoms: Any) -> Any:
    """Return a detached structure snapshot, preserving ``None``."""
    return None if atoms is None else atoms.copy()


def _element_assignment_draft(atoms: Any) -> ElementAssignmentDraft | None:
    """Build an element-assignment draft only when a structure exists."""
    snapshot = copy_structure_snapshot(atoms)
    return None if snapshot is None else ElementAssignmentDraft(snapshot)


def warn_if_structure_kind_is_unknown(atoms: Any, parent: QWidget) -> None:
    """Explain that loaded atoms are not a supported bulk/layered document."""
    if detect_structure_kind(atoms) != "unknown":
        return
    QMessageBox.warning(
        parent,
        "Unknown Structure Type",
        "The loaded structure could not be recognized as a supported "
        "3D bulk or SPR-KKR 2D layered structure. Check its periodic "
        "boundary conditions and, for a 2D structure, its left, central, "
        "and right regions before calculating.",
    )


def edit_current_structure(
    controller: WorkspaceController,
    parent: QWidget,
    editor: Callable[..., Any],
    *,
    error_title: str,
) -> bool:
    """Edit a revision-tagged structure snapshot and commit it on acceptance."""
    snapshot = wait_for_structure(
        parent,
        partial(
            controller.read_structure,
            copy_structure_snapshot,
            reason="reading the structure for an editor",
        ),
    )
    if isinstance(snapshot, Busy):
        return False
    generation, source = snapshot
    if source is None:
        QMessageBox.information(
            parent, "No Structure", "Load or create a structure first."
        )
        return False

    try:
        atoms = editor(source, parent=parent)
        if atoms is None:
            return False
        change = wait_for_structure(
            parent,
            partial(
                controller.replace_structure,
                atoms,
                expected_generation=generation,
                restarted=True,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - editor/backend boundary
        QMessageBox.critical(
            parent,
            error_title,
            f"Failed to edit structure:\n{exc}",
        )
        return False

    if isinstance(change, Busy):
        return False
    return document_change_applied(parent, change)


def edit_site_elements(
    controller: WorkspaceController,
    parent: QWidget,
) -> bool:
    """Edit site occupations and commit the accepted draft transactionally."""
    draft_result = wait_for_structure(
        parent,
        partial(
            controller.read_structure,
            _element_assignment_draft,
            reason="reading the structure for element assignment",
        ),
    )
    if isinstance(draft_result, Busy):
        return False
    generation, draft = draft_result
    if draft is None:
        QMessageBox.information(
            parent, "No Structure", "Load or create a structure first."
        )
        return False

    result = select_site_elements(draft, parent=parent, apply=False)
    if result is None or result == DialogAction.BACK:
        return False

    change = wait_for_structure(
        parent,
        partial(
            controller.apply_structure_edit,
            lambda atoms: result.apply(atoms),
            expected_generation=generation,
        ),
    )
    if isinstance(change, Busy):
        return False
    return document_change_applied(parent, change)


def create_structure(
    controller: WorkspaceController, parent: QWidget
) -> Any | None:
    generation = controller.generation
    atoms = chain_dialogs(
        select_spacegroup,
        select_site_elements,
        parent=parent,
    )
    if atoms is not None:
        change = wait_for_structure(
            parent,
            partial(
                controller.replace_structure,
                atoms,
                expected_generation=generation,
            ),
        )
        if isinstance(change, Busy) or not document_change_applied(parent, change):
            return None
    return atoms


def create_structure_from_database(
    controller: WorkspaceController, parent: QWidget
) -> Any | None:
    generation = controller.generation
    atoms = chain_dialogs(
        select_structure_prototype,
        select_spacegroup_from_prototype,
        select_site_elements,
        parent=parent,
    )
    if atoms is not None:
        change = wait_for_structure(
            parent,
            partial(
                controller.replace_structure,
                atoms,
                expected_generation=generation,
            ),
        )
        if isinstance(change, Busy) or not document_change_applied(parent, change):
            return None
        warn_if_structure_kind_is_unknown(atoms, parent)
    return atoms


def download_structure(
    controller: WorkspaceController, parent: QWidget
) -> Any | None:
    generation = controller.generation
    atoms = select_online_structure(parent=parent)
    if atoms is not None:
        change = wait_for_structure(
            parent,
            partial(
                controller.replace_structure,
                atoms,
                expected_generation=generation,
            ),
        )
        if isinstance(change, Busy) or not document_change_applied(parent, change):
            return None
        warn_if_structure_kind_is_unknown(atoms, parent)
    return atoms


def build_2d_structure(
    controller: WorkspaceController,
    parent: QWidget,
    *,
    surface_mode: bool = False,
) -> Any | None:
    snapshot = wait_for_structure(
        parent,
        partial(
            controller.read_structure,
            copy_structure_snapshot,
            reason="reading the structure for the 2D editor",
        ),
    )
    if isinstance(snapshot, Busy):
        return None
    generation, atoms = snapshot
    if atoms is None:
        QMessageBox.information(
            parent, "No Structure", "Load or create a structure first."
        )
        return None
    try:
        result = select_build_2d_structure(
            atoms,
            parent=parent,
            surface_mode=surface_mode,
        )
        if result is not None:
            change = wait_for_structure(
                parent,
                partial(
                    controller.replace_structure,
                    result,
                    expected_generation=generation,
                    restarted=True,
                ),
            )
            if isinstance(change, Busy) or not document_change_applied(
                parent, change
            ):
                return None
        return result
    except Exception as exc:  # noqa: BLE001 - dialog/backend boundary
        QMessageBox.critical(
            parent,
            "Build 2D Structure Error",
            f"Failed to build 2D structure:\n{exc}",
        )
        return None


def update_empty_spheres(
    controller: WorkspaceController, parent: QWidget
) -> bool:
    """Find empty spheres explicitly and publish the resulting structure."""
    generation = controller.generation
    recalculate = bool(controller.workspace.empty_spheres_added)
    previous_result = controller.workspace.result
    initial_parameters = (
        previous_result.parameters
        if isinstance(previous_result, EmptySpheresResult)
        else None
    )
    parameters = select_empty_spheres_parameters(
        initial=initial_parameters, parent=parent
    )
    if parameters is None:
        return False

    def edit(atoms: Any, previous_count: int) -> tuple[Any, int]:
        if previous_count:
            if previous_count > len(atoms):
                raise ValueError(
                    "Stored empty-sphere provenance no longer matches the structure."
                )
            candidate = atoms.copy()
            trailing = candidate.sites[-previous_count:]
            if not all(site.is_vacuum() for site in trailing):
                raise ValueError(
                    "Previously generated empty spheres are no longer the trailing sites."
                )
            del candidate[-previous_count:]
            base_count = len(candidate)
            add_empty_spheres(candidate, method="inhouse", **parameters)
            return candidate, len(candidate) - base_count

        candidate = add_empty_spheres(
            atoms, copy=True, method="inhouse", **parameters
        )
        if candidate is atoms:
            return atoms, 0
        return candidate, len(candidate) - len(atoms)

    try:
        change = wait_for_structure(
            parent,
            partial(
                controller.update_empty_spheres,
                edit,
                expected_generation=generation,
                parameters=parameters,
            ),
        )
        if isinstance(change, Busy) or not document_change_applied(
            parent, change
        ):
            return False
    except Exception as exc:  # noqa: BLE001 - optional finder/backend boundary
        QMessageBox.critical(
            parent,
            "Empty Spheres Error",
            f"Failed to update empty spheres:\n{exc}",
        )
        return False

    if controller.workspace.empty_spheres_added == 0:
        QMessageBox.information(
            parent,
            "Empty Spheres",
            (
                "No empty spheres were found. Previously generated empty spheres "
                "were removed."
                if recalculate
                else "No empty spheres were found for this structure."
            ),
        )
    return True
