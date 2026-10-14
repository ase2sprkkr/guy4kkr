"""Mutable workspace draft owned by ``WorkspaceController``."""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from ase2sprkkr.sprkkr.sprkkr_atoms import SPRKKRAtoms

from guy4ase.gui.application.materialized import Materialized
from guy4ase.gui.application.structure_provenance import (
    StructureProvenance,
    materialize_structure,
)
from guy4ase.physics.lattice import StructureKind, detect_structure_kind


@dataclass(frozen=True)
class Generation:
    """Revision of non-structural mutable workspace draft state.

    Structure concurrency is deliberately not represented by this counter;
    exact ``StructureProvenance`` identities are used for that purpose.
    """

    value: int = 0

    def next(self) -> "Generation":
        return Generation(self.value + 1)

    def next_major(self) -> "Generation":
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


class WorkspaceState:
    """Inputs prepared for the next calculation and facts derived from them.

    The physical structure is one ``Materialized`` owner. Its provenance is the
    authoritative identity of the logical structure state; its ``Atoms`` object is
    merely a mutable runtime realization which may be discarded and reconstructed.
    Potential path/version therefore never live as independent workspace state.

    ``atoms`` and ``potential_path`` are compatibility read views only. New code
    should reason about ``structure`` / ``structure_provenance``.
    """

    def __init__(
        self,
        *,
        structure: Materialized[Any, StructureProvenance] | None = None,
        atoms: Any | None = None,
        input_parameters: Any | None = None,
        directory: str | None = None,
        potential_path: str | None = None,
        structure_id: int | None = None,
        state_id: int | None = None,
        empty_spheres: EmptySpheresState | None = None,
        restarted: bool = False,
        generation: Generation = Generation(),
    ) -> None:
        if structure is not None and (atoms is not None or potential_path is not None):
            raise ValueError(
                "Pass either a materialized structure or legacy atoms/potential_path, not both."
            )
        if structure is None and atoms is not None:
            structure = materialize_structure(atoms, potential_path=potential_path)
        elif atoms is None and potential_path is not None:
            raise ValueError("A potential path without a structure is invalid.")

        self.structure = structure
        self.input_parameters = input_parameters
        self.directory = directory
        self.structure_id = structure_id
        self.state_id = state_id
        self.empty_spheres = empty_spheres
        self.restarted = restarted
        self.generation = generation

    @property
    def atoms(self) -> Any | None:
        return self.structure.get() if self.structure is not None else None

    @property
    def structure_provenance(self) -> StructureProvenance | None:
        return self.structure.provenance if self.structure is not None else None

    @property
    def potential_path(self) -> str | None:
        provenance = self.structure_provenance
        if provenance is None or provenance.potential_path is None:
            return None
        return str(provenance.potential_path)

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
            self.structure is not None
            and self.input_parameters is not None
            and bool(self.directory)
        )

    def scf_status(self) -> str | None:
        """Return the normalized SCFSTATUS of the active workspace potential."""
        if self.restarted:
            return "START" if self.structure is not None else None
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
        """Return convergence of the active workspace potential only."""
        if self.restarted:
            return False
        atoms = self.atoms
        if atoms is None:
            return False
        checker = getattr(atoms, "sprkkr_is_scf_converged", None)
        return bool(callable(checker) and checker())

    def has_vacuum_sites(self) -> bool:
        atoms = self.atoms
        if atoms is None:
            return False
        if isinstance(atoms, SPRKKRAtoms):
            return any(site.is_vacuum() for site in atoms.sites)
        return any(int(number) == 0 for number in getattr(atoms, "numbers", ()))
