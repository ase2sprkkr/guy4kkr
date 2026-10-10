import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/guy4ase-test-matplotlib")

import pytest
from ase2sprkkr.common.warnings import DataValidityError
from ase2sprkkr.input_parameters.input_parameters import InputParameters
from PyQt6.QtWidgets import QApplication

from guy4ase.gui.dialogs import guided_input
from guy4ase.gui.dialogs.guided_input import GuidedInputParametersDialog
from guy4ase.gui.flows import input_parameters as input_parameter_flows
from guy4ase.gui.input_parameters.session import create_input_parameters_session
from guy4ase.gui.input_parameters.validation import (
    InputParametersValidationError,
    validate_setup,
)


@pytest.fixture
def application():
    return QApplication.instance() or QApplication([])


def _raise(error):
    raise error


def test_load_reports_parser_error(monkeypatch, tmp_path, application):
    session = create_input_parameters_session(InputParameters.create("scf"))
    messages = []
    monkeypatch.setattr(
        input_parameter_flows.InputParameters,
        "from_file",
        lambda _path: _raise(RuntimeError("broken input")),
    )
    monkeypatch.setattr(
        input_parameter_flows.QMessageBox,
        "critical",
        lambda _parent, _title, text: messages.append(text),
    )

    assert not input_parameter_flows.load_input_parameters(
        session, tmp_path / "broken.inp", None
    )
    assert messages == ["Failed to load input parameters:\nbroken input"]


def test_load_does_not_hide_session_error(monkeypatch, tmp_path, application):
    session = create_input_parameters_session(InputParameters.create("scf"))
    parameters = InputParameters.create("scf")
    monkeypatch.setattr(
        input_parameter_flows.InputParameters,
        "from_file",
        lambda _path: parameters,
    )
    monkeypatch.setattr(
        session,
        "replace_parameters",
        lambda *_args, **_kwargs: _raise(RuntimeError("session invariant")),
    )

    with pytest.raises(RuntimeError, match="session invariant"):
        input_parameter_flows.load_input_parameters(
            session, tmp_path / "valid.inp", None
        )


def test_wrong_task_is_a_user_facing_load_error(
    monkeypatch, tmp_path, application
):
    session = create_input_parameters_session(InputParameters.create("scf"))
    monkeypatch.setattr(
        input_parameter_flows.InputParameters,
        "from_file",
        lambda _path: InputParameters.create("dos"),
    )
    messages = []
    monkeypatch.setattr(
        input_parameter_flows.QMessageBox,
        "critical",
        lambda _parent, _title, text: messages.append(text),
    )

    assert not input_parameter_flows.load_input_parameters(
        session, tmp_path / "dos.inp", None
    )
    assert "Expected SCF input parameters, got DOS." in messages[0]


def test_text_editor_flow_does_not_hide_dialog_error(monkeypatch, application):
    session = create_input_parameters_session(InputParameters.create("scf"))

    class BrokenEditor:
        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            raise RuntimeError("dialog bug")

    monkeypatch.setattr(input_parameter_flows, "InputFileEditor", BrokenEditor)

    with pytest.raises(RuntimeError, match="dialog bug"):
        input_parameter_flows.edit_input_parameters_file(session, None)


def test_guided_expert_does_not_hide_dialog_error(monkeypatch, application):
    dialog = GuidedInputParametersDialog("scf", InputParameters.create("scf"))
    monkeypatch.setattr(dialog, "_commit_pending", lambda: True)
    monkeypatch.setattr(
        guided_input,
        "edit_input_parameters_session",
        lambda *_args, **_kwargs: _raise(RuntimeError("expert bug")),
    )

    with pytest.raises(RuntimeError, match="expert bug"):
        dialog._open_expert_settings()
    dialog.close()


class _ValidationParameters:
    task_name = "scf"

    def __init__(self, error):
        self.error = error

    def validate(self, **_kwargs):
        raise self.error

    def __contains__(self, _name):
        return False


def test_validate_setup_wraps_expected_validation_error():
    parameters = _ValidationParameters(DataValidityError("bad value"))

    with pytest.raises(InputParametersValidationError, match="bad value"):
        validate_setup(parameters)


def test_validate_setup_does_not_hide_programming_error():
    parameters = _ValidationParameters(RuntimeError("validation bug"))

    with pytest.raises(RuntimeError, match="validation bug"):
        validate_setup(parameters)
