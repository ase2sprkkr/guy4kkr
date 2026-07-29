from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from .models import (
    DownloadedStructure,
    SearchPage,
    StructureSearchQuery,
    StructureSummary,
)


@dataclass(frozen=True)
class ProviderCapabilities:
    formula_or_name: bool = True
    elements: bool = True
    space_group: bool = False
    max_sites: bool = True
    duplicate_filter: bool = False
    validity_filter: bool = False
    disorder_filter: bool = True


class StructureDatabaseProvider(ABC):
    id: str
    name: str
    capabilities: ProviderCapabilities
    max_page_limit: int = 100

    @abstractmethod
    def search(
        self,
        query: StructureSearchQuery,
        *,
        page_url: Optional[str] = None,
    ) -> SearchPage:
        """Search structures or follow a provider-issued pagination URL."""

    @abstractmethod
    def fetch(self, summary: StructureSummary) -> DownloadedStructure:
        """Download and convert one full structure."""
