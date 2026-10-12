from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QApplication, QMenu

from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.dialogs.main_window import MainWindow
from guy4ase.gui.dialogs.structures import source as source_module
from guy4ase.gui.flows.structure_candidates import StructureCandidate
from guy4ase.gui.widgets.recent_launcher import populate_recent_menu


def _app():
    return QApplication.instance() or QApplication([])


def test_populate_recent_menu_uses_shared_path_labels_and_tooltips(tmp_path, monkeypatch):
    _app()
    work = tmp_path / "work"
    work.mkdir()
    inside = work / "results" / "Fe.cif"
    inside.parent.mkdir()
    inside.touch()
    outside = tmp_path / "outside" / "Cu.cif"
    outside.parent.mkdir()
    outside.touch()
    history = RecentFiles(tmp_path / "recent.json")
    history.remember("structure", outside)
    history.remember("structure", inside)
    monkeypatch.chdir(work)
    opened = []
    menu = QMenu()

    populate_recent_menu(menu, history, "structure", opened.append)

    actions = menu.actions()
    assert [action.text() for action in actions] == [
        str(Path("results") / "Fe.cif"),
        str(outside.resolve()),
    ]
    assert [action.toolTip() for action in actions] == [
        str(inside.resolve()),
        str(outside.resolve()),
    ]
    actions[1].trigger()
    assert opened == [str(outside.resolve())]


def test_populate_recent_menu_has_disabled_empty_action(tmp_path):
    _app()
    history = RecentFiles(tmp_path / "recent.json")
    menu = QMenu()

    populate_recent_menu(menu, history, "input", lambda _path: None)

    actions = menu.actions()
    assert len(actions) == 1
    assert actions[0].text() == "(No recent files)"
    assert not actions[0].isEnabled()


def test_expert_recent_menu_uses_shared_presentation(tmp_path, monkeypatch):
    _app()
    work = tmp_path / "work"
    work.mkdir()
    target = work / "structures" / "Fe.cif"
    target.parent.mkdir()
    target.touch()
    history = RecentFiles(tmp_path / "recent.json")
    history.remember("structure", target)
    monkeypatch.chdir(work)
    menu = QMenu()
    opened = []

    class Window:
        recent_history = history
        _recent_menus = {"structure": menu}

        def open_recent_file(self, kind, path):
            opened.append((kind, path))

    MainWindow._refresh_recent_menu(Window(), "structure")

    action = menu.actions()[0]
    assert action.text() == str(Path("structures") / "Fe.cif")
    assert action.toolTip() == str(target.resolve())
    action.trigger()
    assert opened == [("structure", str(target.resolve()))]


def test_structure_source_recent_success_moves_path_to_front(tmp_path, monkeypatch):
    _app()
    first = tmp_path / "first.cif"
    second = tmp_path / "second.cif"
    first.touch()
    second.touch()
    history = RecentFiles(tmp_path / "recent.json")
    history.remember("structure", first)
    history.remember("structure", second)
    loaded = object()
    candidate = StructureCandidate(loaded)
    monkeypatch.setattr(
        source_module.structure_candidates,
        "load_structure_candidate",
        lambda path, parent: candidate,
    )
    dialog = source_module.StructureSourceDialog(recent_files=history)

    dialog._load_recent_path(first)

    assert history.paths("structure")[0] == str(first.resolve())
    assert dialog.candidate() is candidate
    dialog.close()
