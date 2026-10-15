"""Mutable workspace draft owned by ``WorkspaceController``."""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from ase2sprkkr.sprkkr.sprkkr_atoms import SPRKKRAtoms

from guy4ase.physics.lattice import StructureKind, detect_structure_kind


@dataclass(frozen=True)
class Generation:
    """Monotonic revision used by ``WorkspaceController`` for stale callbacks."""

    value: int = 0

    def next(self) -> Generation:
        return Generation(self.value + 1)


@dataclass(frozen=True)
class EmptySpheresState:
    """Provenance of the latest explicit empty-sphere search."""

    count: int
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        count = int(self.count)
        if count < 0:
            raise ValueError("Empty-sphere count cannot be negative.")
        object.__setattr__(self, "count", count)
        object.__setattr__(
            self,
            "parameters",
            MappingProxyType(deepcopy(dict(self.parameters))),
        )


@dataclass
class WorkspaceState:
    """Application draft from which the next calculation will be launched.

    ``atoms`` is the sole physical authority, including an attached SPR-KKR
    potential when present. ``potential_path`` is provenance/artifact metadata
    only. Result-tree identifiers and stale-callback generations deliberately do
    not live here; they are bookkeeping owned by ``WorkspaceController``.
    """

    atoms: Any | None = None
    input_parameters: Any | None = None
    directory: str | None = None
    potential_path: str | None = None
    empty_spheres: EmptySpheresState | None = None
    restarted: bool = False
    active_project_id: str | None = None

    @property
    def empty_spheres_added(self) -> int | None:
        if self.empty_spheres is None:
            return None
        return self.empty_spheres.count

    def structure_kind(self) -> StructureKind | None:
        return detect_structure_kind(self.atoms)

    def is_calculation_input_complete(self) -> bool:
        """Return whether all generic inputs required to launch a task exist."""
        return (
            self.atoms is not None
            and self.input_parameters is not None
            and bool(self.directory)
        )

    def scf_status(self) -> str | None:
        """Return the effective SCFSTATUS of the active workspace state."""
        atoms = self.atoms
        if atoms is None:
            return None
        if self.restarted:
            return "START"
        if not isinstance(atoms, SPRKKRAtoms):
            return None
        if not atoms.has_potential():
            return None
        status = atoms.potential.SCF_INFO.SCFSTATUS()
        if status is None:
            return None
        status = str(status).strip().upper()
        return status or None

    def is_scf_converged(self) -> bool:
        """Return convergence of the active workspace potential only."""
        if self.restarted:
            return False
        atoms = self.atoms
        if atoms is None:
            return False
        checker = getattr(atoms, "sprkkr_is_scf_converged", None)
        return bool(callable(checker) and checker())

    def has_vacuum_sites(self) -> bool:
        if self.atoms is None:
            return False
        if isinstance(self.atoms, SPRKKRAtoms):
            return any(site.is_vacuum() for site in self.atoms.sites)
        return any(
            int(number) == 0 for number in getattr(self.atoms, "numbers", ())
        )
