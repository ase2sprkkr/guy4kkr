import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/guy4ase-test-matplotlib")

from ase import Atoms
from PyQt6.QtWidgets import QApplication

from guy4ase.gui.online_structure_dialog import OnlineStructureDialog
from guy4ase.online_databases import (
    DownloadedStructure,
    ProviderCapabilities,
    SearchPage,
    StructureDatabaseProvider,
    StructureProvenance,
    StructureSummary,
)


class _FakeProvider(StructureDatabaseProvider):
    id = "fake"
    name = "Test Database"
    capabilities = ProviderCapabilities()

    def __init__(self):
        self.search_calls = []
        self.fetch_calls = []
        self.summary = StructureSummary(
            provider_id=self.id,
            entry_id="test-1",
            formula="FeO",
            name="test structure",
            site_count=2,
        )

    def search(self, query, *, page_url=None):
        self.search_calls.append((query, page_url))
        return SearchPage((self.summary,), total=1)

    def fetch(self, summary):
        self.fetch_calls.append(summary)
        atoms = Atoms(
            "FeO",
            positions=((0, 0, 0), (1, 1, 1)),
            cell=(2, 2, 2),
            pbc=True,
        )
        provenance = StructureProvenance(
            provider_id=self.id,
            provider_name=self.name,
            entry_id=summary.entry_id,
            entry_url="https://example.test/test-1",
            retrieved_at="2026-01-01T00:00:00+00:00",
            license_name="CC0-1.0",
            license_url="https://creativecommons.org/publicdomain/zero/1.0/",
            experimental=True,
        )
        atoms.info["online_database"] = provenance.as_dict()
        return DownloadedStructure(atoms, summary, provenance)


def _process_until(application, predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        application.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    application.processEvents()
    assert predicate()


def test_search_fetch_and_open_use_one_provider_flow():
    application = QApplication.instance() or QApplication([])
    provider = _FakeProvider()
    dialog = OnlineStructureDialog(providers=(provider,))

    dialog._elements_edit.setText("fe, O")
    dialog._start_new_search()
    _process_until(application, lambda: dialog._table.rowCount() == 1)

    assert provider.search_calls[0][0].elements == ("Fe", "O")
    assert dialog._table.item(0, 0).text() == "FeO"
    assert not dialog._open_button.isEnabled()

    dialog._table.selectRow(0)
    _process_until(application, dialog._open_button.isEnabled)

    assert provider.fetch_calls == [provider.summary]
    assert dialog.selected_atoms.get_chemical_formula() == "FeO"
    assert dialog.selected_atoms.info["online_database"]["entry_id"] == "test-1"
    dialog.close()
