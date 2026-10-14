"""Capture mutable/backend result state into immutable provenance values."""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from guy4ase.gui.application.file_version import FileVersion
from guy4ase.gui.application.potential_version import PotentialFileVersion
from guy4ase.gui.application.structure_snapshot import StructureSnapshot
from guy4ase.physics.composition import structure_formula


@runtime_checkable
class _CopyValues(Protocol):
    def copy(self, *, copy_values: bool) -> Any: ...


@dataclass(frozen=True)
class CapturedStructure:
    """Filesystem-independent structure provenance ready for history mutation."""

    formula: str
    potential_path: str | None
    potential_version: PotentialFileVersion | None
    structure_snapshot: StructureSnapshot | None


@dataclass(frozen=True)
class CapturedResult:
    """Mutable/backend result data detached before history mutation begins."""

    result: Any
    task_name: str
    input_parameters: Any | None
    result_files: Mapping[str, FileVersion]
    output_path: Path | None
    output_version: FileVersion | None
    potential_path: Path | None


def task_name(result: Any) -> str:
    """Capture a stable normalized task identity from a result."""
    try:
        return str(result.task_name).strip().lower()
    except (AttributeError, TypeError, ValueError):
        return type(result).__name__.lower()


def snapshot_input_parameters(parameters: Any | None) -> Any | None:
    """Detach small mutable input provenance from its live source object.

    Mapping values are copied structurally. Objects implementing the explicit
    ``copy(copy_values=True)`` contract are copied through that contract and any
    failure propagates; ``TypeError`` is not used as feature detection.
    """
    if parameters is None:
        return None
    if isinstance(parameters, Mapping):
        return deepcopy(dict(parameters))
    if isinstance(parameters, _CopyValues):
        return parameters.copy(copy_values=True)
    return deepcopy(parameters)


def capture_file_version(path: str | Path | None) -> FileVersion | None:
    """Capture one optional filesystem source for provenance identity."""
    return FileVersion.capture(path) if path is not None else None


def capture_result_files(result: Any) -> Mapping[str, FileVersion]:
    """Capture path-backed output values without making recording fragile."""
    try:
        items = tuple(result.output_values.items())
    except Exception:  # noqa: BLE001 - optional result presentation metadata
        return MappingProxyType({})

    result_files: dict[str, FileVersion] = {}
    for key, value in items:
        path_getter = getattr(value, "path", None)
        if not callable(path_getter):
            continue
        try:
            path = path_getter()
        except Exception:  # noqa: BLE001 - optional result presentation metadata
            continue
        if not path:
            continue
        try:
            result_files[str(key)] = FileVersion.capture(path)
        except Exception:  # noqa: BLE001 - provenance enrichment is best effort
            continue
    return MappingProxyType(result_files)


def resolve_potential_version(
    path: str | Path | None,
    version: PotentialFileVersion | None = None,
) -> PotentialFileVersion | None:
    """Capture or validate the exact POTFIL version represented by ``path``."""
    if version is None:
        return PotentialFileVersion.capture(path) if path is not None else None
    if path is None:
        raise AssertionError("A captured potential version requires its potential path.")
    resolved_path = Path(path).expanduser().resolve()
    if version.path != resolved_path:
        raise AssertionError("Captured potential version does not match potential path.")
    return version


def capture_structure(
    atoms: Any,
    *,
    potential_path: str | Path | None,
    potential_version: PotentialFileVersion | None = None,
) -> CapturedStructure:
    """Capture all external structure state required by the provenance graph."""
    path = str(potential_path) if potential_path is not None else None
    version = resolve_potential_version(potential_path, potential_version)
    snapshot = (
        StructureSnapshot.capture(atoms)
        if version is None or not version.available
        else None
    )
    return CapturedStructure(
        formula=structure_formula(atoms) or type(atoms).__name__,
        potential_path=path,
        potential_version=version,
        structure_snapshot=snapshot,
    )


def capture_structure_snapshot(atoms: Any) -> StructureSnapshot:
    """Capture an output structure before entering history mutation."""
    return StructureSnapshot.capture(atoms)


def capture_result(
    result: Any,
    *,
    input_parameters: Any | None,
    output_path: str | Path | None,
    potential_path: str | Path | None,
    output_version: FileVersion | None = None,
) -> CapturedResult:
    """Capture result provenance that may inspect mutable objects or files."""
    resolved_output = Path(output_path) if output_path is not None else None
    resolved_potential = Path(potential_path) if potential_path is not None else None
    return CapturedResult(
        result=result,
        task_name=task_name(result),
        input_parameters=snapshot_input_parameters(input_parameters),
        result_files=capture_result_files(result),
        output_path=resolved_output,
        output_version=(
            output_version
            if resolved_output is not None
            else None
        ) if output_version is not None else capture_file_version(resolved_output),
        potential_path=resolved_potential,
    )
