"""Modal workflow for editing an isolated copy of ``InputParameters``."""
from __future__ import annotations

from typing import Any

from ase2sprkkr.input_parameters.input_parameters import InputParameters  # type: ignore
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from guy4ase.gui.dialogs.input_file import InputFileEditor
from guy4ase.gui.input_parameters.validation import validate_setup
from guy4ase.gui.widgets.input_parameters.expert_tree import ExpertInputTreeEditor


class InputParametersDialog(QDialog):
    """Own the expert editor's draft and modal accept/cancel workflow."""

    def __init__(
        self,
        params: InputParameters,
        parent: QWidget | None = None,
        *,
        show_changed_only: bool = False,
        calculate_mode: bool = False,
        directory: str | None = None,
        atoms: Any = None,
    ) -> None:
        super().__init__(parent)
        self._params = params.copy(copy_values=True)
        self._calculate_mode = calculate_mode
        self._directory = directory or ''

        self.setWindowTitle('Edit Input Parameters')
        self.resize(800, 600)
        root = QVBoxLayout(self)

        if calculate_mode:
            directory_row = QHBoxLayout()
            directory_row.addWidget(QLabel('Working directory:'))
            self._directory_edit = QLineEdit(self._directory, self)
            self._directory_edit.setPlaceholderText('Select a calculation directory')
            directory_row.addWidget(self._directory_edit, 1)
            choose_directory = QPushButton('Browse…', self)
            choose_directory.clicked.connect(self._choose_directory)
            directory_row.addWidget(choose_directory)
            root.addLayout(directory_row)
        else:
            self._directory_edit = None

        self.tree_editor = ExpertInputTreeEditor(
            lambda: self._params,
            atoms=atoms,
            show_changed_only=show_changed_only,
            parent=self,
        )
        root.addWidget(self.tree_editor, 1)

        self._validation_error = QLabel(self)
        self._validation_error.setWordWrap(True)
        self._validation_error.hide()
        root.addWidget(self._validation_error)
        self.tree_editor.validationChanged.connect(
            lambda _has_errors: self._validation_error.hide()
        )

        footer = QHBoxLayout()
        footer.addStretch(1)
        root.addLayout(footer)

        def add_button(text: str, slot: Any) -> QPushButton:
            button = QPushButton(text, self)
            button.clicked.connect(slot)
            footer.addWidget(button)
            return button

        self.load_btn = add_button('Load input…', self._load_input)
        self.edit_input_btn = add_button('Edit input file…', self._edit_input_file)
        self.cancel_btn = add_button('Cancel', self.reject)
        self.ok_btn = add_button('Calculate' if calculate_mode else 'OK', self._on_ok)

    def _load_input(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            'Load SPRKKR Input File',
            '',
            'SPRKKR Input Files (*.inp *.in *.txt);;All Files (*)',
        )
        if not file_path:
            return
        try:
            parameters = InputParameters.from_file(file_path)
            self._replace_parameters(parameters)
        except Exception as exc:  # noqa: BLE001 - parser errors are heterogeneous.
            QMessageBox.critical(
                self,
                'Load Error',
                f'Failed to load input parameters:\n{exc}',
            )
            return
        self.tree_editor.set_show_changed_only(True)

    def _replace_parameters(self, parameters: InputParameters) -> None:
        """Install a parsed draft atomically with respect to tree rebuilding."""
        previous = self._params
        self._params = parameters
        try:
            self.tree_editor.rebuild()
        except Exception:
            self._params = previous
            self.tree_editor.rebuild()
            raise

    def _edit_input_file(self) -> None:
        focus = QApplication.focusWidget()
        if focus is not None:
            focus.clearFocus()
        try:
            editor = InputFileEditor(
                self._params,
                self,
                apply_parameters=self._replace_parameters,
            )
            editor.exec()
        except Exception as exc:  # noqa: BLE001 - modal callback boundary.
            QMessageBox.critical(self, 'Input File Error', str(exc))

    def _choose_directory(self) -> bool:
        start = (
            self._directory_edit.text().strip()
            if self._directory_edit is not None
            else self._directory
        )
        selected = QFileDialog.getExistingDirectory(
            self,
            'Select Calculation Directory',
            start,
        )
        if not selected:
            return False
        self._directory = str(selected)
        if self._directory_edit is not None:
            self._directory_edit.setText(self._directory)
        return True

    def _on_ok(self) -> None:
        self._validation_error.hide()
        if not self.tree_editor.commit_pending():
            return
        try:
            validate_setup(self._params)
        except Exception as error:  # noqa: BLE001 - backend validation boundary.
            self._validation_error.setText(str(error))
            self._validation_error.show()
            return
        if self._calculate_mode:
            self._directory = (
                self._directory_edit.text().strip()
                if self._directory_edit is not None
                else ''
            )
            if not self._directory and not self._choose_directory():
                return
        self.accept()

    def result(self) -> InputParameters:
        return self._params

    def directory(self) -> str:
        if self._directory_edit is not None:
            return self._directory_edit.text().strip()
        return self._directory


def edit_input_parameters(
    params: InputParameters,
    parent: QWidget | None = None,
    *,
    show_changed_only: bool = False,
    calculate_mode: bool = False,
    directory: str | None = None,
    return_directory: bool = False,
    atoms: Any = None,
) -> Any:
    """Open the expert editor and return its accepted isolated draft."""
    dialog = InputParametersDialog(
        params,
        parent=parent,
        show_changed_only=show_changed_only,
        calculate_mode=calculate_mode,
        directory=directory,
        atoms=atoms,
    )
    code = dialog.exec()
    if code == QDialog.DialogCode.Accepted:
        if return_directory:
            return dialog.result(), dialog.directory()
        return dialog.result()
    return None


def select_input_parameters(
    atoms: Any,
    parent: QWidget | None = None,
    task: str = 'scf',
) -> InputParameters | None:
    """Create fresh parameters for a task and open the expert editor."""
    from importlib import import_module

    task_module = import_module(
        f'ase2sprkkr.input_parameters.definitions.{task.lower()}'
    )
    params_def = task_module.input_parameters()
    params = params_def.create_object()
    return edit_input_parameters(params, parent=parent, atoms=atoms)
