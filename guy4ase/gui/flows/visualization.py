"""Visualization workflows."""
from __future__ import annotations

from functools import partial
from typing import Any

from ase import Atoms
from ase.visualize import view as ase_view
from PyQt6.QtWidgets import QMessageBox, QWidget

from guy4ase.gui.application.settings import ApplicationSettings
from guy4ase.gui.application.workspace_controller import Busy, WorkspaceController
from guy4ase.gui.misc.structure_wait import wait_for_structure


def _visualization_atoms(atoms: Any) -> Atoms | None:
    """Return a plain ASE Atoms snapshot, without SPR-KKR runtime state."""
    if atoms is None:
        return None
    return Atoms(
        numbers=atoms.get_atomic_numbers(),
        positions=atoms.get_positions(),
        cell=atoms.get_cell(),
        pbc=atoms.get_pbc(),
    )


def visualize_structure(
    controller: WorkspaceController,
    settings: ApplicationSettings,
    parent: QWidget,
) -> bool:
    """Open a snapshot of the current structure in the configured ASE viewer."""
    snapshot = wait_for_structure(
        parent,
        partial(
            controller.read_structure,
            _visualization_atoms,
            reason="reading the structure for visualization",
        ),
    )
    if isinstance(snapshot, Busy):
        return False
    _generation, atoms = snapshot
    if atoms is None:
        QMessageBox.information(
            parent,
            "No Structure",
            "Load or create a structure first.",
        )
        return False

    try:
        ase_view(atoms, viewer=settings.viewer)
    except Exception as exc:  # noqa: BLE001 - external viewer boundary
        QMessageBox.critical(
            parent,
            "Visualization Error",
            (
                f"Could not open the structure with ASE viewer "
                f"'{settings.viewer}':\n{exc}"
            ),
        )
        return False
    return True
