"""Immutable identity and reconstruction data for one physical structure state."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from guy4ase.gui.application.materialized import Materialized
from guy4ase.gui.application.potential_version import PotentialFileVersion
from guy4ase.gui.application.structure_snapshot import StructureSnapshot
from guy4ase.physics.composition import structure_formula


@dataclass(frozen=True)
class StructureProvenance:
    """Identity and reconstruction recipe for one exact physical structure state."""

    formula: str
    identity: UUID = field(default_factory=uuid4)
    potential_version: PotentialFileVersion | None = None
    structure_snapshot: StructureSnapshot | None = None

    def __post_init__(self) -> None:
        version = self.potential_version
        snapshot = self.structure_snapshot
        if version is None:
            if snapshot is None:
                raise ValueError("A structure without a potential requires a snapshot.")
            return
        if version.available:
            if snapshot is not None:
                raise AssertionError("A usable potential must be the sole structure authority.")
        elif snapshot is None:
            raise ValueError("An unavailable potential requires a structure snapshot.")

    @property
    def potential_path(self) -> Path | None:
        """Return the path carried by the exact captured POTFIL version."""
        version = self.potential_version
        return version.path if version is not None else None

    @classmethod
    def capture(
        cls,
        atoms: Any,
        *,
        potential_version: PotentialFileVersion | None = None,
    ) -> "StructureProvenance":
        """Capture one logical structure state.

        Raw ``Atoms`` never discover a POTFIL by path. POT-backed provenance must
        be supplied as an already captured exact ``PotentialFileVersion`` by the
        stable I/O boundary that produced ``atoms``.
        """
        snapshot = (
            StructureSnapshot.capture(atoms)
            if potential_version is None or not potential_version.available
            else None
        )
        return cls(
            formula=structure_formula(atoms) or type(atoms).__name__,
            potential_version=potential_version,
            structure_snapshot=snapshot,
        )

    def materialize(self) -> Any:
        """Reconstruct a fresh runtime structure representing this provenance."""
        version = self.potential_version
        if version is not None and version.available:
            from guy4ase.gui.application.result_loading import load_potential_version

            return load_potential_version(version)
        if self.structure_snapshot is not None:
            return self.structure_snapshot.to_atoms()
        raise ValueError("The structure provenance is no longer materializable.")

    def materialized(
        self,
        atoms: Any | None = None,
    ) -> Materialized[Any, "StructureProvenance"]:
        return Materialized(
            self,
            materializer=StructureProvenance.materialize,
            value=atoms,
        )


def materialize_structure(
    atoms: Any,
    *,
    potential_version: PotentialFileVersion | None = None,
) -> Materialized[Any, StructureProvenance]:
    """Bind runtime structure to already-known provenance in one operation."""
    provenance = StructureProvenance.capture(
        atoms,
        potential_version=potential_version,
    )
    return provenance.materialized(atoms)
