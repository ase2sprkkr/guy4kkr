"""Stable provenance for result files that may later be overwritten."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any


FileFingerprint = tuple[int, int, int, int, int, int]


class ArtifactState(Enum):
    """Relationship between a historical artifact and its path on disk now."""

    CURRENT = "current"
    OVERWRITTEN = "overwritten"
    MISSING = "missing"
    UNAVAILABLE = "unavailable"


def _file_fingerprint(path: Path) -> FileFingerprint:
    info = path.stat()
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


@dataclass(frozen=True)
class ResultArtifactVersion:
    """Filesystem identity captured when a result enters the history."""

    path: Path
    fingerprint: FileFingerprint | None

    @classmethod
    def capture(cls, path: str | Path) -> ResultArtifactVersion:
        resolved = Path(path).expanduser().resolve()
        try:
            fingerprint = _file_fingerprint(resolved)
        except OSError:
            fingerprint = None
        return cls(path=resolved, fingerprint=fingerprint)

    def state(self) -> ArtifactState:
        try:
            current = _file_fingerprint(self.path)
        except FileNotFoundError:
            return ArtifactState.MISSING
        except OSError:
            return ArtifactState.UNAVAILABLE

        if self.fingerprint is None:
            return ArtifactState.OVERWRITTEN
        if current == self.fingerprint:
            return ArtifactState.CURRENT
        return ArtifactState.OVERWRITTEN


def capture_result_artifacts(result: Any) -> Mapping[str, ResultArtifactVersion]:
    """Capture path-backed output values without making result recording fragile.

    ASE2SPRKKR ``OutputFileOption`` values expose ``path()``. Guy4ASE keeps the
    dependency deliberately duck-typed so operation results and test doubles do
    not need to inherit from that concrete class. Broken optional presentation
    metadata must never prevent an otherwise valid result from entering history.
    """
    try:
        items = tuple(result.output_values.items())
    except Exception:  # noqa: BLE001 - optional result presentation metadata
        return MappingProxyType({})

    artifacts: dict[str, ResultArtifactVersion] = {}
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
            name = str(key)
            artifacts[name] = ResultArtifactVersion.capture(path)
        except Exception:  # noqa: BLE001 - provenance enrichment is best effort
            continue
    return MappingProxyType(artifacts)
