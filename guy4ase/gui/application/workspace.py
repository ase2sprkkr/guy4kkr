"""Mutable workspace storage owned by ``WorkspaceController``."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ase2sprkkr.sprkkr.sprkkr_atoms import SPRKKRAtoms

from guy4ase.physics.lattice import StructureKind, detect_structure_kind


@dataclass
class WorkspaceState:
    """Mutable document storage owned by ``WorkspaceController``."""

    atoms: Any | None = None
    input_parameters: Any | None = None
    directory: str | None = None
    potential_path: str | None = None
    result: Any | None = None
    # Results available for browsing in the UI, newest first.
    result_history: tuple[Any, ...] = ()
    # None = not searched / provenance unknown; 0 = searched and none found;
    # positive = number of trailing empty-sphere sites added by Guy4ASE.
    empty_spheres_added: int | None = None
    restarted: bool = False

    def structure_kind(self) -> StructureKind | None:
        """Classify the current structure directly from ``atoms``."""
        return detect_structure_kind(self.atoms)

    def can_calculate(self) -> bool:
        """Return whether the workspace has all inputs required to run."""
        return (
            self.atoms is not None
            and self.input_parameters is not None
            and bool(self.directory)
        )

    def scf_status(self) -> str | None:
        """Return the normalized SCFSTATUS stored in the attached potential."""
        atoms = self.atoms
        if not isinstance(atoms, SPRKKRAtoms):
            return None
        if not atoms.has_potential():
            return None
        if self.restarted:
            return "START"
        status = atoms.potential.SCF_INFO.SCFSTATUS()
        if status is None:
            return None
        status = str(status).strip().upper()
        return status or None

    def is_scf_converged(self) -> bool:
        """Return effective SPR-KKR convergence derived from the current atoms."""
        if self.restarted:
            return False
        atoms = self.atoms
        if atoms is None:
            return False
        checker = getattr(atoms, "sprkkr_is_scf_converged", None)
        return bool(callable(checker) and checker())

    def has_vacuum_sites(self) -> bool:
        """Return whether the current structure contains pure vacuum sites."""
        atoms = self.atoms
        if atoms is None:
            return False
        if isinstance(atoms, SPRKKRAtoms):
            return any(site.is_vacuum() for site in atoms.sites)
        return any(int(number) == 0 for number in getattr(atoms, "numbers", ()))

    def empty_spheres_action(self) -> str | None:
        """Return ``add``/``recalculate`` for the explicit ES workflow.

        Imported or manually created vacuum sites are deliberately not treated
        as generated empty spheres. Recalculation is offered only while we
        still know exactly how many trailing sites Guy4ASE added.
        """
        if self.atoms is None:
            return None
        if self.empty_spheres_added is not None:
            return "recalculate" if self.empty_spheres_added > 0 else None
        if self.has_vacuum_sites():
            return None
        return "add"
