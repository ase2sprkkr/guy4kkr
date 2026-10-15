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
    """Monotonic revision used to reject stale calculation-draft edits."""

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
class CalculationState:
    """The calculation-specific state prepared for the next SPR-KKR task.

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


@dataclass
class WorkspaceContext:
    """Non-physical context in which the prepared calculation will be launched.

    ``directory`` controls execution/output placement. ``active_project_id`` is
    launch attribution only: changing it must not invalidate an in-progress
    structure or input-parameter edit.
    """

    directory: str | None = None
    active_project_id: str | None = None


class WorkspaceState:
    """Complete mutable workspace snapshot, split by semantic responsibility.

    ``calculation`` answers *what would be calculated*. ``context`` answers
    *where/how the next launch belongs*. Results deliberately do not live here.
    ``generation`` protects revision-sensitive calculation-edit workflows; a
    project-selection-only change does not advance it.

    The component keyword arguments remain a compact construction API for tests
    and composition roots. Runtime code should mutate the nested state only
    through ``WorkspaceController``.
    """

    def __init__(
        self,
        *,
        calculation: CalculationState | None = None,
        context: WorkspaceContext | None = None,
        atoms: Any | None = None,
        input_parameters: Any | None = None,
        directory: str | None = None,
        potential_path: str | None = None,
        structure_id: int | None = None,
        state_id: int | None = None,
        empty_spheres: EmptySpheresState | None = None,
        restarted: bool = False,
        active_project_id: str | None = None,
        generation: Generation = Generation(),
    ) -> None:
        if calculation is not None and any(
            value is not None
            for value in (
                atoms,
                input_parameters,
                potential_path,
                structure_id,
                state_id,
                empty_spheres,
            )
        ):
            raise TypeError(
                "Pass either calculation= or calculation component arguments, not both."
            )
        if calculation is not None and restarted:
            raise TypeError(
                "Pass restarted through CalculationState when calculation= is supplied."
            )
        if context is not None and (directory is not None or active_project_id is not None):
            raise TypeError(
                "Pass either context= or context component arguments, not both."
            )

        self.calculation = calculation or CalculationState(
            atoms=atoms,
            input_parameters=input_parameters,
            potential_path=potential_path,
            structure_id=structure_id,
            state_id=state_id,
            empty_spheres=empty_spheres,
            restarted=restarted,
        )
        self.context = context or WorkspaceContext(
            directory=directory,
            active_project_id=active_project_id,
        )
        self.generation = generation

    # Explicit aggregate conveniences keep callers concise without obscuring
    # ownership in the stored data model.
    @property
    def atoms(self) -> Any | None:
        return self.calculation.atoms

    @atoms.setter
    def atoms(self, value: Any | None) -> None:
        self.calculation.atoms = value

    @property
    def input_parameters(self) -> Any | None:
        return self.calculation.input_parameters

    @input_parameters.setter
    def input_parameters(self, value: Any | None) -> None:
        self.calculation.input_parameters = value

    @property
    def directory(self) -> str | None:
        return self.context.directory

    @directory.setter
    def directory(self, value: str | None) -> None:
        self.context.directory = value

    @property
    def potential_path(self) -> str | None:
        return self.calculation.potential_path

    @potential_path.setter
    def potential_path(self, value: str | None) -> None:
        self.calculation.potential_path = value

    @property
    def structure_id(self) -> int | None:
        return self.calculation.structure_id

    @structure_id.setter
    def structure_id(self, value: int | None) -> None:
        self.calculation.structure_id = value

    @property
    def state_id(self) -> int | None:
        return self.calculation.state_id

    @state_id.setter
    def state_id(self, value: int | None) -> None:
        self.calculation.state_id = value

    @property
    def empty_spheres(self) -> EmptySpheresState | None:
        return self.calculation.empty_spheres

    @empty_spheres.setter
    def empty_spheres(self, value: EmptySpheresState | None) -> None:
        self.calculation.empty_spheres = value

    @property
    def restarted(self) -> bool:
        return self.calculation.restarted

    @restarted.setter
    def restarted(self, value: bool) -> None:
        self.calculation.restarted = bool(value)

    @property
    def empty_spheres_added(self) -> int | None:
        return self.calculation.empty_spheres_added

    def structure_kind(self) -> StructureKind | None:
        return self.calculation.structure_kind()

    def is_calculation_input_complete(self) -> bool:
        """Return whether all generic inputs required to launch a task exist."""
        return (
            self.calculation.atoms is not None
            and self.calculation.input_parameters is not None
            and bool(self.context.directory)
        )

    def scf_status(self) -> str | None:
        return self.calculation.scf_status()

    def is_scf_converged(self) -> bool:
        return self.calculation.is_scf_converged()

    def has_vacuum_sites(self) -> bool:
        return self.calculation.has_vacuum_sites()
