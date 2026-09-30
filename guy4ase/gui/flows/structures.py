"""Stateless Qt workflows for creating and transforming structures."""
from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import QMessageBox, QWidget

from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.dialogs.structures.build_2d import select_build_2d_structure
from guy4ase.gui.dialogs.structures.database import select_structure_prototype
from guy4ase.gui.dialogs.structures.element_assignment import select_site_elements
from guy4ase.gui.dialogs.structures.online_database import select_online_structure
from guy4ase.gui.dialogs.structures.spacegroup_selector import (
    select_spacegroup,
    select_spacegroup_from_prototype,
)
from guy4ase.gui.misc.dialog_flow import chain_dialogs
from guy4ase.physics.lattice import detect_structure_kind


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


def create_structure(
    controller: WorkspaceController, parent: QWidget
) -> Any | None:
    atoms = chain_dialogs(
        select_spacegroup,
        select_site_elements,
        back=True,
        kwargs={"parent": parent},
    )
    if atoms is not None:
        controller.set_structure(atoms)
    return atoms


def create_structure_from_database(
    controller: WorkspaceController, parent: QWidget
) -> Any | None:
    atoms = chain_dialogs(
        select_structure_prototype,
        select_spacegroup_from_prototype,
        select_site_elements,
        back=True,
        kwargs={"parent": parent},
    )
    if atoms is not None:
        controller.set_structure(atoms)
        warn_if_structure_kind_is_unknown(atoms, parent)
    return atoms


def download_structure(
    controller: WorkspaceController, parent: QWidget
) -> Any | None:
    atoms = select_online_structure(parent=parent)
    if atoms is not None:
        controller.set_structure(atoms)
        warn_if_structure_kind_is_unknown(atoms, parent)
    return atoms


def build_2d_structure(
    controller: WorkspaceController,
    parent: QWidget,
    *,
    surface_mode: bool = False,
) -> Any | None:
    atoms = controller.workspace.atoms
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
            controller.set_structure(result)
        return result
    except Exception as exc:  # noqa: BLE001 - dialog/backend boundary
        QMessageBox.critical(
            parent,
            "Build 2D Structure Error",
            f"Failed to build 2D structure:\n{exc}",
        )
        return None
