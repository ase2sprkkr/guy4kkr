from urllib.parse import parse_qs, urlparse

import pytest

from guy4ase.online_databases.models import StructureSearchQuery
from guy4ase.online_databases.optimade import (
    CodOptimadeProvider,
    OnlineDatabaseError,
)


def _summary_resource(entry_id="1000001"):
    return {
        "id": entry_id,
        "type": "structures",
        "attributes": {
            "chemical_formula_reduced": "Fe2O3",
            "nsites": 5,
            "structure_features": [],
            "_cod_commonname": "hematite",
            "_cod_sg": "R-3c",
            "_cod_sgnumber": 167,
            "_cod_method": "single crystal X-ray diffraction",
            "_cod_year": 2020,
            "_cod_status": None,
            "_cod_duplicateof": None,
            "_cod_optimal": 1000001,
            "_cod_doi": "10.1234/example",
        },
    }


def test_cod_search_builds_filters_and_parses_pagination():
    requested = []

    def transport(url):
        requested.append(url)
        return {
            "data": [_summary_resource()],
            "meta": {"data_returned_available": 123},
            "links": {
                "next": "/cod/optimade/v1/structures?page_offset=50",
                "prev": None,
            },
        }

    provider = CodOptimadeProvider(transport=transport)
    page = provider.search(
        StructureSearchQuery(
            text="Fe2O3",
            elements=("Fe", "O"),
            exact_elements=True,
            space_group=167,
            max_sites=20,
            ordered_only=True,
        )
    )

    query = parse_qs(urlparse(requested[0]).query)
    assert query["page_limit"] == ["10"]
    filter_text = query["filter"][0]
    assert 'chemical_formula_hill="Fe2O3"' in filter_text
    assert 'elements HAS ALL "Fe", "O"' in filter_text
    assert "nelements=2" in filter_text
    assert "_cod_sgnumber=167" in filter_text
    assert "nsites<=20" not in filter_text
    assert "_cod_duplicateof IS UNKNOWN" in filter_text
    assert 'NOT structure_features HAS "disorder"' not in filter_text
    assert page.total == 123
    assert page.next_url == (
        "https://www.crystallography.net/cod/optimade/v1/"
        "structures?page_offset=50"
    )
    assert page.results[0].name == "hematite"
    assert page.results[0].space_group_number == 167


def test_formula_is_normalized_to_the_hill_format_supported_by_cod():
    provider = CodOptimadeProvider(transport=lambda _url: {"data": []})

    filters = provider._filters(StructureSearchQuery(text="NaCl"))

    assert 'chemical_formula_hill="ClNa"' in filters


def test_cod_fetch_preserves_partial_occupancies_and_provenance():
    full_resource = _summary_resource()
    full_resource["attributes"].update(
        {
            "nsites": 3,
            "lattice_vectors": [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 6.0]],
            "cartesian_site_positions": [
                [0.0, 0.0, 0.0],
                [2.0, 2.0, 2.0],
                [1.0, 1.0, 1.0],
            ],
            "dimension_types": [1, 1, 1],
            "species_at_sites": ["Fe", "mixed", "vac"],
            "species": [
                {
                    "name": "Fe",
                    "chemical_symbols": ["Fe"],
                    "concentration": [1.0],
                },
                {
                    "name": "mixed",
                    "chemical_symbols": ["Fe", "Ni"],
                    "concentration": [0.6, 0.3],
                },
                {
                    "name": "vac",
                    "chemical_symbols": ["vacancy"],
                    "concentration": [1.0],
                },
            ],
            "structure_features": ["assemblies", "disorder"],
            "assemblies": [
                {
                    "sites_in_groups": [[1], [2]],
                    "group_probabilities": [0.7, 0.3],
                }
            ],
            "_cod_celltemp": 295,
            "_cod_cellpressure": 101.325,
        }
    )

    provider = CodOptimadeProvider(
        transport=lambda _url: {"data": full_resource}
    )
    summary = provider._summary(_summary_resource())
    downloaded = provider.fetch(summary)

    assert downloaded.atoms.get_chemical_symbols() == ["Fe", "Fe", "X"]
    assert downloaded.atoms.info["occupancy"]["0"] == {"Fe": 1.0}
    assert downloaded.atoms.info["occupancy"]["1"] == {
        "Fe": pytest.approx(0.42),
        "Ni": pytest.approx(0.21),
        "Vc": pytest.approx(0.37),
    }
    assert downloaded.atoms.info["occupancy"]["2"] == {"Vc": 1.0}
    assert downloaded.provenance.entry_id == "1000001"
    assert downloaded.provenance.license_name == "CC0-1.0"
    assert downloaded.provenance.temperature_kelvin == 295.0
    assert downloaded.atoms.info["online_database"]["doi"] == "10.1234/example"
    assert downloaded.atoms.info["online_database"]["provider_metadata"][
        "optimade_assemblies"
    ] == full_resource["attributes"]["assemblies"]
    assert any("Correlated disorder" in item for item in downloaded.warnings)


def test_unknown_optimade_species_is_rejected():
    with pytest.raises(OnlineDatabaseError, match="unknown chemical species"):
        CodOptimadeProvider._occupation(
            {"chemical_symbols": ["X"], "concentration": [1.0]}
        )
