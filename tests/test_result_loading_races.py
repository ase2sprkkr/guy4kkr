from __future__ import annotations

from types import SimpleNamespace

import pytest
from ase import Atoms

from guy4ase.gui.application import result_loading
from guy4ase.gui.application.potential_version import PotentialFileVersion
from guy4ase.gui.application.result_loading import (
    OutputVersionChanged,
    PotentialVersionChanged,
)


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


def test_potential_materialization_binds_atoms_to_exact_captured_version(
    tmp_path, monkeypatch
):
    path = tmp_path / "Fe.pot"
    path.write_text("stable potential", encoding="utf-8")
    seen = []

    def load_exact(version):
        seen.append(version)
        return Atoms("Fe")

    monkeypatch.setattr(result_loading, "load_potential_version", load_exact)

    structure = result_loading.load_potential_materialized(path)

    assert seen == [structure.provenance.potential_version]
    assert structure.provenance.potential_path == path.resolve()
    assert structure.get().get_chemical_symbols() == ["Fe"]


def test_result_file_loader_rejects_output_changed_during_parse(tmp_path, monkeypatch):
    path = tmp_path / "Fe.out"
    path.write_text("v1", encoding="utf-8")

    def parse_and_change(_path):
        path.write_text("v2", encoding="utf-8")
        return SimpleNamespace(files={}, task_name="dos", directory=tmp_path)

    monkeypatch.setattr(
        result_loading.TaskResult,
        "from_file",
        staticmethod(parse_and_change),
    )

    with pytest.raises(OutputVersionChanged, match="changed while it was read"):
        result_loading.load_result_file(path)


def test_result_file_loader_carries_exact_output_version(tmp_path, monkeypatch):
    path = tmp_path / "Fe.out"
    path.write_text("stable", encoding="utf-8")
    parsed = SimpleNamespace(files={}, task_name="dos", directory=tmp_path)
    monkeypatch.setattr(
        result_loading.TaskResult,
        "from_file",
        staticmethod(lambda _path: parsed),
    )

    loaded = result_loading.load_result_file(path)

    assert loaded.output_path == path.resolve()
    assert loaded.output_version is not None
    assert loaded.output_version.path == path.resolve()
    assert loaded.output_version.current() == loaded.output_version
