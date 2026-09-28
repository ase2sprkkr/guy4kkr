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
from guy4ase.gui.input_parameters.bsf import EK, bsf_mode
from guy4ase.gui.input_parameters.session import SPLIT_SWITCHES, InputParametersSession
from guy4ase.gui.input_parameters.specs.registry import task_dialog_spec
from guy4ase.gui.input_parameters.specs.schema import (
    FieldPlacement,
    FieldRole,
    PageSpec,
    TaskDialogSpec,
)
from guy4ase.gui.input_parameters.tasks import prepare_parameters as _prepare_parameters
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
        self._conditional_groups = []
        self._group_notes = {}

        self.setWindowTitle(self.spec.title)
        self.resize(980, 700)
        self._build_ui()
        self._connect_session()
        self._update_all_statuses()
        self._update_dynamic_state()

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
        intro = QLabel(
            "Configure the most useful task parameters. Quick setup mirrors a small selection "
            "from the detailed categories; all remaining parameters are available in Expert settings."
        )
        if self.task == "scf" and _is_2d(self.atoms):
            intro.setText(
                intro.text() + " One SCF run for a 2D system converges the bulk regions and then the interaction zone."
            )
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
            if group_spec.special and group_spec.special.startswith("bsf_"):
                self._conditional_groups.append((group_spec.special, group))
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
            paired = group_spec.special == "energy_grids"
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
            if group_spec.note:
                note = QLabel(group_spec.note, fields)
                note.setWordWrap(True)
                grid.addWidget(note, len(group_spec.fields), 0, 1, 3)
                if group_spec.special:
                    self._group_notes[group_spec.special] = note
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
        editor.validationChanged.connect(self._editor_validation_changed)
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
        elif placement.kind == "bsf_vectors":
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
            if editor.placement.kind == "kpath":
                editor.path_combo.setFocus(Qt.FocusReason.OtherFocusReason)
            elif editor.placement.kind == "bsf_mesh":
                editor.mode_combo.setFocus(Qt.FocusReason.OtherFocusReason)
            elif editor.placement.kind == "bsf_vectors":
                editor.control.focus_value(path, field_indices.get(path))
            else:
                editor.control.setFocus(Qt.FocusReason.OtherFocusReason)
            return

    def _parameters_replaced(self) -> None:
        self._errors = {editor.path: editor._error for editor in self._editors if editor._error}
        self._update_all_statuses()
        self._update_dynamic_state()

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

    def _editor_validation_changed(self, path: InputParameterPath, _page_id: str, message: str) -> None:
        if message:
            self._errors[path] = message
        else:
            self._errors.pop(path, None)
            if self.task == "bsf":
                # A syntactically valid unset value can still be required by
                # the selected BSF geometry (e.g. clearing K1).
                self._update_bsf_state()
        self._update_all_statuses()

    def _update_dynamic_state(self) -> None:
        """Update task-dependent visibility and enablement without clearing inactive values."""
        if self.task not in {"scf", "bsf"}:
            return
        value = lambda section, name: self.session.value((section, name))

        def enable(paths, enabled, reason=None):
            for path in paths:
                for editor in self._editors_by_path.get(path, ()):
                    editor.set_parameter_enabled(enabled, reason)
                    if reason is not None:
                        self._field_widgets[editor][0].setToolTip(editor.toolTip())
                for label in self._labels_by_path.get(path, ()):
                    label.setEnabled(enabled)

        if self.task == "scf":
            enable((("SCF", "ISTBRY"), ("SCF", "ITDEPT")), value("SCF", "ALG") == "BROYDEN2")
        cluster = bool(value("TAU", "CLUSTER") or value("TAU", "MOL")
                       or value("TAU", "BZINT") == "CLUSTER")
        representation = value("TAU", "KKRMODE") or "STANDARD"
        bzint = value("TAU", "BZINT")
        enable((("TAU", "BZINT"),), not bool(value("TAU", "CLUSTER") or value("TAU", "MOL")))
        enable(tuple(("TAU", name) for name in ("NKTAB", "NKTAB2D", "NKTAB3D")),
               not cluster and bzint == "POINTS")
        enable((("TAU", "NKMIN"), ("TAU", "NKMAX")), not cluster and bzint == "WEYL")
        enable((("TAU", "NSHLCLU"), ("TAU", "CLURAD")),
               cluster or representation in {"TB", "IMPURITY"},
               'Choose TB or IMPURITY under "KKR representation", enable "Use cluster mode" '
               'or "Molecular calculation", or select CLUSTER under "BZ integration" on this page.')
        cluster_reason = ('Enable "Use cluster mode" or "Molecular calculation", or select CLUSTER '
                          'under "BZ integration" on this page. TB / IMPURITY alone does not enable these fields.')
        enable(tuple(("TAU", name) for name in ("IQCNTR", "ITCNTR", "NLOUT")), cluster, cluster_reason)
        if cluster:
            cluster_note = "Cluster settings are active. Set the extent using shells or radius."
        elif representation in {"TB", "IMPURITY"}:
            cluster_note = (f"{representation}: shells and radius are active. Centre and angular cutoff are disabled. "
                            + cluster_reason)
        else:
            cluster_note = (f"Disabled: {representation} with BZ integration {bzint} does not use these cluster settings. "
                            'Enable "Use cluster mode" or "Molecular calculation", or select CLUSTER under '
                            '"BZ integration" above. Choose TB / IMPURITY under "KKR representation" '
                            'to enable shells and radius only.')
        self._group_notes["cluster_extent"].setText(cluster_note)
        enable(tuple(("STRCONST", name) for name in ("ETA", "RMAX", "GMAX")),
               not cluster and representation == "STANDARD")
        magnetic = not value("CONTROL", "NONMAG")
        enable(tuple(("MODE", name) for name in ("MDIR", "MALF", "MBET", "MGAM"))
               + (("SCF", "MSPIN"),), magnetic)
        op = value("MODE", "OP")
        beyond_dft = op not in (None, "NONE")
        enable((("MODE", "LOPT"), ("SCF", "MIXOP")), beyond_dft)
        enable(tuple(("MODE", name) for name in ("IEREF", "UMODE", "UEFF", "JEFF")), op == "LDA+U")
        enable((("MODE", "EREF"),), op == "LDA+U" and str(value("MODE", "IEREF")) == "-1")

        split = any(bool(self.session.value(path)) for path in SPLIT_SWITCHES)
        for path in (("ENERGY", "GRID"), ("ENERGY", "NE")):
            count = len(self.session.value(path))
            for editor in self._editors_by_path.get(path, ()):
                if editor.placement.index == 1:
                    editor.set_parameter_enabled(split)
                    self._field_widgets[editor][0].setEnabled(split)
            if split and count != 2:
                self._errors[path] = "A separate single-site contour requires two values. Set its mesh on the Energy page."
        if self.task == "bsf":
            self._update_bsf_state()
        self._update_all_statuses()

    def _update_bsf_state(self) -> None:
        ek = bsf_mode(self.session.working_parameters) == EK
        custom = self.session.value(("TASK", "KPATH")) is None
        for special, group in self._conditional_groups:
            group.setVisible({"bsf_ek": ek, "bsf_kk": not ek,
                              "bsf_vectors": not ek or custom}[special])
            if special == "bsf_vectors":
                group.setTitle("Custom path" if ek else "K–k plane")
        for editor, widgets in self._field_widgets.items():
            path = editor.path
            visible = True
            if path in (("TASK", "KPATH"), ("TASK", "NK"), ("TASK", "KE"),
                        ("ENERGY", "EMAX"), ("ENERGY", "EMAXEV")):
                visible = ek
            if path in tuple(("TASK", name) for name in ("NK1", "NK2", "K1", "K2")):
                visible = not ek
            for widget in widgets:
                widget.setVisible(visible)
            if path == ("TASK", "KA"):
                widgets[0].setText("Path segments (2π/a):" if ek else "Plane origin KA (2π/a):")
                editor.set_parameter_enabled(not ek or custom)
            elif path == ("TASK", "KE"):
                editor.set_parameter_enabled(ek and custom)
            elif path == ("ENERGY", "EMIN"):
                widgets[0].setText("Minimum energy:" if ek else "Fixed energy:")
        required = ("NK1", "NK2", "K1", "K2") if not ek else (("KA", "KE") if custom else ())
        for name in required:
            path = ("TASK", name)
            if self.session.value(path) is None:
                self._errors[path] = f"TASK.{name} is required for this BSF geometry."
        self._update_all_statuses()

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
    parameters = InputParameters.create(spec.parameter_task)
    if task == "bsf":
        # A new canonical BSF starts in KK mode (NE=1). Seed its required
        # plane with XBand's initial choices; never replace imported geometry.
        parameters.TASK.set({"NK1": 60, "NK2": 60, "K1": [1., 0., 0.], "K2": [0., 1., 0.]})
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
