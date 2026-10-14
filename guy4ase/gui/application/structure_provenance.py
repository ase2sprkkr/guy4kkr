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
    potential_path: Path | None = None
    potential_version: PotentialFileVersion | None = None
    structure_snapshot: StructureSnapshot | None = None

    def __post_init__(self) -> None:
        version = self.potential_version
        path = self.potential_path
        snapshot = self.structure_snapshot
        if version is None:
            if path is not None:
                raise AssertionError("A potential path requires a captured version.")
            if snapshot is None:
                raise ValueError("A structure without a potential requires a snapshot.")
            return
        if path is None:
            raise AssertionError("A potential version requires its potential path.")
        if path != version.path:
            raise AssertionError("Potential version does not match potential path.")
        if version.available:
            if snapshot is not None:
                raise AssertionError("A usable potential must be the sole structure authority.")
        elif snapshot is None:
            raise ValueError("An unavailable potential requires a structure snapshot.")

    @classmethod
    def capture(
        cls,
        atoms: Any,
        *,
        potential_path: str | Path | None = None,
        potential_version: PotentialFileVersion | None = None,
    ) -> "StructureProvenance":
        path = (
            Path(potential_path).expanduser().resolve()
            if potential_path is not None
            else None
        )
        if potential_version is None:
            version = PotentialFileVersion.capture(path) if path is not None else None
        else:
            if path is None:
                raise AssertionError(
                    "A captured potential version requires its potential path."
                )
            if potential_version.path != path:
                raise AssertionError(
                    "Captured potential version does not match potential path."
                )
            version = potential_version
        snapshot = (
            StructureSnapshot.capture(atoms)
            if version is None or not version.available
            else None
        )
        return cls(
            formula=structure_formula(atoms) or type(atoms).__name__,
            potential_path=path,
            potential_version=version,
            structure_snapshot=snapshot,
        )

    def materialize(self) -> Any:
        """Reconstruct a fresh runtime structure representing this provenance."""
        version = self.potential_version
        if version is not None and version.available:
            # Stable POTFIL loading owns the external I/O race checks. Keep that
            # boundary lazy so result loading may itself construct provenance.
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
    potential_path: str | Path | None = None,
    potential_version: PotentialFileVersion | None = None,
) -> Materialized[Any, StructureProvenance]:
    """Capture provenance and bind it to the runtime structure in one operation."""
    provenance = StructureProvenance.capture(
        atoms,
        potential_path=potential_path,
        potential_version=potential_version,
    )
    return provenance.materialized(atoms)
