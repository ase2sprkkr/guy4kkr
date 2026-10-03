"""Qt file orchestration around the workspace document controller."""
from __future__ import annotations

import re
from functools import partial
from pathlib import Path

from ase.io.formats import ioformats
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QWidget

from guy4ase.gui.application.recent_files import RecentFiles, RecentKind
from guy4ase.gui.application.workspace_controller import (
    ResultAdoption,
    WorkspaceController,
)
from guy4ase.gui.flows.structures import warn_if_structure_kind_is_unknown
from guy4ase.gui.misc.workspace_wait import wait_for_workspace


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
        outcome = wait_for_workspace(
            parent, partial(controller.load_structure, file_path)
        )
    except Exception as exc:  # noqa: BLE001 - backend readers vary
        QMessageBox.critical(
            parent, "Load Error", f"Failed to load structure:\n{exc}"
        )
        return False
    if not outcome.completed:
        return False
    atoms = outcome.value
    assert atoms is not None
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
        outcome = wait_for_workspace(
            parent, partial(controller.load_input_parameters, file_path)
        )
    except Exception as exc:  # noqa: BLE001 - parser errors are presented
        QMessageBox.critical(
            parent,
            "Load Error",
            f"Failed to load input parameters:\n{exc}",
        )
        return False
    if not outcome.completed:
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
        outcome = wait_for_workspace(
            parent, partial(controller.load_result, file_path)
        )
    except Exception as exc:  # noqa: BLE001 - backend readers vary
        QMessageBox.critical(
            parent,
            "Load Error",
            f"Failed to load SPRKKR output:\n{exc}",
        )
        return False
    if not outcome.completed:
        return False
    adoption = outcome.value
    assert adoption is not None
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
    try:
        outcome = wait_for_workspace(
            parent, partial(controller.save_structure, file_path)
        )
    except Exception as exc:  # noqa: BLE001 - backend writers vary
        QMessageBox.critical(
            parent, "Save Error", f"Failed to save structure:\n{exc}"
        )
        return False
    if not outcome.completed:
        return False
    recent_files.remember("structure", file_path)
    return True


def save_input_parameters(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    parent: QWidget,
) -> bool:
    if controller.workspace.input_parameters is None:
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
        outcome = wait_for_workspace(
            parent, partial(controller.save_input_parameters, file_path)
        )
    except Exception as exc:  # noqa: BLE001 - backend writers vary
        QMessageBox.critical(
            parent,
            "Save Error",
            f"Failed to save input parameters:\n{exc}",
        )
        return False
    if not outcome.completed:
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
