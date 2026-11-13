"""Qt file orchestration around the workspace document controller."""
from __future__ import annotations

import re
from functools import partial
from pathlib import Path

from ase.io import read as ase_read
from ase.io import write as ase_write
from ase.io.formats import ioformats
from ase2sprkkr.input_parameters.input_parameters import InputParameters
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QWidget

from guy4ase.gui.application.recent_files import RecentFiles, RecentKind
from guy4ase.gui.application.result_loading import load_result_file
from guy4ase.gui.application.workspace_controller import (
    Busy,
    DocumentChange,
    ResultAdoption,
    WorkspaceController,
)
from guy4ase.gui.flows.structures import warn_if_structure_kind_is_unknown
from guy4ase.gui.misc.structure_wait import (
    document_change_applied,
    wait_for_structure,
)


def _structure_open_filter() -> str:
    extensions = sorted(
        f"*.{extension}"
        for file_format in ioformats.values()
        for extension in (file_format.extensions or [])
    )
    return f"Structure Files ({' '.join(extensions)});;All Files (*)"


def _show_potential_warning(
    adoption: ResultAdoption, parent: QWidget
) -> None:
    if adoption.potential_error is None:
        return
    QMessageBox.warning(
        parent,
        "Potential Load Warning",
        "The result was loaded, but its potential could not be loaded:\n"
        f"{adoption.potential_error}",
    )


def choose_and_load_structure(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    parent: QWidget,
) -> bool:
    file_path, _ = QFileDialog.getOpenFileName(
        parent,
        "Load Structure File",
        "",
        _structure_open_filter(),
    )
    return bool(
        file_path
        and load_structure(controller, recent_files, file_path, parent)
    )


def load_structure(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    file_path: str | Path,
    parent: QWidget,
) -> bool:
    try:
        generation = controller.generation
        path = Path(file_path).resolve()
        atoms = ase_read(path)
        potential_path = (
            str(path) if path.suffix.lower() in {".pot", ".pot_new"} else None
        )
        change = wait_for_structure(
            parent,
            partial(
                controller.replace_structure,
                atoms,
                potential_path=potential_path,
                directory=str(path.parent),
                expected_generation=generation,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - backend readers vary
        QMessageBox.critical(
            parent, "Load Error", f"Failed to load structure:\n{exc}"
        )
        return False
    if isinstance(change, Busy) or not document_change_applied(parent, change):
        return False
    warn_if_structure_kind_is_unknown(atoms, parent)
    recent_files.remember("structure", file_path)
    return True


def choose_and_load_input_parameters(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    parent: QWidget,
) -> bool:
    file_path, _ = QFileDialog.getOpenFileName(
        parent,
        "Load Input File",
        "",
        "SPRKKR Input Files (*.inp *.in *.txt);;All Files (*)",
    )
    return bool(
        file_path
        and load_input_parameters(
            controller, recent_files, file_path, parent
        )
    )


def load_input_parameters(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    file_path: str | Path,
    parent: QWidget,
) -> bool:
    try:
        generation = controller.generation
        path = Path(file_path).resolve()
        parameters = InputParameters.from_file(path)
        change = controller.replace_input_parameters(
            parameters,
            directory=str(path.parent),
            expected_generation=generation,
        )
    except Exception as exc:  # noqa: BLE001 - parser errors are presented
        QMessageBox.critical(
            parent,
            "Load Error",
            f"Failed to load input parameters:\n{exc}",
        )
        return False
    if not document_change_applied(parent, change):
        return False
    recent_files.remember("input", file_path)
    return True


def choose_and_load_output(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    parent: QWidget,
) -> bool:
    file_path, _ = QFileDialog.getOpenFileName(
        parent,
        "Load SPRKKR Output File",
        "",
        "SPRKKR Output Files (*.out *.log *.txt);;All Files (*)",
    )
    return bool(
        file_path and load_output(controller, recent_files, file_path, parent)
    )


def load_output(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    file_path: str | Path,
    parent: QWidget,
) -> bool:
    try:
        generation = controller.generation
        loaded = load_result_file(file_path)
        adoption = wait_for_structure(
            parent,
            partial(
                controller.adopt_external_result,
                loaded,
                expected_generation=generation,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - backend readers vary
        QMessageBox.critical(
            parent,
            "Load Error",
            f"Failed to load SPRKKR output:\n{exc}",
        )
        return False
    if isinstance(adoption, Busy):
        return False
    if not adoption.adopted:
        document_change_applied(parent, DocumentChange.STALE)
        return False
    recent_files.remember("output", file_path)
    _show_potential_warning(adoption, parent)
    return True


def save_structure(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    parent: QWidget,
) -> bool:
    if controller.workspace.atoms is None:
        return False
    formats = {
        " ".join(f"*.{ext}" for ext in file_format.extensions): file_format.name
        for file_format in ioformats.values()
        if file_format.extensions
    }
    formats["*"] = "All Files"
    file_path, selected_filter = QFileDialog.getSaveFileName(
        parent,
        "Save Structure File",
        "",
        ";;".join(f"{name} ({patterns})" for patterns, name in formats.items()),
    )
    if not file_path:
        return False
    match = re.search(r"\*\.(\w+)", selected_filter)
    if match and not file_path.lower().endswith(f".{match.group(1)}"):
        file_path += f".{match.group(1)}"

    def write_structure() -> None:
        atoms = controller.workspace.atoms
        if atoms is None:
            raise ValueError("No structure is loaded.")
        ase_write(Path(file_path).resolve(), atoms)

    try:
        outcome = wait_for_structure(
            parent,
            partial(
                controller.structure_gate.try_call,
                "saving the structure",
                write_structure,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - backend writers vary
        QMessageBox.critical(
            parent, "Save Error", f"Failed to save structure:\n{exc}"
        )
        return False
    if isinstance(outcome, Busy):
        return False
    recent_files.remember("structure", file_path)
    return True


def save_input_parameters(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    parent: QWidget,
) -> bool:
    parameters = controller.workspace.input_parameters
    if parameters is None:
        return False
    file_path, _ = QFileDialog.getSaveFileName(
        parent,
        "Save Input File",
        "",
        "SPRKKR Input Files (*.inp *.in *.txt);;All Files (*)",
    )
    if not file_path:
        return False
    try:
        parameters.to_file(Path(file_path).resolve())
    except Exception as exc:  # noqa: BLE001 - backend writers vary
        QMessageBox.critical(
            parent,
            "Save Error",
            f"Failed to save input parameters:\n{exc}",
        )
        return False
    recent_files.remember("input", file_path)
    return True


def open_recent(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    kind: RecentKind,
    file_path: str | Path,
    parent: QWidget,
) -> bool:
    if not Path(file_path).exists():
        QMessageBox.warning(
            parent, "Missing File", f"File not found:\n{file_path}"
        )
        recent_files.forget(kind, file_path)
        return False
    loaders = {
        "structure": load_structure,
        "input": load_input_parameters,
        "output": load_output,
    }
    return loaders[kind](controller, recent_files, file_path, parent)
