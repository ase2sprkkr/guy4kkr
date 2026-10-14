from __future__ import annotations

import pytest
from ase import Atoms

from guy4ase.gui.application.workflow_facts import ScfProgress
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController


def test_controller_exposes_live_read_only_workspace_properties():
    controller = WorkspaceController(WorkspaceState())

    assert controller.atoms is None

    atoms = Atoms("Fe")
    controller.replace_structure(atoms, potential_path="Fe.pot")

    assert controller.atoms is atoms
    assert controller.potential_path == "Fe.pot"

    with pytest.raises(AttributeError):
        controller.atoms = Atoms("Cu")
    with pytest.raises(AttributeError):
        controller.potential_path = "Cu.pot"

    assert controller.atoms is atoms
    assert controller.potential_path == "Fe.pot"


def test_controller_exposes_normalized_scf_progress(monkeypatch):
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Fe")))
    monkeypatch.setattr(controller, "scf_status", lambda: "ITR-L-BULK")
    monkeypatch.setattr(controller, "is_scf_converged", lambda: False)

    assert controller.scf_progress() is ScfProgress.LEFT_BULK

    monkeypatch.setattr(controller, "is_scf_converged", lambda: True)
    assert controller.scf_progress() is ScfProgress.CONVERGED
