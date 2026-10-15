"""Mutable workspace state owned by ``WorkspaceController``."""
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
    """Monotonic revision used to reject stale calculation-state edits."""

    value: int = 0

    def next(self) -> Generation:
        return Generation(self.value + 1)

    def next_major(self) -> Generation:
        """Advance the revision after a semantic workspace change."""
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
class CalculationState:
    """Calculation-specific data prepared for the next SPR-KKR task.

    ``atoms`` is the sole physical authority, including an attached SPR-KKR
    potential when one exists. ``potential_path`` and the state identifiers are
    provenance for that same physical state; they are not independent inputs.
    """

    atoms: Any | None = None
    input_parameters: Any | None = None
    potential_path: str | None = None
    structure_id: int | None = None
    state_id: int | None = None
    empty_spheres: EmptySpheresState | None = None
    restarted: bool = False

    @property
    def empty_spheres_added(self) -> int | None:
        if self.empty_spheres is None:
            return None
        return self.empty_spheres.count

    def structure_kind(self) -> StructureKind | None:
        return detect_structure_kind(self.atoms)

    def scf_status(self) -> str | None:
        """Return the effective SCFSTATUS of the active calculation state."""
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
        """Return convergence of the active calculation potential only."""
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


@dataclass
class WorkspaceContext:
    """Non-physical context captured by the next calculation launch.

    ``directory`` changes the concrete calculation request and therefore still
    participates in workspace generation checks. ``active_project_id`` is only
    launch attribution: selecting another project must not invalidate an
    in-progress structure or input-parameter edit.
    """

    directory: str | None = None
    active_project_id: str | None = None


@dataclass
class WorkspaceState:
    """Complete mutable workspace snapshot split by semantic responsibility.

    ``calculation`` answers what would be calculated. ``context`` carries the
    non-physical context of the next launch. Results deliberately do not live
    here. ``generation`` protects revision-sensitive edits; the controller
    decides which transitions advance it.
    """

    calculation: CalculationState = field(default_factory=CalculationState)
    context: WorkspaceContext = field(default_factory=WorkspaceContext)
    generation: Generation = Generation()
