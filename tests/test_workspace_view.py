from __future__ import annotations

import pytest
from ase import Atoms

from guy4ase.gui.application.workspace import WorkspaceState, WorkspaceView
from guy4ase.gui.application.workspace_controller import WorkspaceController


def test_controller_exposes_live_read_only_workspace_view():
    controller = WorkspaceController(WorkspaceState())
    view = controller.workspace

    assert isinstance(view, WorkspaceView)
    assert view is controller.workspace
    assert view.atoms is None

    atoms = Atoms("Fe")
    controller.replace_structure(atoms, potential_path="Fe.pot")

    assert view.atoms is atoms
    assert view.potential_path == "Fe.pot"

    with pytest.raises(AttributeError):
        view.atoms = Atoms("Cu")
    with pytest.raises(AttributeError):
        view.potential_path = "Cu.pot"

    assert controller.workspace.atoms is atoms
    assert controller.workspace.potential_path == "Fe.pot"


def test_workspace_property_cannot_be_replaced():
    controller = WorkspaceController()

    with pytest.raises(AttributeError):
        controller.workspace = WorkspaceState()
