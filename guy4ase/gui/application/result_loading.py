"""Interpret calculation results and artifacts without changing a workspace."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ase2sprkkr.outputs.task_result import TaskResult
from ase2sprkkr.potentials.potentials import Potential


@dataclass(frozen=True)
class LoadedResult:
    """A result whose filesystem references have already been interpreted.

    ``output_path`` is provenance and may name a file that no longer exists.
    A missing referenced potential is different: reconstructing atoms depends
    on it, so ``potential_error`` contains ``FileNotFoundError``.
    """

    result: TaskResult
    output_path: Path | None
    potential_path: Path | None
    atoms: Any | None
    potential_error: Exception | None
    directory: str | None


def load_result_file(file_path: str | Path) -> LoadedResult:
    """Parse an external result and all usable referenced artifacts."""
    path = Path(file_path).resolve()
    result = TaskResult.from_file(path)
    return load_result(
        result,
        fallback_directory=path.parent,
        output_fallback=path,
    )


def load_result(
    result: TaskResult,
    *,
    fallback_directory: str | Path | None,
    output_fallback: str | Path | None = None,
) -> LoadedResult:
    """Resolve artifacts for an already constructed calculation result."""
    output, potential = _result_artifacts(result, fallback_directory)
    if output is None and output_fallback is not None:
        output = Path(output_fallback).resolve()
    atoms, potential_error = _load_potential(potential)
    directory = str(output.parent.resolve()) if output is not None else None
    return LoadedResult(
        result=result,
        output_path=output,
        potential_path=potential,
        atoms=atoms,
        potential_error=potential_error,
        directory=directory,
    )


def _registered_path(result: Any, key: str) -> Path | None:
    files = getattr(result, "files", None)
    if files is None or key not in files:
        return None
    value = result.path_to(key)
    return Path(value) if value else None


def _resolve_path(
    path: str | Path | None,
    result: Any,
    fallback_directory: str | Path | None,
) -> Path | None:
    if not path:
        return None
    resolved = Path(path)
    if not resolved.is_absolute():
        base = getattr(result, "directory", None) or fallback_directory
        if base:
            resolved = Path(base) / resolved
    return resolved.resolve()


def _result_artifacts(
    result: Any,
    fallback_directory: str | Path | None,
) -> tuple[Path | None, Path | None]:
    output = _registered_path(result, "output")
    if output is None:
        output = getattr(result, "output_file", None)
    output = _resolve_path(output, result, fallback_directory)

    potential = _registered_path(result, "converged")
    if potential is None:
        potential = _registered_path(result, "potential")
    if potential is None:
        try:
            potential = getattr(result, "potential_filename", None)
        except ValueError:
            # TaskResult uses ValueError for an unspecified POTFIL.
            potential = None
    potential = _resolve_path(potential, result, fallback_directory)
    return output, potential


def _load_potential(
    potential: Path | None,
) -> tuple[Any | None, Exception | None]:
    if potential is None:
        return None, None
    if not potential.exists():
        return None, FileNotFoundError(
            f"Referenced potential file does not exist: {potential}"
        )
    if not potential.is_file():
        return None, IsADirectoryError(
            f"Referenced potential is not a file: {potential}"
        )
    try:
        return Potential.from_file(str(potential.resolve())).atoms, None
    except Exception as exc:  # noqa: BLE001 - parser failures are data
        return None, exc
