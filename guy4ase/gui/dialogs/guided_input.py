"""Side-navigation guided editor for SPR-KKR input parameters."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from ase2sprkkr.input_parameters.input_parameters import InputParameters
from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from guy4ase.gui.dialogs.expert_input import edit_input_parameters
from guy4ase.gui.dialogs.input_file import InputFileEditor
from guy4ase.gui.input_parameters.bindings import InputParameterPath, resolve_option
from guy4ase.gui.input_parameters.session import InputParametersSession
from guy4ase.gui.input_parameters.specs.registry import task_dialog_spec
from guy4ase.gui.input_parameters.specs.schema import (
    FieldPlacement,
    FieldRole,
    GroupSpec,
    PageSpec,
    PresentationContext,
    TaskDialogSpec,
)
from guy4ase.gui.input_parameters.tasks import new_parameters, prepare_parameters as _prepare_parameters
from guy4ase.gui.input_parameters.validation import validate_setup
from guy4ase.gui.misc.colors import blend as _blend
from guy4ase.gui.misc.resources import icon_path
from guy4ase.gui.widgets.input_parameters.parameter import EDITOR_WIDTH, ParameterEditor

LABEL_WIDTH = 245


def _is_2d(atoms: Any) -> bool:
    try:
        return not all(bool(value) for value in atoms.get_pbc())
    except Exception:
        return False


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
        self._validate_spec(prepared)
        self.session = InputParametersSession(prepared, self)
        self._primary_pages = self.spec.primary_pages()
        self._page_indexes = {page.id: index for index, page in enumerate(self.spec.pages)}
        self._editors: list[ParameterEditor] = []
        self._editors_by_path: dict[InputParameterPath, list[ParameterEditor]] = defaultdict(list)
        self._labels_by_path: dict[InputParameterPath, list[QLabel]] = defaultdict(list)
        self._errors: dict[InputParameterPath, str] = {}
        self._navigation_items: dict[str, QListWidgetItem] = {}
        self._navigation_labels: dict[str, QLabel] = {}
        self._navigation_tints: dict[str, QColor] = {}
        self._detail_toggles: dict[ParameterEditor, QToolButton] = {}
        self._field_widgets = {}
        self._group_views: list[tuple[GroupSpec, QGroupBox, QToolButton | None, QLabel | None]] = []
        self._group_notes_by_id: dict[str, QLabel] = {}
        self._editor_errors: dict[ParameterEditor, str] = {}
        self._rule_errors: dict[tuple[InputParameterPath, int | None], str] = {}

        self.setWindowTitle(self.spec.title)
        self.resize(980, 700)
        self._build_ui()
        self._connect_session()
        self._apply_presentation()
        self._update_all_statuses()

    def _validate_spec(self, parameters: InputParameters) -> None:
        """Check field ownership and option existence, not the input values' validity."""
        self.spec.primary_pages()
        for path in self.spec.all_paths():
            try:
                resolve_option(parameters, path)
            except (AttributeError, KeyError) as exc:
                raise ValueError(
                    f"The {self.task.upper()} guided-dialog specification refers to missing "
                    f"parameter {'.'.join(path)}."
                ) from exc

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        intro = QLabel(self.spec.intro or (
            "Configure the most useful task parameters. Quick setup mirrors a small selection "
            "from the detailed categories; all remaining parameters are available in Expert settings."
        ))
        intro.setWordWrap(True)
        root.addWidget(intro)

        directory_row = QHBoxLayout()
        directory_row.addWidget(QLabel("Working directory:"))
        self.directory_edit = QLineEdit(self.directory, self)
        self.directory_edit.setPlaceholderText("Select a calculation directory")
        directory_row.addWidget(self.directory_edit, 1)
        browse = QPushButton("Browse…", self)
        browse.clicked.connect(self._choose_directory)
        directory_row.addWidget(browse)
        root.addLayout(directory_row)

        body = QHBoxLayout()
        self.navigation = QListWidget(self)
        self.navigation.setObjectName("categoryNavigation")
        self.navigation.setMinimumWidth(220)
        self.navigation.setMaximumWidth(280)
        self.navigation.setSpacing(7)
        self.navigation.setStyleSheet(
            "QListWidget { border: 0; padding: 6px; background: palette(base); }"
            "QListWidget::item { border: 0; }"
        )
        self.pages = QStackedWidget(self)
        body.addWidget(self.navigation)
        body.addWidget(self.pages, 1)
        root.addLayout(body, 1)

        for page in self.spec.pages:
            self._add_page(page)
        self.navigation.currentRowChanged.connect(self._select_page_index)
        self.navigation.setCurrentRow(0)

        footer = QHBoxLayout()
        self.undo_button = QToolButton(self)
        self.undo_button.setText("Undo")
        self.undo_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.undo_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack))
        self.undo_button.clicked.connect(self.session.undo_stack.undo)
        footer.addWidget(self.undo_button)
        self.redo_button = QToolButton(self)
        self.redo_button.setText("Redo")
        self.redo_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.redo_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowForward))
        self.redo_button.clicked.connect(self.session.undo_stack.redo)
        footer.addWidget(self.redo_button)

        load = QPushButton("Load input…", self)
        load.clicked.connect(self._load_input)
        footer.addWidget(load)
        self.edit_input_button = QPushButton("Edit input file…", self)
        self.edit_input_button.clicked.connect(self._edit_input_file)
        footer.addWidget(self.edit_input_button)
        expert = QPushButton("Expert settings…", self)
        expert.clicked.connect(self._open_expert_settings)
        footer.addWidget(expert)
        footer.addStretch(1)

        self.previous_button = QPushButton("Previous", self)
        self.previous_button.clicked.connect(lambda: self.navigation.setCurrentRow(self.navigation.currentRow() - 1))
        footer.addWidget(self.previous_button)
        self.next_button = QPushButton("Next", self)
        self.next_button.clicked.connect(lambda: self.navigation.setCurrentRow(self.navigation.currentRow() + 1))
        footer.addWidget(self.next_button)
        cancel = QPushButton("Cancel", self)
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        calculate = QPushButton("Calculate", self)
        calculate.setDefault(True)
        calculate.setIcon(QIcon(str(icon_path("system-run.svg"))))
        calculate.clicked.connect(self._accept)
        footer.addWidget(calculate)
        root.addLayout(footer)

    def _add_page(self, page: PageSpec) -> None:
        item = QListWidgetItem(page.title)
        item.setData(Qt.ItemDataRole.UserRole, page.id)
        item.setSizeHint(QSize(0, 46))
        background = self.palette().window().color()
        tint = _blend(background, QColor(page.color), .36 if background.lightness() > 128 else .48)
        self._navigation_tints[page.id] = tint
        label = QLabel(page.title, self.navigation)
        label.setContentsMargins(12, 0, 8, 0)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        font = label.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 1)
        label.setFont(font)
        self.navigation.addItem(item)
        self.navigation.setItemWidget(item, label)
        self._navigation_items[page.id] = item
        self._navigation_labels[page.id] = label

        scroll = QScrollArea(self.pages)
        scroll.setWidgetResizable(True)
        content = QWidget(scroll)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)
        for group_spec in page.groups:
            group = QGroupBox("" if group_spec.collapsed else group_spec.title, content)
            if group_spec.id:
                group.setObjectName(group_spec.id)
            group_tint = _blend(background, QColor(page.color), .08 if background.lightness() > 128 else .16)
            border = _blend(self.palette().mid().color(), QColor(page.color), .25)
            group.setStyleSheet(
                "QGroupBox {"
                f"background-color: {group_tint.name()}; border: 1px solid {border.name()};"
                "border-radius: 5px; margin-top: 0.8em; padding: 8px;"
                "} QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px; }"
            )
            group_layout = QVBoxLayout(group)
            fields = QWidget(group)
            grid = QGridLayout(fields)
            grid.setContentsMargins(0, 0, 0, 0)
            toggle = None
            if group_spec.collapsed:
                toggle = QToolButton(group)
                toggle.setText(group_spec.title)
                toggle.setCheckable(True)
                toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
                toggle.setArrowType(Qt.ArrowType.RightArrow)
                toggle.setAutoRaise(True)
                toggle.toggled.connect(fields.setVisible)
                toggle.toggled.connect(lambda checked, button=toggle: button.setArrowType(
                    Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow))
                group_layout.addWidget(toggle)
                fields.hide()
            group_layout.addWidget(fields)
            paired = group_spec.layout == "paired"
            grid.setColumnMinimumWidth(0, EDITOR_WIDTH if paired else LABEL_WIDTH)
            grid.setColumnMinimumWidth(1, EDITOR_WIDTH)
            grid.setColumnStretch(0, 0)
            grid.setColumnStretch(1, 0)
            grid.setColumnStretch(2, 1)
            grid.setHorizontalSpacing(12)
            grid.setVerticalSpacing(7)
            for row, placement in enumerate(group_spec.fields):
                if paired:
                    # Two equally wide columns, labels above their controls.
                    self._add_field(grid, 2 * (row // 2), page, placement, column=row % 2)
                else:
                    self._add_field(grid, row, page, placement)
                if toggle is not None:
                    self._detail_toggles[self._editors[-1]] = toggle
            note = None
            if group_spec.note or group_spec.note_when:
                note = QLabel(group_spec.note or "", fields)
                note.setWordWrap(True)
                grid.addWidget(note, len(group_spec.fields), 0, 1, 3)
                if group_spec.id:
                    self._group_notes_by_id[group_spec.id] = note
            self._group_views.append((group_spec, group, toggle, note))
            layout.addWidget(group)
        layout.addStretch(1)
        scroll.setWidget(content)
        self.pages.addWidget(scroll)

    def _add_field(
        self,
        grid: QGridLayout,
        row: int,
        page: PageSpec,
        placement: FieldPlacement,
        column: int | None = None,
    ) -> None:
        editor = ParameterEditor(
            self.session,
            placement,
            page.id,
            atoms=self.atoms,
            parent=self,
        )
        editor.validationChanged.connect(
            lambda path, page_id, message, source=editor:
            self._editor_validation_changed(source, path, page_id, message)
        )
        editor.pathEditRequested.connect(lambda: self._edit_kpath(editor))
        self._editors.append(editor)
        for path in placement.paths:
            self._editors_by_path[path].append(editor)

        label = QLabel(placement.label)
        label.setFixedWidth(LABEL_WIDTH)
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        tooltip = editor.toolTip()
        label.setToolTip(tooltip)
        for path in placement.paths:
            self._labels_by_path[path].append(label)

        if column is not None:
            label.setFixedWidth(EDITOR_WIDTH)
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(label, row, column)
            grid.addWidget(editor, row + 1, column, alignment=Qt.AlignmentFlag.AlignTop)
        elif editor.full_width:
            block = QWidget()
            layout = QVBoxLayout(block)
            layout.setContentsMargins(0, 0, 0, 0)
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            layout.addWidget(label)
            layout.addWidget(editor)
            grid.addWidget(block, row, 0, 1, 3)
        else:
            grid.addWidget(label, row, 0)
            grid.addWidget(editor, row, 1)
        self._field_widgets[editor] = [label, editor]
        if placement.role is FieldRole.MIRROR:
            primary_id = self._primary_pages[placement.path]
            primary_title = self.spec.pages[self._page_indexes[primary_id]].title
            link_color = self.palette().highlight().color().name()
            details = QLabel(
                f'<a style="color: {link_color};" href="{primary_id}">{primary_title}</a>',
                self,
            )
            details.setTextFormat(Qt.TextFormat.RichText)
            details.setWordWrap(True)
            details.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            details.setOpenExternalLinks(False)
            details.setToolTip(f"Open the primary {primary_title} setting")
            details.linkActivated.connect(self.select_page)
            grid.addWidget(details, row, 2, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self._field_widgets[editor].append(details)
            label.setToolTip(f"{tooltip}\n\nPrimary location: {primary_title}")

    def _connect_session(self) -> None:
        stack = self.session.undo_stack
        stack.canUndoChanged.connect(self._update_history_buttons)
        stack.canRedoChanged.connect(self._update_history_buttons)
        stack.undoTextChanged.connect(self._update_history_buttons)
        stack.redoTextChanged.connect(self._update_history_buttons)
        stack.indexChanged.connect(self._update_history_buttons)
        self.session.parametersReplaced.connect(self._parameters_replaced)
        self.session.historyApplied.connect(self._history_applied)

    def _history_applied(self, paths, source_page, field_indices) -> None:
        """Defer history navigation until restoring the undo command has finished."""
        # Wait until QUndoStack finishes restoring the command before focus
        # changes can emit editingFinished from another control.
        QTimer.singleShot(0, lambda: self._reveal_history_field(paths, source_page, field_indices))

    def _reveal_history_field(self, paths, source_page, field_indices) -> None:
        """Reveal the source-page editor if available, otherwise its primary placement."""
        for path in paths:
            editors = self._editors_by_path.get(path, ())
            if not editors:
                continue
            matching = [editor for editor in editors if editor.placement.index == field_indices.get(path)]
            candidates = matching or list(editors)
            editor = next((item for item in candidates if item.page_id == source_page), None)
            if editor is None:
                editor = next((item for item in candidates
                               if item.page_id == self._primary_pages[path]), candidates[0])
            self.select_page(editor.page_id)
            if editor in self._detail_toggles:
                self._detail_toggles[editor].setChecked(True)
            scroll = self.pages.currentWidget()
            scroll.widget().layout().activate()
            scroll.ensureWidgetVisible(editor, 20, 30)
            editor.focus_for_history(path, field_indices.get(path))
            return

    def _parameters_replaced(self) -> None:
        self._editor_errors = {editor: editor._error for editor in self._editors if editor._error}
        self._apply_presentation()
        self._update_all_statuses()

    def _update_history_buttons(self, *_args: Any) -> None:
        stack = self.session.undo_stack
        self.undo_button.setEnabled(stack.canUndo())
        self.redo_button.setEnabled(stack.canRedo())
        self.undo_button.setToolTip(self.session.history_description(undo=True))
        self.redo_button.setToolTip(self.session.history_description(undo=False))

    def _update_all_statuses(self) -> None:
        changed = self.session.changed_paths(self.spec.all_paths())
        changed_labels = {label for path in changed for label in self._labels_by_path.get(path, ())}
        for path, labels in self._labels_by_path.items():
            for label in labels:
                font = label.font()
                font.setBold(label in changed_labels)
                label.setFont(font)

        for page in self.spec.pages:
            if page.quick:
                suffix = f"  ({len(changed)} changed)" if changed else ""
                if self._errors:
                    suffix += f"  ⚠ {len(self._errors)}"
            else:
                page_changed = any(
                    path in changed and self._primary_pages.get(path) == page.id
                    for path in self._primary_pages
                )
                page_errors = sum(
                    1 for path in self._errors if self._primary_pages.get(path) == page.id
                )
                suffix = "  •" if page_changed else ""
                if page_errors:
                    suffix += f"  ⚠ {page_errors}"
            text = page.title + suffix
            self._navigation_items[page.id].setText(text)
            self._navigation_labels[page.id].setText(text)
        self._update_history_buttons()

    def _editor_validation_changed(
        self,
        editor: ParameterEditor,
        path: InputParameterPath,
        _page_id: str,
        message: str,
    ) -> None:
        if message:
            self._editor_errors[editor] = message
        else:
            self._editor_errors.pop(editor, None)
        self._apply_presentation()
        self._update_all_statuses()

    @staticmethod
    def _missing(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        try:
            return len(value) == 0
        except TypeError:
            return False

    def _placement_value(self, placement: FieldPlacement, path: InputParameterPath) -> Any:
        value = self.session.value(path)
        index = placement.index if path == placement.path else None
        if index is None:
            return value
        try:
            return value[index]
        except (IndexError, TypeError):
            return None

    def _rebuild_errors(self) -> None:
        errors: dict[InputParameterPath, str] = {}
        for editor, message in self._editor_errors.items():
            if message:
                errors.setdefault(editor.path, message)
        for (path, _index), message in self._rule_errors.items():
            errors.setdefault(path, message)
        self._errors = errors

    def _update_field_tooltip(self, editor: ParameterEditor) -> None:
        widgets = self._field_widgets[editor]
        tooltip = editor.toolTip()
        if editor.placement.role is FieldRole.MIRROR:
            primary_id = self._primary_pages[editor.path]
            primary_title = self.spec.pages[self._page_indexes[primary_id]].title
            tooltip += f"\n\nPrimary location: {primary_title}"
        widgets[0].setToolTip(tooltip)

    def _apply_presentation(self) -> None:
        """Render declarative rules without modifying parameters or history."""
        # Rules receive a detached snapshot. Even an accidentally impure rule
        # therefore cannot mutate the session or create an untracked change.
        context = PresentationContext(self.session.result(), self.atoms)
        rule_errors: dict[tuple[InputParameterPath, int | None], str] = {}

        for spec, group, toggle, note in self._group_views:
            visible = spec.visible_when(context) if spec.visible_when else True
            group.setVisible(bool(visible))
            title = spec.title_when(context) if spec.title_when else spec.title
            if toggle is None:
                group.setTitle(title)
            else:
                toggle.setText(title)
            if note is not None:
                note.setText(spec.note_when(context) if spec.note_when else spec.note or "")

        for editor in self._editors:
            spec = editor.placement
            widgets = self._field_widgets[editor]
            visible = spec.visible_when(context) if spec.visible_when else True
            for widget in widgets:
                widget.setVisible(bool(visible))

            enabled = spec.enabled_when(context) if spec.enabled_when else True
            reason = spec.disabled_reason_when(context) if not enabled and spec.disabled_reason_when else None
            editor.set_parameter_enabled(bool(enabled), reason)
            widgets[0].setEnabled(bool(enabled))
            for widget in widgets[2:]:
                widget.setEnabled(bool(enabled))

            label = spec.label_when(context) if spec.label_when else spec.label
            widgets[0].setText(label)
            editor.setAccessibleName(label.rstrip(":"))
            help_text = spec.tooltip_when(context) if spec.tooltip_when else ""
            editor.set_presentation_help(help_text)
            self._update_field_tooltip(editor)

            if spec.required_when and spec.required_when(context):
                for path in spec.paths:
                    if not self._missing(self._placement_value(spec, path)):
                        continue
                    message = spec.required_message
                    if callable(message):
                        message = message(context)
                    rule_errors[(path, spec.index if path == spec.path else None)] = (
                        message or f"{'.'.join(path)} is required for the selected settings."
                    )

        self._rule_errors = rule_errors
        self._rebuild_errors()

    def group_note(self, group_id: str) -> QLabel:
        """Return a group's note widget for UI tests and accessibility checks."""
        return self._group_notes_by_id[group_id]

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
        highlight = self.palette().highlight().color().name()
        border = self.palette().mid().color().name()
        text = self.palette().text().color().name()
        for page_id, label in self._navigation_labels.items():
            active = self._page_indexes[page_id] == selected
            label.setStyleSheet(
                f"background-color: {self._navigation_tints[page_id].name()};"
                f"color: {text}; border: {3 if active else 1}px solid "
                f"{highlight if active else border}; border-radius: 6px;"
            )

    def editors_for(self, path: InputParameterPath) -> tuple[ParameterEditor, ...]:
        return tuple(self._editors_by_path.get(path, ()))

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
        if self._errors:
            path = next(iter(self._errors))
            self.select_page(self._primary_pages[path])
            editor = self._editors_by_path[path][-1]
            if editor in self._detail_toggles:
                self._detail_toggles[editor].setChecked(True)
            editor.control.setFocus()
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
        for path, page_id in self._primary_pages.items():
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
            candidate = self.session.result()
            result = edit_input_parameters(candidate, parent=self, show_changed_only=False, atoms=self.atoms)
            if result is not None:
                result = _prepare_parameters(result, self.task)
                self.session.replace_parameters(
                    result,
                    text="Apply expert settings",
                    source_page="expert",
                )
        except Exception as exc:
            QMessageBox.critical(self, "Expert Settings Error", str(exc))

    def _edit_kpath(self, editor) -> None:
        """Own modal path editing; widgets only request this action."""
        if self.atoms is None:
            QMessageBox.warning(self, 'K-path', 'A structure is required to edit the Brillouin-zone path.')
            return
        try:
            self.session.mutate(
                lambda parameters: parameters.TASK.k_path_gui(self.atoms, parent=self),
                text='Edit custom K-path', source_page=editor.page_id, path=editor.path)
        except Exception as error:
            QMessageBox.critical(self, 'K-path Error', str(error))

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
            loaded = _prepare_parameters(InputParameters.from_file(file_path), self.task)
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
