"""Interpret calculation results and result files without changing a workspace."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ase2sprkkr.outputs.task_result import TaskResult
from ase2sprkkr.potentials.potentials import Potential, PotentialFileChanged

from guy4ase.gui.application.file_version import FileVersion
from guy4ase.gui.application.materialized import Materialized
from guy4ase.gui.application.potential_version import PotentialFileVersion
from guy4ase.gui.application.structure_provenance import (
    StructureProvenance,
    materialize_structure,
)


class PotentialVersionChanged(RuntimeError):
    """The potential file no longer matches the version approved by the user."""


class OutputVersionChanged(RuntimeError):
    """The output file changed while the parsed result was being materialized."""


class LoadedResult:
    """A result whose external sources are already bound to exact versions.

    Successfully loaded structure state is represented by one ``Materialized``
    object. ``potential_path``/``potential_version`` remain available when POTFIL
    loading failed, so the UI can report the failed external reference without
    pretending that a valid structure provenance exists.
    """

    def __init__(
        self,
        *,
        result: TaskResult,
        output_path: Path | None,
        potential_path: Path | None,
        potential_error: Exception | None,
        directory: str | None,
        input_parameters: Any | None = None,
        input_parameters_error: Exception | None = None,
        persistent_ref: str | None = None,
        potential_version: PotentialFileVersion | None = None,
        output_version: FileVersion | None = None,
        structure: Materialized[Any, StructureProvenance] | None = None,
        atoms: Any | None = None,
    ) -> None:
        if structure is not None and atoms is not None:
            raise ValueError("Pass either structure or atoms, not both.")
        if atoms is not None:
            if potential_path is not None or potential_version is not None:
                raise ValueError(
                    "Raw atoms cannot be associated with POTFIL provenance. "
                    "Pass a structure materialized by the stable potential loader."
                )
            structure = materialize_structure(atoms)
        if structure is not None:
            provenance = structure.provenance
            if potential_path is None:
                potential_path = provenance.potential_path
            if potential_version is None:
                potential_version = provenance.potential_version
            if provenance.potential_path != potential_path:
                raise ValueError("Loaded structure does not match the potential path.")
            if provenance.potential_version != potential_version:
                raise ValueError("Loaded structure does not match the potential version.")
        if output_version is not None and output_path != output_version.path:
            raise ValueError("Loaded result does not match the captured output version.")

        self.result = result
        self.output_path = output_path
        self.output_version = output_version
        self.potential_path = potential_path
        self.potential_version = potential_version
        self.structure = structure
        self.potential_error = potential_error
        self.directory = directory
        self.input_parameters = input_parameters
        self.input_parameters_error = input_parameters_error
        self.persistent_ref = persistent_ref

    @property
    def atoms(self) -> Any | None:
        return self.structure.get() if self.structure is not None else None


def load_potential_atoms(file_path: str | Path) -> Any:
    """Load one stable POT file and return the atoms owned by that potential."""
    path = Path(file_path).resolve()
    potential = Potential.from_file(str(path), check_file_unchanged=True)
    atoms = potential.atoms
    if atoms is None:
        raise ValueError(f"Potential file contains no structure: {path}")
    return atoms


def require_potential_version_current(version: PotentialFileVersion) -> None:
    current = version.current()
    if not current.available or current != version:
        raise PotentialVersionChanged(
            f"Potential file changed after it was presented: {version.path}"
        )


def load_potential_version(version: PotentialFileVersion) -> Any:
    """Load exactly ``version`` of a POTFIL, rejecting pre/read/post races."""
    require_potential_version_current(version)
    try:
        atoms = load_potential_atoms(version.path)
    except PotentialFileChanged as exc:
        raise PotentialVersionChanged(
            f"Potential file changed while it was being read: {version.path}"
        ) from exc

    after = version.current()
    if not after.available or after != version:
        raise PotentialVersionChanged(
            f"Potential file changed while it was being read: {version.path}"
        )
    return atoms


def load_potential_materialized(
    file_path: str | Path,
) -> Materialized[Any, StructureProvenance]:
    """Load POTFIL and its exact structure provenance as one stable operation."""
    path = Path(file_path).resolve()
    version = PotentialFileVersion.capture(path)
    if not version.available:
        raise OSError(f"Potential file cannot be inspected: {path}")
    atoms = load_potential_version(version)
    return materialize_structure(atoms, potential_version=version)


def load_result_file(file_path: str | Path) -> LoadedResult:
    """Parse one exact version of an external result file."""
    path = Path(file_path).resolve()
    version = FileVersion.capture(path)
    if not version.available:
        raise OSError(f"Output file cannot be inspected: {path}")
    result = TaskResult.from_file(path)
    current = version.current()
    if not current.available or current != version:
        raise OutputVersionChanged(f"Output file changed while it was read: {path}")
    return load_result(
        result,
        fallback_directory=path.parent,
        output_fallback=path,
        output_version=version,
    )


def load_result(
    result: TaskResult,
    *,
    fallback_directory: str | Path | None,
    output_fallback: str | Path | None = None,
    persistent_ref: str | None = None,
    output_version: FileVersion | None = None,
) -> LoadedResult:
    """Resolve result files for an already constructed calculation result."""
    output, potential = _result_files(result, fallback_directory)
    if output is None and output_fallback is not None:
        output = Path(output_fallback).resolve()
    if output_version is not None:
        if output is None:
            output = output_version.path
        elif output != output_version.path:
            raise ValueError(
                "Parsed result reports an output path different from the exact file version that was read."
            )
    elif output is not None:
        output_version = FileVersion.capture(output)

    structure, potential_version, potential_error = _load_potential(potential)
    input_parameters, input_parameters_error = _load_input_parameters(result)
    directory = str(output.parent.resolve()) if output is not None else None
    return LoadedResult(
        result=result,
        output_path=output,
        output_version=output_version,
        potential_path=potential,
        structure=structure,
        potential_error=potential_error,
        directory=directory,
        input_parameters=input_parameters,
        input_parameters_error=input_parameters_error,
        persistent_ref=persistent_ref,
        potential_version=potential_version,
    )


def _load_input_parameters(result: Any) -> tuple[Any | None, Exception | None]:
    try:
        return getattr(result, "input_parameters", None), None
    except Exception as exc:  # noqa: BLE001 - parser failures are data
        return None, exc


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


def _result_files(
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
            potential = None
    potential = _resolve_path(potential, result, fallback_directory)
    return output, potential


def _load_potential(
    potential: Path | None,
) -> tuple[
    Materialized[Any, StructureProvenance] | None,
    PotentialFileVersion | None,
    Exception | None,
]:
    if potential is None:
        return None, None, None
    if not potential.exists():
        return (
            None,
            None,
            FileNotFoundError(f"Referenced potential file does not exist: {potential}"),
        )
    if not potential.is_file():
        return (
            None,
            None,
            IsADirectoryError(f"Referenced potential is not a file: {potential}"),
        )

    version = PotentialFileVersion.capture(potential)
    if not version.available:
        return (
            None,
            version,
            OSError(f"Referenced potential file cannot be inspected: {potential}"),
        )
    try:
        atoms = load_potential_version(version)
        return (
            materialize_structure(atoms, potential_version=version),
            version,
            None,
        )
    except Exception as exc:  # noqa: BLE001 - parser/filesystem failures are data
        return None, version, exc
