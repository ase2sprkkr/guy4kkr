from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any, Callable, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen

import numpy as np
from ase import Atoms
from ase.data import atomic_numbers
from ase.formula import Formula

from .models import (
    DownloadedStructure,
    SearchPage,
    StructureProvenance,
    StructureSearchQuery,
    StructureSummary,
)
from .provider import ProviderCapabilities, StructureDatabaseProvider


class OnlineDatabaseError(RuntimeError):
    """A user-facing online database or response error."""


JsonTransport = Callable[[str], dict[str, Any]]


def _default_json_transport(url: str) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.api+json, application/json",
            "User-Agent": "Guy4ASE/0.1",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = exc.reason or f"HTTP {exc.code}"
        try:
            payload = json.load(exc)
            detail = payload.get("errors", [{}])[0].get("detail", detail)
        except Exception:
            pass
        raise OnlineDatabaseError(f"Database request failed: {detail}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise OnlineDatabaseError(f"Cannot reach the online database: {exc}") from exc
    except (ValueError, TypeError) as exc:
        raise OnlineDatabaseError("The database returned invalid JSON data.") from exc


def _escape_filter_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _as_optional_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_optional_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class CodOptimadeProvider(StructureDatabaseProvider):
    id = "cod"
    name = "Crystallography Open Database"
    base_url = "https://www.crystallography.net/cod/optimade/v1/"
    homepage = "https://www.crystallography.net/cod"
    max_page_limit = 10
    capabilities = ProviderCapabilities(
        space_group=True,
        max_sites=False,
        duplicate_filter=True,
        validity_filter=True,
        disorder_filter=False,
    )

    _summary_fields = (
        "chemical_formula_reduced",
        "chemical_formula_descriptive",
        "nsites",
        "structure_features",
        "_cod_chemname",
        "_cod_commonname",
        "_cod_mineral",
        "_cod_sg",
        "_cod_sgnumber",
        "_cod_method",
        "_cod_year",
        "_cod_status",
        "_cod_duplicateof",
        "_cod_optimal",
        "_cod_doi",
        "_cod_flags",
        "_cod_celltemp",
        "_cod_cellpressure",
    )
    _structure_fields = (
        "lattice_vectors",
        "cartesian_site_positions",
        "dimension_types",
        "species_at_sites",
        "species",
        "assemblies",
    )

    def __init__(self, transport: Optional[JsonTransport] = None):
        self._transport = transport or _default_json_transport

    def search(
        self,
        query: StructureSearchQuery,
        *,
        page_url: Optional[str] = None,
    ) -> SearchPage:
        url = page_url or self._search_url(query)
        payload = self._transport(url)
        return self._parse_page(payload, request_url=url)

    def fetch(self, summary: StructureSummary) -> DownloadedStructure:
        entry_id = quote(summary.entry_id, safe="")
        parameters = {
            "response_fields": ",".join(
                self._summary_fields + self._structure_fields
            )
        }
        url = (
            urljoin(self.base_url, f"structures/{entry_id}")
            + "?"
            + urlencode(parameters)
        )
        payload = self._transport(url)
        resource = payload.get("data")
        if not isinstance(resource, dict):
            raise OnlineDatabaseError("The database response contains no structure.")
        return self._downloaded_structure(resource, fallback_summary=summary)

    def _search_url(self, query: StructureSearchQuery) -> str:
        parameters = {
            "page_limit": max(
                1, min(int(query.page_limit), self.max_page_limit)
            ),
            "response_fields": ",".join(self._summary_fields),
        }
        filters = self._filters(query)
        if filters:
            parameters["filter"] = " AND ".join(f"({item})" for item in filters)
        return urljoin(self.base_url, "structures") + "?" + urlencode(parameters)

    def _filters(self, query: StructureSearchQuery) -> list[str]:
        filters = []
        text = query.text.strip()
        escaped_text = _escape_filter_string(text)
        if text:
            if re.fullmatch(r"\d{7}", text):
                filters.append(f'id="{escaped_text}"')
            elif re.fullmatch(
                r"(?:[A-Z][a-z]?(?:\d+(?:\.\d+)?)?)+",
                re.sub(r"\s+", "", text),
            ):
                formula = Formula(re.sub(r"\s+", "", text)).format("hill")
                escaped_formula = _escape_filter_string(formula)
                filters.append(f'chemical_formula_hill="{escaped_formula}"')
            else:
                filters.append(
                    "("
                    f'_cod_chemname CONTAINS "{escaped_text}" OR '
                    f'_cod_commonname CONTAINS "{escaped_text}" OR '
                    f'_cod_mineral CONTAINS "{escaped_text}"'
                    ")"
                )

        elements = tuple(dict.fromkeys(query.elements))
        if elements:
            quoted = ", ".join(f'"{_escape_filter_string(item)}"' for item in elements)
            filters.append(f"elements HAS ALL {quoted}")
            if query.exact_elements:
                filters.append(f"nelements={len(elements)}")

        if query.space_group is not None:
            filters.append(f"_cod_sgnumber={int(query.space_group)}")
        if query.max_sites is not None and self.capabilities.max_sites:
            filters.append(f"nsites<={int(query.max_sites)}")
        if query.hide_duplicates:
            filters.append("_cod_duplicateof IS UNKNOWN")
        if query.hide_invalid:
            filters.append(
                '(_cod_status IS UNKNOWN OR '
                '(_cod_status!="errors" AND _cod_status!="retracted"))'
            )
        if query.ordered_only and self.capabilities.disorder_filter:
            filters.append('NOT structure_features HAS "disorder"')
        return filters

    def _parse_page(self, payload: dict[str, Any], *, request_url: str) -> SearchPage:
        resources = payload.get("data")
        if not isinstance(resources, list):
            raise OnlineDatabaseError("The database returned an invalid result page.")
        results = tuple(self._summary(resource) for resource in resources)
        links = payload.get("links") or {}
        meta = payload.get("meta") or {}
        return SearchPage(
            results=results,
            next_url=self._page_link(links.get("next"), request_url),
            previous_url=self._page_link(links.get("prev"), request_url),
            total=_as_optional_int(
                meta.get("data_returned_available", meta.get("data_returned"))
            ),
        )

    @staticmethod
    def _page_link(value: Any, request_url: str) -> Optional[str]:
        if isinstance(value, dict):
            value = value.get("href")
        if not isinstance(value, str) or not value:
            return None
        return urljoin(request_url, value)

    def _summary(self, resource: dict[str, Any]) -> StructureSummary:
        attributes = resource.get("attributes")
        if not isinstance(attributes, dict):
            raise OnlineDatabaseError("A database result contains no attributes.")
        entry_id = str(resource.get("id", ""))
        if not entry_id:
            raise OnlineDatabaseError("A database result contains no identifier.")
        name = next(
            (
                str(attributes.get(field)).strip()
                for field in ("_cod_commonname", "_cod_chemname", "_cod_mineral")
                if attributes.get(field)
            ),
            "",
        )
        formula = (
            attributes.get("chemical_formula_reduced")
            or attributes.get("chemical_formula_descriptive")
            or ""
        )
        return StructureSummary(
            provider_id=self.id,
            entry_id=entry_id,
            formula=str(formula),
            name=name,
            space_group=str(attributes.get("_cod_sg") or ""),
            space_group_number=_as_optional_int(attributes.get("_cod_sgnumber")),
            site_count=_as_optional_int(attributes.get("nsites")),
            method=str(attributes.get("_cod_method") or ""),
            year=_as_optional_int(attributes.get("_cod_year")),
            status=str(attributes.get("_cod_status") or ""),
            duplicate_of=(
                str(attributes["_cod_duplicateof"])
                if attributes.get("_cod_duplicateof") is not None
                else None
            ),
            optimal_entry=(
                str(attributes["_cod_optimal"])
                if attributes.get("_cod_optimal") is not None
                else None
            ),
            structure_features=tuple(attributes.get("structure_features") or ()),
            doi=str(attributes.get("_cod_doi") or ""),
            raw_attributes=dict(attributes),
        )

    def _downloaded_structure(
        self,
        resource: dict[str, Any],
        *,
        fallback_summary: StructureSummary,
    ) -> DownloadedStructure:
        attributes = resource.get("attributes")
        if not isinstance(attributes, dict):
            raise OnlineDatabaseError("The selected database entry has no attributes.")
        summary = self._summary(resource)
        if not summary.formula:
            summary = fallback_summary
        atoms, conversion_warnings = self._atoms_from_attributes(attributes)
        warnings = tuple(dict.fromkeys(summary.warnings + conversion_warnings))
        provenance = StructureProvenance(
            provider_id=self.id,
            provider_name=self.name,
            entry_id=summary.entry_id,
            entry_url=f"{self.homepage}/{summary.entry_id}.html",
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            license_name="CC0-1.0",
            license_url="https://creativecommons.org/publicdomain/zero/1.0/",
            experimental=True,
            doi=summary.doi,
            method=summary.method,
            temperature_kelvin=_as_optional_float(attributes.get("_cod_celltemp")),
            pressure_kpa=_as_optional_float(attributes.get("_cod_cellpressure")),
            warnings=warnings,
            provider_metadata={
                "structure_features": list(summary.structure_features),
                "optimade_assemblies": attributes.get("assemblies"),
            },
        )
        atoms.info["online_database"] = provenance.as_dict()
        return DownloadedStructure(
            atoms=atoms,
            summary=summary,
            provenance=provenance,
            warnings=warnings,
        )

    @staticmethod
    def _atoms_from_attributes(
        attributes: dict[str, Any],
    ) -> tuple[Atoms, tuple[str, ...]]:
        try:
            lattice = np.asarray(
                attributes.get("lattice_vectors"), dtype=float
            )
            positions = np.asarray(
                attributes.get("cartesian_site_positions"), dtype=float
            )
        except (TypeError, ValueError) as exc:
            raise OnlineDatabaseError(
                "The selected structure has invalid coordinates."
            ) from exc
        if lattice.shape != (3, 3) or not np.isfinite(lattice).all():
            raise OnlineDatabaseError("The selected structure has no valid unit cell.")
        if (
            positions.ndim != 2
            or positions.shape[1:] != (3,)
            or not np.isfinite(positions).all()
        ):
            raise OnlineDatabaseError(
                "The selected structure has no valid atomic positions."
            )
        declared_site_count = _as_optional_int(attributes.get("nsites"))
        if (
            declared_site_count is not None
            and declared_site_count != len(positions)
        ):
            raise OnlineDatabaseError(
                "The selected structure has an inconsistent site count."
            )

        features = set(attributes.get("structure_features") or ())
        unsupported_features = features.intersection(
            {"implicit_atoms", "site_attachments"}
        )
        if unsupported_features:
            names = ", ".join(sorted(unsupported_features))
            raise OnlineDatabaseError(
                "The selected structure uses unsupported OPTIMADE features: "
                f"{names}."
            )

        species_at_sites = attributes.get("species_at_sites")
        if not isinstance(species_at_sites, list) or len(species_at_sites) != len(
            positions
        ):
            raise OnlineDatabaseError(
                "The selected structure has inconsistent site information."
            )
        species_definitions = {
            item.get("name"): item
            for item in (attributes.get("species") or ())
            if isinstance(item, dict) and item.get("name")
        }
        assemblies = attributes.get("assemblies")
        site_probabilities = CodOptimadeProvider._site_probabilities(
            assemblies, len(positions)
        )

        symbols = []
        occupancies: dict[str, dict[str, float]] = {}
        labels = []
        warnings = []
        for index, species_name in enumerate(species_at_sites):
            definition = species_definitions.get(species_name)
            if definition is None:
                raise OnlineDatabaseError(
                    "The selected structure refers to an undefined species."
                )
            if definition.get("attached") or definition.get("nattached"):
                raise OnlineDatabaseError(
                    "The selected structure contains attached atoms without "
                    "explicit positions."
                )
            occupation = CodOptimadeProvider._occupation(definition)
            probability = site_probabilities[index]
            if probability < 1.0:
                occupation = {
                    symbol: concentration * probability
                    for symbol, concentration in occupation.items()
                }
                occupation["Vc"] = (
                    occupation.get("Vc", 0.0) + 1.0 - probability
                )
                occupation = CodOptimadeProvider._normalize_occupation(
                    occupation
                )
            occupancies[str(index)] = occupation
            real_species = [
                (symbol, concentration)
                for symbol, concentration in occupation.items()
                if symbol != "Vc"
            ]
            symbols.append(
                max(real_species, key=lambda item: item[1])[0]
                if real_species
                else "X"
            )
            labels.append(str(species_name or f"site-{index + 1}"))

        if assemblies:
            warnings.append(
                "Correlated disorder assemblies are preserved in provenance, "
                "but SPR-KKR represents their site concentrations independently."
            )

        pbc = attributes.get("dimension_types") or [1, 1, 1]
        if (
            not isinstance(pbc, list)
            or len(pbc) != 3
            or any(value not in (0, 1) for value in pbc)
        ):
            raise OnlineDatabaseError(
                "The selected structure has invalid periodic dimensions."
            )
        atoms = Atoms(symbols=symbols, positions=positions, cell=lattice, pbc=pbc)
        atoms.set_array("spacegroup_kinds", np.arange(len(atoms), dtype=int))
        atoms.set_array("labels", np.asarray(labels, dtype=object))
        atoms.info["occupancy"] = occupancies
        if assemblies:
            atoms.info["optimade_assemblies"] = assemblies
        return atoms, tuple(warnings)

    @staticmethod
    def _site_probabilities(
        assemblies: Any, site_count: int
    ) -> list[float]:
        probabilities = [1.0] * site_count
        if not assemblies:
            return probabilities
        if not isinstance(assemblies, list):
            raise OnlineDatabaseError(
                "The selected structure has invalid disorder assemblies."
            )

        assigned_sites = set()
        for assembly in assemblies:
            if not isinstance(assembly, dict):
                raise OnlineDatabaseError(
                    "The selected structure has invalid disorder assemblies."
                )
            groups = assembly.get("sites_in_groups")
            group_probabilities = assembly.get("group_probabilities")
            if (
                not isinstance(groups, list)
                or not isinstance(group_probabilities, list)
                or len(groups) != len(group_probabilities)
            ):
                raise OnlineDatabaseError(
                    "The selected structure has invalid disorder assemblies."
                )
            for group, probability in zip(groups, group_probabilities):
                try:
                    value = float(probability)
                except (TypeError, ValueError) as exc:
                    raise OnlineDatabaseError(
                        "The selected structure has an invalid assembly "
                        "probability."
                    ) from exc
                if not 0.0 <= value <= 1.0 or not isinstance(group, list):
                    raise OnlineDatabaseError(
                        "The selected structure has an invalid disorder "
                        "assembly."
                    )
                for site in group:
                    if (
                        not isinstance(site, int)
                        or isinstance(site, bool)
                        or not 0 <= site < site_count
                        or site in assigned_sites
                    ):
                        raise OnlineDatabaseError(
                            "The selected structure has an invalid disorder "
                            "assembly."
                        )
                    assigned_sites.add(site)
                    probabilities[site] = value
        return probabilities

    @staticmethod
    def _occupation(definition: dict[str, Any]) -> dict[str, float]:
        symbols = definition.get("chemical_symbols") or ()
        concentrations = definition.get("concentration") or ()
        if len(symbols) != len(concentrations) or not symbols:
            raise OnlineDatabaseError(
                "The selected structure contains an invalid species definition."
            )

        occupation: dict[str, float] = {}
        for symbol, concentration in zip(symbols, concentrations):
            try:
                value = float(concentration)
            except (TypeError, ValueError) as exc:
                raise OnlineDatabaseError(
                    "The selected structure contains an invalid concentration."
                ) from exc
            if value < 0:
                raise OnlineDatabaseError(
                    "The selected structure contains a negative concentration."
                )
            if symbol == "vacancy":
                target = "Vc"
            elif symbol == "X":
                raise OnlineDatabaseError(
                    "The selected structure contains an unknown chemical species."
                )
            elif symbol not in atomic_numbers:
                raise OnlineDatabaseError(
                    f"The selected structure contains unknown element {symbol!r}."
                )
            else:
                target = symbol
            occupation[target] = occupation.get(target, 0.0) + value

        return CodOptimadeProvider._normalize_occupation(occupation)

    @staticmethod
    def _normalize_occupation(
        occupation: dict[str, float],
    ) -> dict[str, float]:
        occupation = {
            symbol: concentration
            for symbol, concentration in occupation.items()
            if concentration > 0.0
        }
        total = sum(occupation.values())
        if total > 1.0 + 1e-6:
            raise OnlineDatabaseError(
                "The selected structure has site concentrations greater than one."
            )
        if total < 1.0 - 1e-6:
            occupation["Vc"] = occupation.get("Vc", 0.0) + (1.0 - total)
        correction = 1.0 - sum(occupation.values())
        correction_target = (
            "Vc"
            if "Vc" in occupation
            else max(occupation, key=occupation.get)
        )
        occupation[correction_target] += correction
        return occupation
