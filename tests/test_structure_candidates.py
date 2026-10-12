from __future__ import annotations

from types import SimpleNamespace

from ase import Atoms

from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.dialogs.structures import build_2d as build_2d_dialog
from guy4ase.gui.flows import structure_candidates as candidate_flows
from guy4ase.gui.flows.structure_candidates import StructureCandidate


def test_structure_candidate_load_has_no_workspace_side_effects(tmp_path):
    path = tmp_path / "replacement.cif"
    loaded = Atoms("Fe")
    workspace_atoms = Atoms("Cu")
    workspace = WorkspaceState(
        atoms=workspace_atoms,
        potential_path="Cu.pot",
        result=object(),
    )
    current_result = workspace.result

    candidate = candidate_flows.load_structure_candidate(
        path,
        None,
        reader=lambda value: loaded if value == path.resolve() else None,
    )

    assert candidate == StructureCandidate(loaded, path.resolve())
    assert workspace.atoms is workspace_atoms
    assert workspace.potential_path == "Cu.pot"
    assert workspace.result is current_result


def test_build_2d_replacement_uses_shared_structure_source(monkeypatch):
    loaded = Atoms("Fe")
    recent_files = object()
    assigned = []
    calls = []
    dialog = SimpleNamespace(
        _recent_files=recent_files,
        _set_right_atoms=assigned.append,
    )

    def select(*args, **kwargs):
        calls.append((args, kwargs))
        return StructureCandidate(loaded)

    monkeypatch.setattr(build_2d_dialog, "select_structure_source", select)

    build_2d_dialog.Build2DStructureDialog._on_choose_right(dialog)

    assert assigned == [loaded]
    assert calls == [
        (
            (dialog,),
            {
                "recent_files": recent_files,
                "title": "Choose Replacement Structure",
            },
        )
    ]
