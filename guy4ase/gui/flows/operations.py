"""Shared Qt orchestration which is independent of either main window."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ase.io import read as ase_read
from ase2sprkkr.input_parameters.input_parameters import InputParameters
from ase2sprkkr.outputs.task_result import TaskResult
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QWidget

from guy4ase.gui.application.recent_files import RecentFiles, RecentKind
from guy4ase.gui.application.workspace_controller import (
    ResultArtifacts,
    WorkspaceController,
)
from guy4ase.gui.dialogs.guided_input import select_guided_input_parameters
from guy4ase.gui.dialogs.object_view import show_readonly_object_dialog
from guy4ase.gui.dialogs.run_calculation import SprkkrRunWindow
from guy4ase.gui.dialogs.structures.build_2d import select_build_2d_structure
from guy4ase.gui.dialogs.structures.database import select_structure_prototype
from guy4ase.gui.dialogs.structures.element_assignment import select_site_elements
from guy4ase.gui.dialogs.structures.online_database import select_online_structure
from guy4ase.gui.dialogs.structures.spacegroup_selector import (
    select_spacegroup,
    select_spacegroup_from_prototype,
)
from guy4ase.gui.misc.dialog_flow import chain_dialogs


class GuiOperations(QObject):
    """Run shared modal workflows and apply their results to the controller.

    This object owns orchestration and transient dialog lifetimes, but no
    presentation widgets. Each operation receives the window which should own
    any modal UI it opens.
    """

    recentFilesChanged = pyqtSignal()

    def __init__(
        self,
        controller: WorkspaceController,
        recent_files: RecentFiles,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.workspace = controller.workspace
        self.recent_files = recent_files
        self._run_windows: list[SprkkrRunWindow] = []
        self._result_dialogs: list[QWidget] = []

    def remember_recent(
        self, kind: RecentKind, file_path: str | Path
    ) -> None:
        self.recent_files.remember(kind, file_path)
        self.recentFilesChanged.emit()

    def create_structure(self, parent: QWidget) -> Any | None:
        atoms = chain_dialogs(
            select_spacegroup,
            select_site_elements,
            back=True,
            kwargs={"parent": parent},
        )
        if atoms is not None:
            self.controller.set_structure(atoms)
        return atoms

    def create_structure_from_database(self, parent: QWidget) -> Any | None:
        atoms = chain_dialogs(
            select_structure_prototype,
            select_spacegroup_from_prototype,
            select_site_elements,
            back=True,
            kwargs={"parent": parent},
        )
        if atoms is not None:
            self.controller.set_structure(atoms)
        return atoms

    def download_structure(self, parent: QWidget) -> Any | None:
        atoms = select_online_structure(parent=parent)
        if atoms is not None:
            self.controller.set_structure(atoms)
        return atoms

    def choose_structure(self, parent: QWidget) -> bool:
        from ase.io.formats import ioformats

        extensions = sorted(
            f"*.{extension}"
            for file_format in ioformats.values()
            for extension in (file_format.extensions or [])
        )
        file_path, _ = QFileDialog.getOpenFileName(
            parent,
            "Load Structure File",
            "",
            f"Structure Files ({' '.join(extensions)});;All Files (*)",
        )
        return bool(file_path and self.load_structure(file_path, parent))

    def load_structure(self, file_path: str | Path, parent: QWidget) -> bool:
        try:
            atoms = ase_read(file_path)
            resolved = Path(file_path).resolve()
            is_potential = resolved.suffix.lower() in {".pot", ".pot_new"}
            self.controller.set_directory(str(resolved.parent))
            self.controller.set_structure(
                atoms,
                potential_path=str(resolved) if is_potential else None,
            )
            self.remember_recent("structure", file_path)
        except Exception as exc:  # noqa: BLE001 - backend readers vary
            QMessageBox.critical(
                parent, "Load Error", f"Failed to load structure:\n{exc}"
            )
            return False
        return True

    def load_input(self, file_path: str | Path, parent: QWidget) -> bool:
        try:
            parameters = InputParameters.from_file(file_path)
        except Exception as exc:  # noqa: BLE001 - parser errors are presented
            QMessageBox.critical(
                parent,
                "Load Error",
                f"Failed to load input parameters:\n{exc}",
            )
            return False
        self.controller.set_input_parameters(parameters)
        self.remember_recent("input", file_path)
        return True

    def choose_output(self, parent: QWidget) -> bool:
        file_path, _ = QFileDialog.getOpenFileName(
            parent,
            "Load SPRKKR Output File",
            "",
            "SPRKKR Output Files (*.out *.log *.txt);;All Files (*)",
        )
        return bool(file_path and self.load_output(file_path, parent))

    def load_output(self, file_path: str | Path, parent: QWidget) -> bool:
        try:
            result = TaskResult.from_file(file_path)
            self.adopt_result(
                result,
                parent,
                fallback_directory=Path(file_path).resolve().parent,
                recent_output=file_path,
                potential_error_prefix=(
                    "Failed to load structure from potential"
                ),
            )
        except Exception as exc:  # noqa: BLE001 - backend readers vary
            QMessageBox.critical(
                parent,
                "Load Error",
                f"Failed to load SPRKKR output:\n{exc}",
            )
            return False
        return True

    def adopt_result(
        self,
        result: Any,
        parent: QWidget,
        *,
        fallback_directory: str | Path | None = None,
        recent_output: str | Path | None = None,
        potential_error_prefix: str = (
            "The result was loaded, but its potential could not be loaded"
        ),
    ) -> ResultArtifacts:
        """Adopt one result and apply its UI-facing artifact side effects.

        ``WorkspaceController`` owns result interpretation and document
        mutation. This method adds the orchestration shared by results opened
        from disk and results returned by a calculation: recent-file history,
        potential loading and warning presentation.

        ``recent_output`` overrides the discovered output path so that a file
        explicitly selected by the user is the one retained in history.
        """
        artifacts = self.controller.adopt_result(
            result,
            fallback_directory=fallback_directory,
        )
        output_path = (
            recent_output
            if recent_output is not None
            else artifacts.output_path
        )
        if output_path is not None:
            self.remember_recent("output", output_path)
        self._load_result_potential(
            artifacts.potential_path,
            parent,
            potential_error_prefix,
        )
        return artifacts

    def open_recent(
        self, kind: RecentKind, file_path: str, parent: QWidget
    ) -> bool:
        if not Path(file_path).exists():
            QMessageBox.warning(
                parent, "Missing File", f"File not found:\n{file_path}"
            )
            self.recent_files.forget(kind, file_path)
            self.recentFilesChanged.emit()
            return False
        loaders = {
            "structure": self.load_structure,
            "input": self.load_input,
            "output": self.load_output,
        }
        return loaders[kind](file_path, parent)

    def build_2d_structure(
        self, parent: QWidget, *, surface_mode: bool = False
    ) -> Any | None:
        if self.workspace.atoms is None:
            QMessageBox.information(
                parent, "No Structure", "Load or create a structure first."
            )
            return None
        try:
            atoms = select_build_2d_structure(
                self.workspace.atoms,
                parent=parent,
                surface_mode=surface_mode,
            )
            if atoms is not None:
                self.controller.set_structure(atoms)
            return atoms
        except Exception as exc:  # noqa: BLE001 - dialog/backend boundary
            QMessageBox.critical(
                parent,
                "Build 2D Structure Error",
                f"Failed to build 2D structure:\n{exc}",
            )
            return None

    def prepare_guided_task(
        self, task: str, parent: QWidget
    ) -> SprkkrRunWindow | None:
        if self.workspace.atoms is None:
            QMessageBox.information(
                parent, "No Structure", "Load or create a structure first."
            )
            return None
        selection = select_guided_input_parameters(
            task,
            parent=parent,
            directory=self.workspace.directory,
            atoms=self.workspace.atoms,
        )
        if selection is None:
            return None
        parameters, directory = selection
        self.controller.set_directory(directory)
        self.controller.set_input_parameters(parameters)
        return self.run_calculation(parent)

    def run_calculation(self, parent: QWidget) -> SprkkrRunWindow | None:
        if (
            self.workspace.atoms is None
            or self.workspace.input_parameters is None
            or not self.workspace.directory
        ):
            return None
        window = SprkkrRunWindow(
            atoms=self.workspace.atoms,
            input_parameters=self.workspace.input_parameters,
            directory=self.workspace.directory,
            parent=parent,
            on_finished=lambda result: self.adopt_result(result, parent),
        )
        self._run_windows.append(window)
        window.destroyed.connect(
            lambda _obj=None, item=window: self._forget_run_window(item)
        )
        window.show()
        return window

    def _load_result_potential(
        self,
        potential_path: Path | None,
        parent: QWidget,
        error_prefix: str,
    ) -> None:
        if potential_path is None or not potential_path.is_file():
            return
        try:
            from ase2sprkkr.potentials.potentials import Potential

            resolved = str(potential_path.resolve())
            atoms = Potential.from_file(resolved).atoms
            self.controller.set_structure(atoms, potential_path=resolved)
        except Exception as exc:  # noqa: BLE001 - backend reader boundary
            QMessageBox.warning(parent, "Potential Load Warning", f"{error_prefix}:\n{exc}")

    def execute_output_value_action(
        self,
        value: Any,
        action: str,
        parent: QWidget,
    ) -> None:
        try:
            if action in {"edit", "data"}:
                payload = value.data() if action == "data" else value()
                title = getattr(value, "display_name", value.name)
                dialog = show_readonly_object_dialog(
                    payload, title=f"View {title}", parent=parent
                )
                self._result_dialogs.append(dialog)
                dialog.destroyed.connect(
                    lambda _obj=None, item=dialog:
                    self._forget_result_dialog(item)
                )
                return
            method = getattr(value, action, None)
            method()
        except Exception as exc:  # noqa: BLE001 - plugin action boundary
            QMessageBox.critical(
                parent,
                "Action Error",
                f"Failed to execute action '{action}':\n{exc}",
            )

    def _forget_run_window(self, window: SprkkrRunWindow) -> None:
        self._run_windows = [item for item in self._run_windows if item is not window]

    def _forget_result_dialog(self, dialog: QWidget) -> None:
        self._result_dialogs = [
            item for item in self._result_dialogs if item is not dialog
        ]
