from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class StructureSearchQuery:
    text: str = ""
    elements: tuple[str, ...] = ()
    exact_elements: bool = True
    space_group: Optional[int] = None
    max_sites: Optional[int] = None
    hide_duplicates: bool = True
    hide_invalid: bool = True
    ordered_only: bool = False
    page_limit: int = 50


@dataclass(frozen=True)
class StructureSummary:
    provider_id: str
    entry_id: str
    formula: str
    name: str = ""
    space_group: str = ""
    space_group_number: Optional[int] = None
    site_count: Optional[int] = None
    method: str = ""
    year: Optional[int] = None
    status: str = ""
    duplicate_of: Optional[str] = None
    optimal_entry: Optional[str] = None
    structure_features: tuple[str, ...] = ()
    doi: str = ""
    raw_attributes: dict[str, Any] = field(default_factory=dict, compare=False)

    @property
    def is_disordered(self) -> bool:
        return "disorder" in self.structure_features

    @property
    def warnings(self) -> tuple[str, ...]:
        warnings = []
        if self.is_disordered:
            warnings.append("Disordered structure")
        if self.duplicate_of:
            warnings.append(f"Duplicate of {self.duplicate_of}")
        if self.optimal_entry and self.optimal_entry != self.entry_id:
            warnings.append(f"Recommended COD entry: {self.optimal_entry}")
        if self.status:
            warnings.append(f"COD status: {self.status}")
        return tuple(warnings)


@dataclass(frozen=True)
class SearchPage:
    results: tuple[StructureSummary, ...]
    next_url: Optional[str] = None
    previous_url: Optional[str] = None
    total: Optional[int] = None


@dataclass(frozen=True)
class StructureProvenance:
    provider_id: str
    provider_name: str
    entry_id: str
    entry_url: str
    retrieved_at: str
    license_name: str
    license_url: str
    experimental: bool
    doi: str = ""
    method: str = ""
    temperature_kelvin: Optional[float] = None
    pressure_kpa: Optional[float] = None
    warnings: tuple[str, ...] = ()
    provider_metadata: dict[str, Any] = field(
        default_factory=dict, compare=False
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "entry_id": self.entry_id,
            "entry_url": self.entry_url,
            "retrieved_at": self.retrieved_at,
            "license": self.license_name,
            "license_url": self.license_url,
            "experimental": self.experimental,
            "doi": self.doi,
            "method": self.method,
            "temperature_kelvin": self.temperature_kelvin,
            "pressure_kpa": self.pressure_kpa,
            "warnings": list(self.warnings),
            "provider_metadata": dict(self.provider_metadata),
        }


@dataclass(frozen=True)
class DownloadedStructure:
    atoms: Any
    summary: StructureSummary
    provenance: StructureProvenance
    warnings: tuple[str, ...] = ()
