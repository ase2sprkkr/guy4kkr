from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ase import Atoms
from ase2sprkkr import SPRKKRAtoms
from PyQt6.QtWidgets import QApplication

from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.widgets.result_actions import ResultActionsWidget


class _Parameters:
    def copy(self, *, copy_values: bool):
        assert copy_values
        return self


def _atoms_with_potential(marker: str):
    atoms = SPRKKRAtoms.promote_ase_atoms(
        Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True),
        symmetry=False,
    )
    atoms._potential = SimpleNamespace(atoms=atoms, marker=marker)
    return atoms


def _loaded_scf(atoms, potential_path: str | Path | None = None):
    return LoadedResult(
        result=SimpleNamespace(task_name="scf", output_values={}),
        output_path=None,
        potential_path=(Path(potential_path) if potential_path is not None else None),
        atoms=atoms,
        potential_error=None,
        directory=None,
    )


def test_use_result_state_never_substitutes_current_atoms_for_historical_state(tmp_path):
    controller = WorkspaceController(
        WorkspaceState(
            atoms=_atoms_with_potential("root"),
            input_parameters=_Parameters(),
            directory=str(tmp_path),
        )
    )
    current_request = controller.create_calculation_request()
    historical_request = controller.create_calculation_request()

    current_atoms = _atoms_with_potential("current")
    current = controller.adopt_calculation_result(
        _loaded_scf(current_atoms),
        request=current_request,
    )
    assert current.workspace_updated

    historical_atoms = _atoms_with_potential("historical")
    historical = controller.adopt_calculation_result(
        _loaded_scf(historical_atoms),
        request=historical_request,
    )
    assert not historical.workspace_updated
    assert current.record.structure_id == historical.record.structure_id
    assert controller.atoms is current_atoms

    controller.use_result_state(historical.record.id)

    assert controller.state_id == historical.record.output_state_id
    assert controller.atoms is historical_atoms
    assert controller.atoms is not current_atoms
    assert controller.atoms.potential.marker == "historical"


def test_result_action_does_not_follow_overwritten_potential_path(tmp_path):
    """A click activates the state shown by the UI, not the file now at its path."""
    _application = QApplication.instance() or QApplication([])
    historical_path = tmp_path / "historical.pot"
    current_path = tmp_path / "current.pot"
    historical_path.write_text("historical file", encoding="utf-8")
    current_path.write_text("current file", encoding="utf-8")

    controller = WorkspaceController(
        WorkspaceState(
            atoms=_atoms_with_potential("root"),
            input_parameters=_Parameters(),
            directory=str(tmp_path),
        )
    )
    historical_request = controller.create_calculation_request()
    historical_atoms = _atoms_with_potential("historical")
    historical = controller.adopt_calculation_result(
        _loaded_scf(historical_atoms, historical_path),
        request=historical_request,
    )
    assert historical.workspace_updated

    current_request = controller.create_calculation_request()
    current_atoms = _atoms_with_potential("current")
    current = controller.adopt_calculation_result(
        _loaded_scf(current_atoms, current_path),
        request=current_request,
    )
    assert current.workspace_updated
    assert controller.atoms is current_atoms

    widget = ResultActionsWidget(
        lambda _value, _action: None,
        show_values_without_actions=True,
    )
    widget.useStateRequested.connect(controller.use_result_state)
    widget.set_workspace_state(controller.structure_id, controller.state_id)
    widget.set_results(controller.result_store)
    assert widget.select_result(historical.record.id)
    assert widget._use_state_button.text() == "Use this potential"

    # This is the TOCTOU window from the bug report. The path now contains a
    # different file, but it is not the physical authority on master.
    historical_path.write_text("replacement file", encoding="utf-8")
    widget._use_selected_state()

    assert controller.state_id == historical.record.output_state_id
    assert controller.atoms is historical_atoms
    assert controller.atoms.potential.marker == "historical"
    assert controller.potential_path == str(historical_path)
    widget.close()
