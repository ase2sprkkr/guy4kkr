"""Resolve historical result artifacts against the current filesystem."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from guy4ase.gui.application.file_version import FileState, FileVersion
from guy4ase.gui.application.potential_version import PotentialFileVersion
from guy4ase.gui.application.result_history import ResultHistory, ResultRecord


@dataclass(frozen=True)
class ResolvedPotentialVersion:
    """Live filesystem relation of one recorded potential version."""

    recorded: PotentialFileVersion | None
    current: PotentialFileVersion | None

    @property
    def exact_available(self) -> bool:
        return bool(
            self.recorded is not None
            and self.current is not None
            and self.current.available
            and self.current == self.recorded
        )

    @property
    def changed(self) -> bool:
        return bool(
            self.recorded is not None
            and self.current is not None
            and self.current.available
            and self.current != self.recorded
        )


@dataclass(frozen=True)
class ResolvedResultValue:
    """Filesystem-resolved value used to build result presentation data."""

    value: Any
    warning: str | None = None
    disable_actions: bool = False
    replaced: bool = False
    unavailable: bool = False


def resolve_potential_version(
    recorded: PotentialFileVersion | None,
) -> ResolvedPotentialVersion:
    """Observe the live filesystem for one recorded POTFIL version."""
    current = (
        recorded.current()
        if recorded is not None and recorded.available
        else None
    )
    return ResolvedPotentialVersion(recorded=recorded, current=current)


def find_existing_external_result(
    history: ResultHistory,
    output_path: str | Path | None,
    *,
    persistent_ref: str | None = None,
) -> ResultRecord | None:
    """Resolve a previously imported source against its current file version."""
    if persistent_ref is not None:
        existing = history.result_for_persistent_ref(persistent_ref)
        if existing is not None:
            return existing

    if output_path is None:
        return None
    path = Path(output_path).expanduser().resolve()
    for record in history.results:
        version = record.output_version
        if version is None or version.path != path:
            continue
        if version.state() is FileState.CURRENT:
            return record
    return None


def current_value_for_result_file(
    history: ResultHistory,
    result_file: FileVersion,
) -> Any | None:
    """Return the known output value that owns the file currently at this path."""
    for record in history.results:
        for name, candidate in record.result_files.items():
            if candidate.path != result_file.path:
                continue
            if candidate.state() is not FileState.CURRENT:
                continue
            try:
                values = record.result.output_values
                for key, value in values.items():
                    if str(key) == name:
                        return value
            except Exception:  # noqa: BLE001 - backend presentation metadata boundary
                continue
    return None


def resolve_result_value(
    history: ResultHistory | None,
    record: ResultRecord | None,
    key: str,
    value: Any,
) -> ResolvedResultValue:
    """Resolve one captured output value without involving a Qt view."""
    result_file = record.result_files.get(key) if record is not None else None
    if result_file is None:
        return ResolvedResultValue(value)

    state = result_file.state()
    if state is FileState.OVERWRITTEN:
        current_value = (
            current_value_for_result_file(history, result_file)
            if history is not None
            else None
        )
        return ResolvedResultValue(
            current_value if current_value is not None else value,
            warning=(
                "The historical result file was overwritten. Showing the current "
                f"contents of {result_file.path.name}; these are not the original "
                "data from the selected calculation."
            ),
            replaced=True,
        )
    if state is FileState.MISSING:
        return ResolvedResultValue(
            value,
            warning=(
                "The historical result file no longer exists, so its original "
                "contents are unavailable."
            ),
            disable_actions=True,
            unavailable=True,
        )
    if state is FileState.UNAVAILABLE:
        return ResolvedResultValue(
            value,
            warning=(
                "The historical result file cannot currently be inspected, so "
                "its contents are unavailable."
            ),
            disable_actions=True,
            unavailable=True,
        )
    return ResolvedResultValue(value)
