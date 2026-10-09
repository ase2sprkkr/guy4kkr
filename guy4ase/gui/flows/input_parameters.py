"""Shared file workflows for transactional input-parameter editors."""
from __future__ import annotations

from pathlib import Path

from ase2sprkkr.input_parameters.input_parameters import InputParameters
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox, QWidget

from guy4ase.gui.dialogs.input_file import InputFileEditor
from guy4ase.gui.input_parameters.session import InputParametersSession

_INPUT_FILE_FILTER = "SPRKKR Input Files (*.inp *.in *.txt);;All Files (*)"


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


def load_input_parameters(
    session: InputParametersSession,
    file_path: str | Path,
    parent: QWidget | None,
) -> bool:
    """Parse an input file and install it without leaking parser/UI policy."""
    try:
        path = Path(file_path).resolve()
        parameters = InputParameters.from_file(path)
        session.replace_parameters(
            parameters,
            text=f"Load {path.name}",
            source_page="load",
        )
    except Exception as exc:  # noqa: BLE001 - parser/apply errors are heterogeneous.
        QMessageBox.critical(
            parent,
            "Load Error",
            f"Failed to load input parameters:\n{exc}",
        )
        return False
    return True


def edit_input_parameters_file(
    session: InputParametersSession,
    parent: QWidget | None,
) -> None:
    """Edit generated input text and apply a valid result transactionally."""
    focus = QApplication.focusWidget()
    if focus is not None:
        focus.clearFocus()
    try:
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
    except Exception as exc:  # noqa: BLE001 - modal callback boundary.
        QMessageBox.critical(parent, "Input File Error", str(exc))
