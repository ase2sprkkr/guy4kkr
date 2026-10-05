"""Side-navigation guided editor for SPR-KKR input parameters."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ase2sprkkr.input_parameters.input_parameters import InputParameters
from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from guy4ase.gui.dialogs.expert_input import edit_input_parameters_session
from guy4ase.gui.dialogs.input_file import InputFileEditor
from guy4ase.gui.input_parameters.bindings import InputParameterPath
from guy4ase.gui.input_parameters.session import create_input_parameters_session
from guy4ase.gui.input_parameters.specs.registry import task_dialog_spec
from guy4ase.gui.input_parameters.specs.schema import (
    PageSpec,
    TaskDialogSpec,
)
from guy4ase.gui.input_parameters.tasks import new_parameters
from guy4ase.gui.input_parameters.tasks import prepare_parameters as _prepare_parameters
from guy4ase.gui.input_parameters.validation import validate_setup
from guy4ase.gui.misc.resources import icon_path
from guy4ase.gui.style import (
    SPACE_LG,
    SPACE_MD,
    SPACE_SM,
    button_stylesheet,
    heading_font,
    navigation_tile_stylesheet,
    secondary_text_stylesheet,
)
from guy4ase.gui.widgets.input_parameters.form import GuidedFormRenderer
from guy4ase.gui.widgets.input_parameters.parameter import ParameterEditor


def _is_2d(atoms: Any) -> bool:
    try:
        return not all(bool(value) for value in atoms.get_pbc())
    except Exception:
        return False


@dataclass(frozen=True)
class NavigationView:
    """Widgets and color belonging to one page in the dialog navigation."""

    item: QListWidgetItem
    label: QLabel
    accent: QColor


class GuidedInputParametersDialog(QDialog):
    """A single guided dialog whose contents are supplied by a task spec."""

    def __init__(
        self,
        task: str,
        parameters: InputParameters,
        parent: QWidget | None = None,
        *,
        directory: str | None = None,
        atoms: Any = None,
    ) -> None:
        super().__init__(parent)
        self.task = task.lower()
        self.atoms = atoms
        self.directory = directory or ""
        self.spec: TaskDialogSpec = task_dialog_spec(self.task, is_2d=_is_2d(atoms))
        prepared = _prepare_parameters(parameters, self.task)
        self.session = create_input_parameters_session(prepared, self)
        self._page_indexes = {page.id: index for index, page in enumerate(self.spec.pages)}
        self._navigation: dict[str, NavigationView] = {}

        self.setWindowTitle(self.spec.title)
        self.resize(980, 700)
        self._build_ui()
        self._connect_session()
        self._update_all_statuses()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE_LG, SPACE_LG, SPACE_LG, SPACE_MD)
        root.setSpacing(SPACE_MD)
        title = QLabel(self.spec.title, self)
        title.setObjectName("guidedDialogTitle")
        title.setFont(heading_font(title.font(), "dialog"))
        root.addWidget(title)
        intro = QLabel(self.spec.intro or (
            "Configure the most useful task parameters. Quick setup mirrors a small selection "
            "from the detailed categories; all remaining parameters are available in Expert settings."
        ))
        intro.setWordWrap(True)
        intro.setObjectName("guidedDialogSubtitle")
        intro.setStyleSheet(secondary_text_stylesheet(self.palette()))
        root.addWidget(intro)

        directory_row = QHBoxLayout()
        directory_row.addWidget(QLabel("Working directory:"))
        self.directory_edit = QLineEdit(self.directory, self)
        self.directory_edit.setPlaceholderText("Select a calculation directory")
        directory_row.addWidget(self.directory_edit, 1)
        browse = QPushButton("Browse…", self)
        browse.setStyleSheet(button_stylesheet(self.palette()))
        browse.clicked.connect(self._choose_directory)
        directory_row.addWidget(browse)
        root.addLayout(directory_row)

        body = QHBoxLayout()
        self.navigation = QListWidget(self)
        self.navigation.setObjectName("categoryNavigation")
        self.navigation.setMinimumWidth(220)
        self.navigation.setMaximumWidth(280)
        self.navigation.setSpacing(SPACE_SM)
        self.navigation.setStyleSheet(
            f"QListWidget {{ border: 0; padding: {SPACE_SM}px; background: palette(base); }}"
            "QListWidget::item { border: 0; }"
        )
        self.pages = QStackedWidget(self)
        body.addWidget(self.navigation)
        body.addWidget(self.pages, 1)
        root.addLayout(body, 1)

        self.form = GuidedFormRenderer(
            self.session,
            self.spec,
            self.pages,
            atoms=self.atoms,
            select_page=self.select_page,
        )
        for page in self.spec.pages:
            self._add_navigation_page(page)
        self.form.statusChanged.connect(self._update_all_statuses)
        self.navigation.currentRowChanged.connect(self._select_page_index)
        self.navigation.setCurrentRow(0)

        footer = QHBoxLayout()
        self.undo_button = QToolButton(self)
        self.undo_button.setText("Undo")
        self.undo_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.undo_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack))
        self.undo_button.setStyleSheet(
            button_stylesheet(self.palette(), "QToolButton")
        )
        self.undo_button.clicked.connect(self.session.undo_stack.undo)
        footer.addWidget(self.undo_button)
        self.redo_button = QToolButton(self)
        self.redo_button.setText("Redo")
        self.redo_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.redo_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowForward))
        self.redo_button.setStyleSheet(
            button_stylesheet(self.palette(), "QToolButton")
        )
        self.redo_button.clicked.connect(self.session.undo_stack.redo)
        footer.addWidget(self.redo_button)

        load = QPushButton("Load input…", self)
        load.setStyleSheet(button_stylesheet(self.palette()))
        load.clicked.connect(self._load_input)
        footer.addWidget(load)
        self.edit_input_button = QPushButton("Edit input file…", self)
        self.edit_input_button.setStyleSheet(button_stylesheet(self.palette()))
        self.edit_input_button.clicked.connect(self._edit_input_file)
        footer.addWidget(self.edit_input_button)
        expert = QPushButton("Expert settings…", self)
        expert.setStyleSheet(button_stylesheet(self.palette()))
        expert.clicked.connect(self._open_expert_settings)
        footer.addWidget(expert)
        footer.addStretch(1)

        self.previous_button = QPushButton("Previous", self)
        self.previous_button.setStyleSheet(button_stylesheet(self.palette()))
        self.previous_button.clicked.connect(lambda: self.navigation.setCurrentRow(self.navigation.currentRow() - 1))
        footer.addWidget(self.previous_button)
        self.next_button = QPushButton("Next", self)
        self.next_button.setStyleSheet(button_stylesheet(self.palette()))
        self.next_button.clicked.connect(lambda: self.navigation.setCurrentRow(self.navigation.currentRow() + 1))
        footer.addWidget(self.next_button)
        cancel = QPushButton("Cancel", self)
        cancel.setStyleSheet(button_stylesheet(self.palette()))
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        calculate = QPushButton("Calculate", self)
        calculate.setStyleSheet(button_stylesheet(self.palette(), primary=True))
        calculate.setDefault(True)
        calculate.setIcon(QIcon(str(icon_path("system-run.svg"))))
        calculate.clicked.connect(self._accept)
        footer.addWidget(calculate)
        root.addLayout(footer)

    def _add_navigation_page(self, page: PageSpec) -> None:
        item = QListWidgetItem(page.title)
        item.setData(Qt.ItemDataRole.UserRole, page.id)
        item.setSizeHint(QSize(0, 46))
        accent = QColor(page.color)
        label = QLabel(page.title, self.navigation)
        label.setContentsMargins(SPACE_MD, 0, SPACE_SM, 0)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        font = label.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 1)
        label.setFont(font)
        self.navigation.addItem(item)
        self.navigation.setItemWidget(item, label)
        self._navigation[page.id] = NavigationView(item, label, accent)

    def _connect_session(self) -> None:
        stack = self.session.undo_stack
        stack.canUndoChanged.connect(self._update_history_buttons)
        stack.canRedoChanged.connect(self._update_history_buttons)
        stack.undoTextChanged.connect(self._update_history_buttons)
        stack.redoTextChanged.connect(self._update_history_buttons)
        stack.indexChanged.connect(self._update_history_buttons)
        self.session.historyApplied.connect(self._history_applied)

    def _history_applied(self, paths, source_page, field_indices) -> None:
        """Defer history navigation until restoring the undo command has finished."""
        # Wait until QUndoStack finishes restoring the command before focus
        # changes can emit editingFinished from another control.
        QTimer.singleShot(0, lambda: self._reveal_history_field(paths, source_page, field_indices))

    def _reveal_history_field(self, paths, source_page, field_indices) -> None:
        """Reveal the source-page editor if available, otherwise its primary placement."""
        result = self.form.history_view(paths, source_page, field_indices)
        if result is None:
            return
        view, path, index = result
        self.select_page(view.page_id)
        view.reveal(path, index)

    def _update_history_buttons(self, *_args: Any) -> None:
        stack = self.session.undo_stack
        self.undo_button.setEnabled(stack.canUndo())
        self.redo_button.setEnabled(stack.canRedo())
        self.undo_button.setToolTip(self.session.history_description(undo=True))
        self.redo_button.setToolTip(self.session.history_description(undo=False))

    def _update_all_statuses(self) -> None:
        changed = self.session.changed_paths(self.spec.all_paths())
        self.form.update_changed(changed)
        errors = self.form.errors

        for page in self.spec.pages:
            if page.quick:
                suffix = f"  ({len(changed)} changed)" if changed else ""
                if errors:
                    suffix += f"  ⚠ {len(errors)}"
            else:
                page_changed = any(
                    path in changed and self.form.primary_pages.get(path) == page.id
                    for path in self.form.primary_pages
                )
                page_errors = sum(
                    1 for path in errors if self.form.primary_pages.get(path) == page.id
                )
                suffix = "  •" if page_changed else ""
                if page_errors:
                    suffix += f"  ⚠ {page_errors}"
            text = page.title + suffix
            navigation = self._navigation[page.id]
            navigation.item.setText(text)
            navigation.label.setText(text)
        self._update_history_buttons()

    def group_note(self, group_id: str) -> QLabel:
        """Return a group's note widget for UI tests and accessibility checks."""
        return self.form.group_note(group_id)

    def _select_page_index(self, index: int) -> None:
        if 0 <= index < self.pages.count():
            self.pages.setCurrentIndex(index)
        self._update_navigation_styles()
        if not hasattr(self, "previous_button"):
            return
        self.previous_button.setEnabled(index > 0)
        self.next_button.setEnabled(0 <= index < self.pages.count() - 1)

    def select_page(self, page_id: str) -> None:
        self.navigation.setCurrentRow(self._page_indexes[page_id])

    def _update_navigation_styles(self) -> None:
        selected = self.navigation.currentRow()
        for page_id, navigation in self._navigation.items():
            active = self._page_indexes[page_id] == selected
            navigation.label.setStyleSheet(
                navigation_tile_stylesheet(
                    self.palette(), navigation.accent, selected=active
                )
            )

    def editors_for(self, path: InputParameterPath) -> tuple[ParameterEditor, ...]:
        return self.form.editors_for(path)

    def _commit_pending(self) -> bool:
        """Finish the focused edit and reveal errors; do not commit visual fallbacks.

        Other editors already commit on their own signals. This checks tracked
        widget errors, not whole-model validity or save-time required options.
        """
        focused = QApplication.focusWidget()
        if focused is not None:
            focused.clearFocus()
            QApplication.processEvents()
        # Editors commit on editingFinished (or immediately for discrete
        # controls).  Do not commit every displayed value here: optional values
        # may be represented by a visual fallback while still being unset in
        # InputParameters.
        errors = self.form.errors
        if errors:
            path = next(iter(errors))
            view = self.form.error_view(path)
            self.select_page(view.page_id)
            view.reveal_error()
            return False
        return True

    def _accept(self) -> None:
        if not self._commit_pending():
            QMessageBox.warning(self, "Invalid Settings", "Correct the highlighted value before calculating.")
            return
        try:
            validate_setup(self.session.working_parameters)
        except Exception as exc:
            self._show_model_error(exc)
            return
        if not self.directory_edit.text().strip() and not self._choose_directory():
            return
        self.directory = self.directory_edit.text().strip()
        self.accept()

    def _show_model_error(self, exception: Exception) -> None:
        message = str(exception)
        for path, page_id in self.form.primary_pages.items():
            if ".".join(path) in message:
                self.select_page(page_id)
                break
        QMessageBox.critical(self, "Invalid Settings", message)

    def _choose_directory(self) -> bool:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select Calculation Directory",
            self.directory_edit.text().strip(),
        )
        if not selected:
            return False
        self.directory = str(selected)
        self.directory_edit.setText(self.directory)
        return True

    def _open_expert_settings(self) -> None:
        """Edit a detached copy; accepting installs the result as one undoable change."""
        if not self._commit_pending():
            return
        try:
            temporary = self.session.fork()
            accepted = edit_input_parameters_session(
                temporary,
                parent=self,
                show_changed_only=False,
                atoms=self.atoms,
            )
            if accepted is not None:
                assert not isinstance(accepted, tuple)
                prepared = _prepare_parameters(accepted.result(), self.task)
                accepted.replace_parameters(
                    prepared,
                    text="Normalize expert settings",
                    source_page="expert",
                )
                self.session.replace_from_session(
                    accepted,
                    text="Apply expert settings",
                    source_page="expert",
                )
        except Exception as exc:
            QMessageBox.critical(self, "Expert Settings Error", str(exc))

    def _load_input(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load SPRKKR Input File",
            "",
            "SPRKKR Input Files (*.inp *.in *.txt);;All Files (*)",
        )
        if not file_path:
            return
        try:
            loaded = _prepare_parameters(
                InputParameters.from_file(Path(file_path).resolve()),
                self.task,
            )
            self.session.replace_parameters(
                loaded,
                text=f"Load {Path(file_path).name}",
                source_page="load",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Load Error", f"Failed to load input parameters:\n{exc}")

    def _edit_input_file(self) -> None:
        """Apply parsed input through a callback so failed application keeps the draft open."""
        # Parsing is also useful for repairing incomplete inputs; do not block
        # opening the text editor on save-time/required-field validation.
        focus = QApplication.focusWidget()
        if focus is not None:
            focus.clearFocus()
        try:
            def apply(parameters):
                self.session.replace_parameters(
                    _prepare_parameters(parameters, self.task),
                    text="Edit input file", source_page="input_file",
                )
            editor = InputFileEditor(self.session.result(), self, apply_parameters=apply)
            editor.exec()
        except Exception as exc:
            QMessageBox.critical(self, "Input File Error", str(exc))

    def result(self) -> tuple[InputParameters, str]:
        """Return a detached parameter copy and the selected calculation directory."""
        return self.session.result(), self.directory


def select_guided_input_parameters(
    task: str,
    parent: QWidget | None = None,
    *,
    directory: str | None = None,
    atoms: Any = None,
) -> tuple[InputParameters, str] | None:
    task = task.lower()
    spec = task_dialog_spec(task, is_2d=_is_2d(atoms))
    parameters = new_parameters(spec.parameter_task)
    dialog = GuidedInputParametersDialog(
        task,
        parameters,
        parent=parent,
        directory=directory,
        atoms=atoms,
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.result()
