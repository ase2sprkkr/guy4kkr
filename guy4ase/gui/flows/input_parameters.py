"""Shared file workflows for transactional input-parameter editors."""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ase2sprkkr import InputParameters
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QWidget

from guy4ase.gui.dialogs.input_file import InputFileEditor
from guy4ase.gui.input_parameters.session import InputParametersSession

_INPUT_FILE_FILTER = "SPRKKR Input Files (*.inp *.in *.txt);;All Files (*)"


def choose_and_load_input_parameters(
    session: InputParametersSession,
    parent: QWidget | None,
    *,
    compatible_tasks: Iterable[str] = (),
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
        and load_input_parameters(
            session,
            file_path,
            parent,
            compatible_tasks=compatible_tasks,
        )
    )


def _load_error(parent: QWidget | None, exception: Exception | str) -> bool:
    QMessageBox.critical(
        parent,
        "Load Error",
        f"Failed to load input parameters:\n{exception}",
    )
    return False


def _read_for_task_family(path: Path, task_names: Iterable[str]):
    """Read *path* using only the explicitly accepted backend task family."""
    last_error = None
    for task_name in dict.fromkeys(str(task).upper() for task in task_names):
        # Resolving a declared task is application configuration, not parsing.
        # Let registry/configuration failures propagate instead of presenting
        # them as malformed user input.
        task = InputParameters.task_registry[task_name]
        try:
            return InputParameters.input_parameters_registry.read_for_task(task, path)
        except Exception as exc:  # noqa: BLE001 - backend parser errors are heterogeneous.
            last_error = exc
    if last_error is None:
        raise ValueError("No compatible input-parameter tasks were supplied")
    raise last_error


def load_input_parameters(
    session: InputParametersSession,
    file_path: str | Path,
    parent: QWidget | None,
    *,
    compatible_tasks: Iterable[str] = (),
) -> bool:
    """Parse an input file and install it as one session transaction."""
    path = Path(file_path).resolve()
    accepted_tasks = (session.task_name, *compatible_tasks)
    try:
        parameters = _read_for_task_family(path, accepted_tasks)
    except Exception as exc:  # noqa: BLE001 - backend parser errors are heterogeneous.
        return _load_error(parent, exc)

    expected_schema = session.working_parameters.definition_name.upper()
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
