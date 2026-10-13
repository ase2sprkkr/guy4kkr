"""Stable provenance for result files that may later be overwritten."""
from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from guy4ase.gui.application.file_version import FileState, FileVersion


ArtifactState = FileState
ResultArtifactVersion = FileVersion


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
