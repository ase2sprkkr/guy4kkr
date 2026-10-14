from __future__ import annotations

import pytest
from ase import Atoms

from guy4ase.gui.application import result_loading
from guy4ase.gui.application.potential_version import PotentialFileVersion
from guy4ase.gui.application.result_loading import PotentialVersionChanged


def test_exact_potential_loader_rejects_change_after_parse(tmp_path, monkeypatch):
    path = tmp_path / "Fe.pot"
    path.write_text("stable potential", encoding="utf-8")
    version = PotentialFileVersion.capture(path)
    atoms = Atoms("Fe")

    def load_and_change(_path):
        path.write_text("changed after parsing", encoding="utf-8")
        return atoms

    monkeypatch.setattr(result_loading, "load_potential_atoms", load_and_change)

    with pytest.raises(PotentialVersionChanged, match="while it was being read"):
        result_loading.load_potential_version(version)
