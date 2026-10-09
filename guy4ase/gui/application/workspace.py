"""The mutable document shared by the application's windows.

The workspace deliberately has no Qt dependency.  Windows render it and offer
operations on it, but neither owns a second copy of the calculation state.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from guy4ase.physics.lattice import StructureKind, detect_structure_kind
from ase2sprkkr.sprkkr.sprkkr_atoms import SPRKKRAtoms


@dataclass
class WorkspaceState:
    """Document data and semantic queries derived from the current ``atoms``.

    Values exposed here are borrowed references, not owned copies or read-only
    proxies. Application code may render them directly, but confirmed changes
    must be published through ``WorkspaceController`` document transitions.
    Derived values are evaluated on demand; they are not a second source of
    document state.
    """

    atoms: Any | None = None
    input_parameters: Any | None = None
    directory: str | None = None
    potential_path: str | None = None
    result: Any | None = None
    restarted: bool = False

    def structure_kind(self) -> StructureKind | None:
        """Classify the current structure directly from ``atoms``."""
        return detect_structure_kind(self.atoms)

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
