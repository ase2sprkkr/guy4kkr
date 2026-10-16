"""Shared file workflows for transactional input-parameter editors."""
from __future__ import annotations

from pathlib import Path

import pyparsing as pp
from ase2sprkkr import InputParameters
from ase2sprkkr.common.warnings import DataValidityError
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QWidget

from guy4ase.gui.dialogs.input_file import InputFileEditor
from guy4ase.gui.input_parameters.session import InputParametersSession

_INPUT_FILE_FILTER = "SPRKKR Input Files (*.inp *.in *.txt);;All Files (*)"


class InputParametersLoadError(RuntimeError):
    """A user input file could not be parsed by the session's input schema."""


def choose_and_load_input_parameters(
    session: InputParametersSession,
    parent: QWidget | None,
) -> bool:
    """Choose an input file and install it as one session transaction."""
    file_path, _ = QFileDialog.getOpenFileName(
        parent,
        "Load SPRKKR Input File",
        "",
        _INPUT_FILE_FILTER,
    )
    return bool(
        file_path
        and load_input_parameters(session, file_path, parent)
    )


def _load_error(parent: QWidget | None, exception: Exception | str) -> bool:
    QMessageBox.critical(
        parent,
        "Load Error",
        f"Failed to load input parameters:\n{exception}",
    )
    return False


def _read_for_schema(path: Path, schema_name: str):
    """Read *path* with one already-known input schema.

    Guided editing already knows the schema of the active session.  Shared
    schemas derive the effective backend task from the parsed values, so trying
    each task separately is both redundant and unsafe: a mismatched task parser
    can be much more expensive than parsing the schema once.

    Registry/configuration errors happen before the parsing boundary and must
    propagate.  Only ordinary parser/validation failures are normalized as a
    user-facing load error.
    """
    definition = InputParameters.definition(schema_name)
    try:
        return definition.read_from_file(path)
    except (pp.ParseBaseException, DataValidityError) as exc:
        raise InputParametersLoadError(str(exc)) from exc


def load_input_parameters(
    session: InputParametersSession,
    file_path: str | Path,
    parent: QWidget | None,
) -> bool:
    """Parse an input file and install it as one session transaction."""
    path = Path(file_path).resolve()
    expected_schema = session.working_parameters.definition_name.upper()
    try:
        parameters = _read_for_schema(path, expected_schema)
    except InputParametersLoadError as exc:
        return _load_error(parent, exc)

    actual_schema = parameters.definition_name.upper()
    if actual_schema != expected_schema:
        return _load_error(
            parent,
            ValueError(
                f"Expected {expected_schema} input schema, got {actual_schema}."
            ),
        )

    # Session application is a separate boundary. Programming/invariant errors
    # here must propagate rather than be re-labelled as file parsing failures.
    session.replace_parameters(
        parameters,
        text=f"Load {path.name}",
        source_page="load",
    )
    return True


def edit_input_parameters_file(
    session: InputParametersSession,
    parent: QWidget | None,
) -> None:
    """Edit generated input text and apply a valid result transactionally."""
    editor = InputFileEditor(
        session.result(),
        parent,
        apply_parameters=lambda parameters: session.replace_parameters(
            parameters,
            text="Edit input file",
            source_page="input_file",
        ),
    )
    editor.exec()
