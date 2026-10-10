from __future__ import annotations

from ase import Atoms

from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.flows import calculation as calculation_flow
from guy4ase.gui.flows import input_editing as input_editing_flow
from guy4ase.gui.flows import structures as structure_flows


class _Parameters:
    def __init__(self, name: str) -> None:
        self.name = name

    def copy(self, *, copy_values: bool):
        assert copy_values
        return _Parameters(f"{self.name}-copy")


def test_workspace_can_calculate_requires_all_inputs():
    workspace = WorkspaceState()
    assert not workspace.can_calculate()

    workspace.atoms = Atoms("Fe")
    assert not workspace.can_calculate()

    workspace.input_parameters = _Parameters("scf")
    assert not workspace.can_calculate()

    workspace.directory = "calculation"
    assert workspace.can_calculate()


def test_edit_current_structure_uses_detached_revision_snapshot():
    original = Atoms("Fe")
    controller = WorkspaceController(WorkspaceState(atoms=original))

    def edit(atoms, *, parent):
        assert parent is None
        assert atoms is not original
        atoms.symbols = "Cu"
        return atoms

    assert structure_flows.edit_current_structure(
        controller,
        None,
        edit,
        error_title="Edit Error",
    )
    assert controller.workspace.atoms is not original
    assert controller.workspace.atoms.get_chemical_symbols() == ["Cu"]
    assert controller.workspace.restarted


def test_edit_current_input_parameters_commits_accepted_copy(monkeypatch):
    original_atoms = Atoms("Fe")
    original_parameters = _Parameters("original")
    edited_parameters = _Parameters("edited")
    controller = WorkspaceController(
        WorkspaceState(
            atoms=original_atoms,
            input_parameters=original_parameters,
        )
    )

    def edit(parameters, *, parent, show_changed_only, atoms):
        assert parent is None
        assert not show_changed_only
        assert parameters is not original_parameters
        assert parameters.name == "original-copy"
        assert atoms is not original_atoms
        return edited_parameters

    monkeypatch.setattr(
        input_editing_flow,
        "edit_input_parameters",
        edit,
    )

    assert input_editing_flow.edit_current_input_parameters(
        controller,
        None,
    )
    assert controller.workspace.input_parameters is edited_parameters


def test_choose_working_directory_is_shared_flow(monkeypatch, tmp_path):
    controller = WorkspaceController(WorkspaceState())
    chosen = tmp_path / "calculation"
    monkeypatch.setattr(
        calculation_flow.QFileDialog,
        "getExistingDirectory",
        lambda *_args, **_kwargs: str(chosen),
    )

    assert calculation_flow.choose_working_directory(
        controller,
        None,
    )
    assert controller.workspace.directory == str(chosen)
