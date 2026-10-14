"""Capture mutable/backend result state into provenance values."""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import logging
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ase2sprkkr.input_parameters.input_parameters import InputParameters

from guy4ase.gui.application.file_version import FileVersion
from guy4ase.gui.application.potential_version import PotentialFileVersion
from guy4ase.gui.application.result_history import CapturedResult, CapturedStructure
from guy4ase.gui.application.structure_snapshot import StructureSnapshot
from guy4ase.physics.composition import structure_formula

logger = logging.getLogger(__name__)


def task_name(result: Any) -> str:
    """Capture a stable normalized task identity from a result."""
    try:
        return str(result.task_name).strip().lower()
    except (AttributeError, TypeError, ValueError):
        return type(result).__name__.lower()


def snapshot_input_parameters(parameters: Any | None) -> Any | None:
    """Detach mutable input provenance using explicit supported contracts."""
    if parameters is None:
        return None
    if isinstance(parameters, InputParameters):
        return parameters.copy(copy_values=True)
    if isinstance(parameters, Mapping):
        return deepcopy(dict(parameters))
    return deepcopy(parameters)


def capture_file_version(path: str | Path | None) -> FileVersion | None:
    """Capture one optional filesystem source for provenance identity."""
    return FileVersion.capture(path) if path is not None else None


def capture_result_files(result: Any) -> Mapping[str, FileVersion]:
    """Capture optional path-backed output values exposed by a backend result.

    Access to backend presentation metadata is deliberately best-effort: a
    broken optional output value must not prevent recording a completed result.
    Failures at that external boundary are logged instead of silently swallowed.
    """
    try:
        items = tuple(result.output_values.items())
    except AttributeError:
        return MappingProxyType({})
    except Exception:  # noqa: BLE001 - backend presentation metadata boundary
        logger.exception("Failed to enumerate result output files")
        return MappingProxyType({})

    result_files: dict[str, FileVersion] = {}
    for key, value in items:
        path_getter = getattr(value, "path", None)
        if not callable(path_getter):
            continue
        try:
            path = path_getter()
        except Exception:  # noqa: BLE001 - backend presentation metadata boundary
            logger.exception("Failed to resolve path for output value %r", key)
            continue
        if path:
            result_files[str(key)] = FileVersion.capture(path)
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
    path = (
        Path(potential_path).expanduser().resolve()
        if potential_path is not None
        else None
    )
    version = resolve_potential_version(path, potential_version)
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


def capture_result(
    result: Any,
    *,
    input_parameters: Any | None,
    output_path: str | Path | None,
    potential_path: str | Path | None,
    output_version: FileVersion | None = None,
) -> CapturedResult:
    """Capture result provenance that may inspect mutable objects or files."""
    resolved_output = (
        Path(output_path).expanduser().resolve() if output_path is not None else None
    )
    resolved_potential = (
        Path(potential_path).expanduser().resolve()
        if potential_path is not None
        else None
    )
    if output_version is not None:
        if resolved_output is None:
            raise ValueError("An output version requires its output path.")
        if output_version.path != resolved_output:
            raise ValueError("Captured output version does not match output path.")
    return CapturedResult(
        result=result,
        task_name=task_name(result),
        input_parameters=snapshot_input_parameters(input_parameters),
        result_files=capture_result_files(result),
        output_path=resolved_output,
        output_version=(
            output_version
            if output_version is not None
            else capture_file_version(resolved_output)
        ),
        potential_path=resolved_potential,
    )
