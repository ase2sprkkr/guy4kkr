"""Modal workflow for editing an isolated copy of ``InputParameters``."""
from __future__ import annotations

from typing import Any

from ase2sprkkr.input_parameters.input_parameters import InputParameters  # type: ignore
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from guy4ase.gui.application.window_geometry import manage_window_geometry
from guy4ase.gui.flows.input_parameters import (
    choose_and_load_input_parameters,
    edit_input_parameters_file,
)
from guy4ase.gui.input_parameters.session import (
    InputParametersSession,
    create_input_parameters_session,
)
from guy4ase.gui.input_parameters.validation import validate_setup
from guy4ase.gui.widgets.input_parameters.expert_tree import ExpertInputTreeEditor


class InputParametersDialog(QDialog):
    """Own the expert editor's draft and modal accept/cancel workflow."""

    def __init__(
        self,
        parameters: InputParameters | InputParametersSession,
        parent: QWidget | None = None,
        *,
        show_changed_only: bool = False,
        calculate_mode: bool = False,
        directory: str | None = None,
        atoms: Any = None,
    ) -> None:
        super().__init__(parent)
        if isinstance(parameters, InputParametersSession):
            # The caller owns an explicitly supplied session and may need it
            # after this dialog has closed (Guided applies it on Accept).
            self.session = parameters
        else:
            self.session = create_input_parameters_session(parameters, self)
        self._calculate_mode = calculate_mode
        self._directory = directory or ''

        self.setWindowTitle('Edit Input Parameters')
        manage_window_geometry(
            self,
            "expert-input",
            default_size=(1200, 750),
            default_maximized=True,
        )
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
            self.session,
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
        if choose_and_load_input_parameters(self.session, self):
            self.tree_editor.set_show_changed_only(True)

    def _edit_input_file(self) -> None:
        edit_input_parameters_file(self.session, self)

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
            validate_setup(self.session.working_parameters)
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
        return self.session.result()

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
    session = create_input_parameters_session(params)
    accepted = edit_input_parameters_session(
        session,
        parent=parent,
        show_changed_only=show_changed_only,
        calculate_mode=calculate_mode,
        directory=directory,
        return_directory=return_directory,
        atoms=atoms,
    )
    if accepted is None:
        return None
    if return_directory:
        return accepted[0].result(), accepted[1]
    return accepted.result()


def edit_input_parameters_session(
    session: InputParametersSession,
    parent: QWidget | None = None,
    *,
    show_changed_only: bool = False,
    calculate_mode: bool = False,
    directory: str | None = None,
    return_directory: bool = False,
    atoms: Any = None,
) -> InputParametersSession | tuple[InputParametersSession, str] | None:
    """Run Expert over an independent session and return it only on Accept."""
    dialog = InputParametersDialog(
        session,
        parent=parent,
        show_changed_only=show_changed_only,
        calculate_mode=calculate_mode,
        directory=directory,
        atoms=atoms,
    )
    code = dialog.exec()
    if code == QDialog.DialogCode.Accepted:
        if return_directory:
            return session, dialog.directory()
        return session
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
