"""Lightweight results produced by GUI-side operations."""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, ClassVar


@dataclass(frozen=True)
class EmptySpheresCount:
    """Summary value for an explicit empty-sphere search."""

    count: int

    name: ClassVar[str] = "empty_spheres"
    display_name: ClassVar[str] = "Empty spheres found"
    info: ClassVar[str] = "Number of empty spheres found by the empty-sphere search."
    show_in_summary: ClassVar[bool] = True

    def value_label(self) -> str:
        return str(self.count)

    @staticmethod
    def actions() -> tuple[str, ...]:
        return ()


@dataclass(frozen=True)
class EmptySpheresResult:
    """Result of one explicit empty-sphere search/recalculation."""

    found: int
    parameters: Mapping[str, Any] = field(
        default_factory=dict, compare=False, repr=False
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "parameters",
            MappingProxyType(deepcopy(dict(self.parameters))),
        )

    @property
    def output_values(self) -> dict[str, EmptySpheresCount]:
        return {"empty_spheres": EmptySpheresCount(self.found)}
