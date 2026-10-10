from __future__ import annotations

from types import SimpleNamespace

from guy4ase.gui.application.settings import ApplicationSettings
from guy4ase.gui.flows import visualization


def test_settings_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    settings = ApplicationSettings(path)

    settings.load()
    assert settings.viewer == "ase"

    settings.viewer = "vmd"
    assert settings.save()

    loaded = ApplicationSettings(path)
    loaded.load()
    assert loaded.viewer == "vmd"


def test_corrupt_settings_keep_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")

    settings = ApplicationSettings(path)
    settings.load()

    assert settings.viewer == "ase"


def test_visualization_uses_configured_viewer(monkeypatch):
    atoms = SimpleNamespace(copy=lambda: "atoms snapshot")

    class Controller:
        def read_structure(self, reader, *, reason):
            assert reason == "reading the structure for visualization"
            return 7, reader(atoms)

    opened = []
    monkeypatch.setattr(
        visualization,
        "wait_for_structure",
        lambda _parent, operation: operation(),
    )
    monkeypatch.setattr(
        visualization,
        "ase_view",
        lambda value, *, viewer: opened.append((value, viewer)),
    )

    settings = ApplicationSettings()
    settings.viewer = "ngl"

    assert visualization.visualize_structure(
        Controller(),
        settings,
        parent=None,
    )
    assert opened == [("atoms snapshot", "ngl")]
