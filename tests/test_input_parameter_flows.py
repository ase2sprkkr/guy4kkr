import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/guy4ase-test-matplotlib")

from ase2sprkkr.input_parameters.input_parameters import InputParameters
from PyQt6.QtWidgets import QApplication

from guy4ase.gui.flows import input_parameters as input_parameter_flows
from guy4ase.gui.input_parameters.session import create_input_parameters_session


def _changed_scf_parameters(session):
    parameters = session.result()
    initial = int(session.value(("SCF", "NITER")))
    parameters.SCF.NITER.set(initial + 1)
    return parameters, initial


def test_load_input_parameters_is_one_named_session_transaction(
    monkeypatch, tmp_path
):
    application = QApplication.instance() or QApplication([])
    assert application is not None
    session = create_input_parameters_session(InputParameters.create("scf"))
    parameters, initial = _changed_scf_parameters(session)
    path = tmp_path / "loaded.inp"
    path.write_text("not parsed because the reader is stubbed")
    monkeypatch.setattr(
        input_parameter_flows.InputParameters,
        "from_file",
        lambda _path: parameters,
    )

    assert input_parameter_flows.load_input_parameters(session, path, None)

    command = session.undo_stack.command(0)
    assert session.undo_stack.count() == 1
    assert command.text() == "Load loaded.inp"
    assert command.source_page == "load"
    assert session.value(("SCF", "NITER")) == initial + 1

    session.undo_stack.undo()
    assert session.value(("SCF", "NITER")) == initial


def test_text_editor_applies_through_the_same_session_flow(monkeypatch):
    application = QApplication.instance() or QApplication([])
    assert application is not None
    session = create_input_parameters_session(InputParameters.create("scf"))
    parameters, initial = _changed_scf_parameters(session)

    class FakeInputFileEditor:
        def __init__(self, _parameters, _parent, *, apply_parameters):
            self.apply_parameters = apply_parameters

        def exec(self):
            self.apply_parameters(parameters)

    monkeypatch.setattr(
        input_parameter_flows,
        "InputFileEditor",
        FakeInputFileEditor,
    )

    input_parameter_flows.edit_input_parameters_file(session, None)

    command = session.undo_stack.command(0)
    assert session.undo_stack.count() == 1
    assert command.text() == "Edit input file"
    assert command.source_page == "input_file"
    assert session.value(("SCF", "NITER")) == initial + 1

    session.undo_stack.undo()
    assert session.value(("SCF", "NITER")) == initial
