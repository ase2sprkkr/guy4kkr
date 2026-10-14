from __future__ import annotations

from types import SimpleNamespace

from ase import Atoms

from guy4ase.gui.application import result_loading
from guy4ase.gui.application.potential_version import PotentialFileVersion
from guy4ase.gui.application.result_capture import capture_result, capture_structure
from guy4ase.gui.application.result_presentation import present_result_record
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController


class _Value:
    info = ""
    display_name = "value"

    def value_label(self):
        return "value"

    def actions(self):
        return ()


def _result(task: str):
    return SimpleNamespace(
        task_name=task,
        output_file=f"{task}.out",
        output_values={"value": _Value()},
    )


def _captured(result):
    return capture_result(
        result,
        input_parameters=None,
        output_path=None,
        potential_path=None,
    )


def _make_two_scf_versions(controller, potential, tmp_path):
    history = controller.result_history
    structure_id = controller.structure_id
    initial_state_id = controller.state_id
    assert structure_id is not None
    assert initial_state_id is not None

    potential.write_text("version one", encoding="utf-8")
    output1 = capture_structure(Atoms("Fe"), potential_path=potential)
    scf1 = history.add_result(
        _captured(_result("scf")),
        structure_id=structure_id,
        input_state_id=initial_state_id,
        directory=str(tmp_path),
        output_structure=output1,
    )
    assert scf1.output_state_id is not None

    potential.write_text("version two is deliberately longer", encoding="utf-8")
    output2 = capture_structure(Atoms("Fe"), potential_path=potential)
    scf2 = history.add_result(
        _captured(_result("scf")),
        structure_id=structure_id,
        input_state_id=scf1.output_state_id,
        directory=str(tmp_path),
        output_structure=output2,
    )
    assert scf2.output_state_id is not None
    return scf1, scf2


def test_continue_current_version_reuses_scf2_state(tmp_path, monkeypatch):
    potential = tmp_path / "Fe.pot"
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Fe")))
    scf1, scf2 = _make_two_scf_versions(controller, potential, tmp_path)
    history = controller.result_history

    scf2_state = history.state(scf2.output_state_id)
    version2 = PotentialFileVersion.capture(potential)
    assert scf2_state.potential_version == version2
    assert scf2_state.potential_source_result_id == scf2.id
    assert scf2_state.structure_snapshot is None

    loaded_atoms = Atoms("Fe")
    monkeypatch.setattr(result_loading, "load_potential_atoms", lambda path: loaded_atoms)

    structures_before = history.structures
    generation_before = controller.generation
    controller.use_result_state(scf1.id, version2)

    assert controller.state_id == scf2.output_state_id
    assert controller.structure_id == scf2_state.structure_id
    assert controller.atoms is loaded_atoms
    assert history.structures == structures_before
    assert controller.generation != generation_before
    assert history.potential_source_result(controller.state_id) is scf2

    generation_after = controller.generation
    controller.use_result_state(scf1.id, version2)
    assert controller.state_id == scf2.output_state_id
    assert controller.generation == generation_after
    assert history.structures == structures_before

    dos = history.add_result(
        _captured(_result("dos")),
        structure_id=controller.structure_id,
        input_state_id=controller.state_id,
        directory=str(tmp_path),
    )
    assert dos.input_state_id == scf2.output_state_id
    assert history.potential_source_result(dos.input_state_id) is scf2


def test_current_version_action_hides_when_current_state_is_active(tmp_path):
    potential = tmp_path / "Fe.pot"
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Fe")))
    scf1, scf2 = _make_two_scf_versions(controller, potential, tmp_path)
    history = controller.result_history
    scf2_state = history.state(scf2.output_state_id)

    presentation = present_result_record(
        history,
        scf1,
        current_structure_id=scf2_state.structure_id,
        current_state_id=scf2_state.id,
    )

    assert presentation.actions.use_state is None


def test_current_version_policy_approves_exact_current_version(tmp_path):
    potential = tmp_path / "Fe.pot"
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Fe")))
    scf1, _scf2 = _make_two_scf_versions(controller, potential, tmp_path)
    history = controller.result_history

    presentation = present_result_record(
        history,
        scf1,
        current_structure_id=controller.structure_id,
        current_state_id=controller.state_id,
    )

    action = presentation.actions.use_state
    assert action is not None
    assert action.label == "Continue with current version of this potential"
    assert action.expected_potential == PotentialFileVersion.capture(potential)
