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
    """Monotonic revision of the mutable workspace draft."""

    value: int = 0

    def next(self) -> Generation:
        return Generation(self.value + 1)

    def next_major(self) -> Generation:
        """Advance the draft revision after a semantic workspace change."""
        return self.next()


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
    """Inputs prepared for the next calculation.

    Results deliberately do not live here. ``structure_id`` identifies the
    user-visible structure and ``state_id`` the exact structure/potential input
    from which the next task will start.
    """

    atoms: Any | None = None
    input_parameters: Any | None = None
    directory: str | None = None
    potential_path: str | None = None
    structure_id: int | None = None
    state_id: int | None = None
    empty_spheres: EmptySpheresState | None = None
    restarted: bool = False
    generation: Generation = Generation()

    @property
    def empty_spheres_added(self) -> int | None:
        if self.empty_spheres is None:
            return None
        return self.empty_spheres.count

    def structure_kind(self) -> StructureKind | None:
        return detect_structure_kind(self.atoms)

    def can_calculate(self) -> bool:
        return (
            self.atoms is not None
            and self.input_parameters is not None
            and bool(self.directory)
        )

    def scf_status(self) -> str | None:
        """Return the normalized SCFSTATUS of the active workspace potential."""
        atoms = self.atoms
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
        """Return whether the active potential is ready as a converged state."""
        if self.scf_status() == "START":
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

    def empty_spheres_action(self) -> str | None:
        if self.atoms is None:
            return None
        if self.empty_spheres is not None:
            return "recalculate"
        if self.has_vacuum_sites():
            return None
        return "add"
