"""Direct recursive Qt renderer for Expert input values."""
from __future__ import annotations

from collections.abc import Mapping, Sequence as AbcSequence
from dataclasses import replace
from typing import Any

import numpy as np
from ase2sprkkr.common.configuration_containers import Section
from ase2sprkkr.common.grammar_types import Array, SetOf, String, Table
from ase2sprkkr.common.grammar_types import Sequence as GrammarSequence
from PyQt6 import sip
from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyle,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from guy4ase.gui.input_parameters.bindings import InputParameterPath, resolve_option
from guy4ase.gui.input_parameters.expert_fields import (
    ExpertFieldSpec,
    applicable_expert_fields,
)
from guy4ase.gui.input_parameters.field_binding import (
    DraftFieldBinding,
    FieldValue,
    FixedArrayDraft,
    SessionFieldBinding,
    array_item_binding,
    mapping_value_binding,
    sequence_item_binding,
    sequence_value_binding,
    table_cell_binding,
)
from guy4ase.gui.input_parameters.session import InputParametersSession
from guy4ase.gui.input_parameters.specs.schema import FieldPlacement
from guy4ase.gui.widgets.input_parameters.modal_editor import ExpertFieldEditorDialog
from guy4ase.gui.widgets.input_parameters.registry import create_editor
from guy4ase.gui.widgets.input_parameters.value_editor import ParameterValueEditor


def _items(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, AbcSequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return [value]


def _option_value(option: Any) -> Any:
    try:
        return option.get()
    except Exception:  # noqa: BLE001 - generated getters can fail on incomplete data.
        return getattr(option, "_value", None)


def _all_values(option: Any) -> Any:
    try:
        return option(all_values=True)
    except Exception:  # noqa: BLE001 - generated getters can fail on incomplete data.
        return getattr(option, "_value", None)


def _structure_key(kind: str, shape: Any) -> tuple[Any, ...]:
    return kind, shape


def _sequence_values(grammar: GrammarSequence, value: Any) -> list[Any] | None:
    """Return a complete Sequence value, or None while it needs whole-value editing."""
    if value is None:
        return None
    try:
        grammar.validate(value)
    except (TypeError, ValueError):
        return None
    return _items(value)


class ExpertInputTreeEditor(QWidget):
    """Render grammar values directly into the single QTreeWidget presentation tree."""

    validationChanged = pyqtSignal(bool)
    _CHANGED_ROLE = Qt.ItemDataRole.UserRole
    _RELATED_PATHS_ROLE = Qt.ItemDataRole.UserRole + 1
    _VALUE_EDITOR_ROLE = Qt.ItemDataRole.UserRole + 2
    _COLLAPSE_ROLE = Qt.ItemDataRole.UserRole + 3
    _OPTION_PATH_ROLE = Qt.ItemDataRole.UserRole + 4
    _STRUCTURAL_KEY_ROLE = Qt.ItemDataRole.UserRole + 5
    _DRAFT_ROLE = Qt.ItemDataRole.UserRole + 6
    _APPEND_ROLE = Qt.ItemDataRole.UserRole + 7

    def __init__(
        self,
        session: InputParametersSession,
        *,
        atoms: Any = None,
        show_changed_only: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self._atoms = atoms
        self._option_rows: dict[InputParameterPath, QTreeWidgetItem] = {}
        self._dependency_editors: dict[int, tuple[Any, QTreeWidgetItem, set]] = {}
        self._editor_errors: dict[int, tuple[QTreeWidgetItem, str, str]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.addWidget(QLabel("Search:"))
        self.filter_edit = QLineEdit(self)
        self.filter_edit.setPlaceholderText("Filter by name…")
        header.addWidget(self.filter_edit, 1)
        clear_button = QPushButton("Clear", self)
        header.addWidget(clear_button)
        self.changed_only_checkbox = QCheckBox("Show changed only", self)
        header.addWidget(self.changed_only_checkbox)
        header.addStretch(1)
        expand_button = QPushButton("Expand all", self)
        collapse_button = QPushButton("Collapse all", self)
        header.addWidget(expand_button)
        header.addWidget(collapse_button)
        layout.addLayout(header)

        self.tree = QTreeWidget(self)
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Name", "Type", "Value", "", "Comment"])
        self.tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.tree.setColumnWidth(0, 300)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.tree, 1)

        self.error_label = QLabel(self)
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)

        self.filter_edit.textChanged.connect(self.apply_filter)
        clear_button.clicked.connect(self.clear_filter)
        self.changed_only_checkbox.toggled.connect(
            lambda _checked: self.apply_filter(self.filter_edit.text())
        )
        expand_button.clicked.connect(self.tree.expandAll)
        collapse_button.clicked.connect(self.tree.collapseAll)
        self.changed_only_checkbox.setChecked(show_changed_only)
        self.session.editApplied.connect(self._session_changed)
        self.rebuild()

    @property
    def parameters(self) -> Any:
        return self.session.working_parameters

    @property
    def has_errors(self) -> bool:
        return bool(self._editor_errors)

    @property
    def error_text(self) -> str:
        return self.error_label.text()

    def set_show_changed_only(self, enabled: bool) -> None:
        self.changed_only_checkbox.setChecked(enabled)

    def clear_filter(self) -> None:
        self.filter_edit.clear()
        self.filter_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def apply_filter(self, text: str) -> None:
        needle = (text or "").strip().lower()
        changed_only = self.changed_only_checkbox.isChecked()

        def visit(item: QTreeWidgetItem) -> bool:
            matches = not needle or needle in (item.text(0) or "").lower()
            changed = bool(item.data(0, self._CHANGED_ROLE))
            child_visible = any(visit(item.child(i)) for i in range(item.childCount()))
            visible = (matches and (not changed_only or changed or child_visible)) or child_visible
            item.setHidden(not visible)
            return visible

        for index in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(index))

    def commit_pending(self) -> bool:
        focus = QApplication.focusWidget()
        if focus is not None:
            focus.clearFocus()
        for item, editor in self._editor_widgets():
            if editor is None or sip.isdeleted(editor) or sip.isdeleted(item):
                continue
            if not editor.commit():
                self.filter_edit.clear()
                self.changed_only_checkbox.setChecked(False)
                parent = item.parent()
                while parent is not None:
                    parent.setExpanded(True)
                    parent = parent.parent()
                self.tree.scrollToItem(item)
                editor.setFocus()
                return False
        return not self.has_errors

    def rebuild(self) -> None:
        self._clear_registries()
        self._field_specs = applicable_expert_fields(self.parameters)
        self._suppressed_paths = frozenset(
            path for spec in self._field_specs.values() for path in spec.related_paths
        )
        self.tree.clear()
        self._build_section(self.parameters)
        self.tree.expandAll()
        self._collapse_groups()
        self.apply_filter(self.filter_edit.text())
        self._refresh_editor_errors()

    def _session_changed(self, paths, reset: bool) -> None:
        if reset:
            self.rebuild()
            return
        changed_paths = tuple(paths)
        QTimer.singleShot(0, lambda: self._apply_session_changes(changed_paths))

    def _apply_session_changes(self, changed_paths: tuple[InputParameterPath, ...]) -> None:
        refreshed: set[int] = set()
        for path in changed_paths:
            item = self._option_rows.get(path)
            if item is None or sip.isdeleted(item):
                continue
            option = resolve_option(self.parameters, path)
            key = self._structural_key(option, self._field_specs.get(path))
            old_key = item.data(0, self._STRUCTURAL_KEY_ROLE)
            if key != old_key or self._contains_draft(item):
                append_container = self._focused_append_container_path(item)
                self._render_option(option, path, item.parent(), item, self._field_specs.get(path))
                self._collapse_groups(item)
                if append_container is not None:
                    QTimer.singleShot(
                        0, lambda current=item, path=append_container: self._focus_append_editor(current, path)
                    )
            else:
                self._refresh_subtree(item, refreshed)
            self._update_changed_style(option, item, refresh_filter=False)

        self._prune_registries()
        for editor, item, dependencies, placement in tuple(self._dependency_editors.values()):
            if (
                id(editor) not in refreshed
                and not sip.isdeleted(editor)
                and not sip.isdeleted(item)
                and dependencies.intersection(changed_paths)
            ):
                editor.refresh()
                self._apply_placement_presentation(editor, placement)
                refreshed.add(id(editor))
                path = item.data(0, self._OPTION_PATH_ROLE)
                if path:
                    try:
                        self._update_changed_style(resolve_option(self.parameters, path), item, refresh_filter=False)
                    except (AttributeError, KeyError):
                        pass
        self.apply_filter(self.filter_edit.text())

    def _structural_key(self, option: Any, spec: ExpertFieldSpec | None) -> Any:
        if spec is not None and spec.small_editor is None:
            return _structure_key("leaf", spec.editor)
        inline_editor = spec.small_editor if spec is not None else "auto"
        if option._definition.is_repeated:
            return self._repeated_structure_key(option, inline_editor)
        return self._value_structure_key(
            option._definition.grammar_type,
            _option_value(option),
            inline_editor,
        )

    def _repeated_structure_key(self, option: Any, editor: str) -> Any:
        grammar = option._definition.type
        values = _all_values(option)
        repeated = option._definition.is_repeated
        if repeated.is_dict:
            mapping = values if isinstance(values, Mapping) else {}
            entries = [("def", mapping.get("def", option.default_value))]
            entries.extend(
                (key, mapping[key])
                for key in sorted(
                    (key for key in mapping if key != "def"),
                    key=lambda key: (not isinstance(key, int), key),
                )
            )
            return _structure_key(
                "repeated-dict",
                tuple(
                    (key, self._value_structure_key(grammar, value, editor, allow_append=False))
                    for key, value in entries
                ),
            )
        sequence = _items(values)
        return _structure_key(
            "repeated-sequence",
            tuple(self._value_structure_key(grammar, value, editor) for value in sequence),
        )

    def _value_structure_key(
        self,
        grammar: Any,
        value: Any,
        editor: str = "auto",
        *,
        allow_append: bool = True,
    ) -> Any:
        """Describe rendered shape recursively; scalar model values never enter the key."""
        if editor != "auto":
            return _structure_key("leaf", editor)
        if isinstance(grammar, (Array, SetOf)) and getattr(grammar, "array_access", False):
            values = _items(value)
            minimum = getattr(grammar, "min_length", None)
            maximum = getattr(grammar, "max_length", None)
            fixed = minimum is not None and minimum == maximum
            display = list(values)
            if fixed:
                display.extend([None] * max(0, minimum - len(display)))
            child_keys = tuple(
                self._value_structure_key(grammar.type, child)
                for child in display
            )
            append = allow_append and not fixed and (maximum is None or len(values) < maximum)
            incomplete = fixed and any(child is None for child in display)
            return _structure_key(
                "array",
                (len(display), fixed, append, incomplete, child_keys),
            )
        if isinstance(grammar, GrammarSequence):
            values = _sequence_values(grammar, value)
            if values is None:
                return _structure_key("sequence-leaf", None)
            children = tuple(
                self._value_structure_key(
                    child_type, values[index],
                )
                for index, child_type in enumerate(grammar.types)
            )
            return _structure_key("sequence", children)
        if isinstance(grammar, Table):
            return self._table_value_structure_key(grammar, value)
        return None

    def _table_value_structure_key(self, grammar: Table, value: Any) -> Any:
        if value is None:
            return _structure_key("table", None)
        try:
            array = value if isinstance(value, np.ndarray) else grammar.convert(value)
        except Exception:  # noqa: BLE001 - preserve opaque fallback.
            return _structure_key("table", "opaque")
        if not isinstance(array, np.ndarray):
            return _structure_key("table", "opaque")
        sequence = grammar.sequence
        rows = []
        if array.dtype.names:
            names = list(array.dtype.names)
            for row in range(len(array)):
                rows.append(tuple(
                    self._value_structure_key(
                        sequence.types[index] if index < len(sequence.types) else String(),
                        array[row][name],
                    )
                    for index, name in enumerate(names)
                ))
        else:
            data = np.asarray(array)
            if data.ndim == 1 and len(sequence.types) == 1:
                data = data.reshape((-1, 1))
            if data.ndim != 2:
                return _structure_key("table", (data.shape, "opaque"))
            for row in range(data.shape[0]):
                rows.append(tuple(
                    self._value_structure_key(
                        sequence.types[column] if column < len(sequence.types) else String(),
                        data[row, column],
                    )
                    for column in range(data.shape[1])
                ))
        return _structure_key("table", (array.shape, array.dtype.names, tuple(rows)))

    def _refresh_subtree(self, item: QTreeWidgetItem, refreshed: set[int]) -> None:
        editor = self.tree.itemWidget(item, 2)
        if isinstance(editor, ParameterValueEditor) and id(editor) not in refreshed:
            editor.refresh()
            refreshed.add(id(editor))
        for index in range(item.childCount()):
            self._refresh_subtree(item.child(index), refreshed)

    def _contains_draft(self, item: QTreeWidgetItem) -> bool:
        return bool(item.data(0, self._DRAFT_ROLE)) or any(
            self._contains_draft(item.child(index))
            for index in range(item.childCount())
        )

    def _focused_append_container_path(self, option_item: QTreeWidgetItem) -> tuple[int, ...] | None:
        focus = QApplication.focusWidget()
        if focus is None:
            return None
        for item, editor in self._editor_widgets():
            if editor is None or sip.isdeleted(editor):
                continue
            if editor is not focus and not editor.isAncestorOf(focus):
                continue
            current = item
            while current is not None and current is not option_item:
                if current.data(0, self._APPEND_ROLE):
                    container = current.parent()
                    path = []
                    while container is not None and container is not option_item:
                        parent = container.parent()
                        if parent is None:
                            return None
                        path.append(parent.indexOfChild(container))
                        container = parent
                    return tuple(reversed(path)) if container is option_item else None
                current = current.parent()
            return None
        return None

    def _focus_append_editor(
        self,
        option_item: QTreeWidgetItem,
        container_path: tuple[int, ...],
    ) -> None:
        container = option_item
        for index in container_path:
            if index < 0 or index >= container.childCount():
                return
            container = container.child(index)
        append_item = next(
            (
                container.child(index)
                for index in range(container.childCount())
                if container.child(index).data(0, self._APPEND_ROLE)
            ),
            None,
        )
        if append_item is None:
            return

        def first_editor(item: QTreeWidgetItem):
            for index in range(item.childCount()):
                editor = first_editor(item.child(index))
                if editor is not None:
                    return editor
            editor = self.tree.itemWidget(item, 2)
            return editor if isinstance(editor, ParameterValueEditor) else None

        editor = first_editor(append_item)
        if editor is not None:
            self.tree.scrollToItem(append_item)
            editor.setFocus(Qt.FocusReason.OtherFocusReason)

    def _build_section(self, parent: Any, treeitem: QTreeWidgetItem | None = None) -> None:
        expert_parent = None
        for option in parent:
            if isinstance(option, Section):
                info = option.info
                item = QTreeWidgetItem([option.name, "", "", "", info])
                item.setToolTip(4, info)
                font = item.font(0)
                font.setBold(True)
                item.setFont(0, font)
                self._add_child(treeitem, item)
                self._build_section(option, item)
                continue
            path = tuple(option._get_path().split("."))
            if path in self._suppressed_paths:
                continue
            if bool(getattr(option._definition, "expert", False)):
                if expert_parent is None:
                    expert_parent = QTreeWidgetItem(["expert", "", "", "", "Expert options"])
                    self._add_child(treeitem, expert_parent)
                row_parent = expert_parent
            else:
                row_parent = treeitem
            self._render_option(option, path, row_parent, spec=self._field_specs.get(path))

    def _add_child(self, parent: QTreeWidgetItem | None, item: QTreeWidgetItem) -> None:
        if parent is None:
            self.tree.addTopLevelItem(item)
        else:
            parent.addChild(item)

    def _new_item(self, parent: QTreeWidgetItem | None, label: str, type_label: str = "", comment: str = "") -> QTreeWidgetItem:
        item = QTreeWidgetItem([label, type_label, "", "", comment])
        self._add_child(parent, item)
        return item

    def _render_option(
        self,
        option: Any,
        path: InputParameterPath,
        parent: QTreeWidgetItem | None,
        item: QTreeWidgetItem | None = None,
        spec: ExpertFieldSpec | None = None,
    ) -> QTreeWidgetItem:
        grammar = option._definition.grammar_type
        placement = FieldPlacement(path, option.name)
        row_label = option.name
        type_label = str(option._definition.type)
        related_paths: tuple[InputParameterPath, ...] = ()
        if spec is not None:
            if spec.small_editor is None:
                placement = spec.placement(path, option.name)
                type_label = spec.type_label or type_label
                related_paths = spec.related_paths
                node_item = item or self._new_item(parent, placement.label, type_label, option.info)
                self._reset_row(node_item, placement.label, type_label, option.info, path, related_paths)
                binding = SessionFieldBinding(self.session, placement, "expert")
                self._render_value(binding, placement, option._definition.type, node_item, path, spec=spec)
            else:
                placement = spec.placement(path, option.name, editor=spec.small_editor)
                row_label = placement.label
                type_label = spec.type_label or type_label
                related_paths = spec.related_paths
                node_item = item or self._new_item(parent, row_label, type_label, option.info)
                self._reset_row(node_item, row_label, type_label, option.info, path, related_paths)
                if option._definition.is_repeated:
                    self._render_repeated(option, path, placement, node_item, type_label, spec=spec)
                else:
                    binding = SessionFieldBinding(self.session, placement, "expert")
                    self._render_value(binding, placement, grammar, node_item, path, spec=spec)
                self._install_full_editor(node_item, path, spec)
        else:
            node_item = item or self._new_item(parent, row_label, type_label, option.info)
            self._reset_row(node_item, row_label, type_label, option.info, path)
            if option._definition.is_repeated:
                self._render_repeated(option, path, placement, node_item, type_label)
            else:
                binding = SessionFieldBinding(self.session, placement, "expert")
                self._render_value(binding, placement, grammar, node_item, path)

        node_item.setData(0, self._STRUCTURAL_KEY_ROLE, self._structural_key(option, spec))
        self._option_rows[path] = node_item
        self._update_changed_style(option, node_item, refresh_filter=False)
        return node_item

    def _reset_row(
        self,
        item: QTreeWidgetItem,
        label: str,
        type_label: str,
        comment: str,
        path: InputParameterPath,
        related: tuple[InputParameterPath, ...] = (),
    ) -> None:
        item.setText(0, label)
        item.setText(1, type_label)
        item.setText(4, comment)
        item.setToolTip(1, type_label)
        item.setToolTip(4, comment)
        item.setData(0, self._OPTION_PATH_ROLE, path)
        item.setData(0, self._RELATED_PATHS_ROLE, related)

    def _render_value(
        self,
        binding: Any,
        placement: FieldPlacement,
        grammar: Any,
        item: QTreeWidgetItem,
        path: InputParameterPath,
        *,
        spec: ExpertFieldSpec | None = None,
        append: bool = True,
    ) -> Any:
        if isinstance(binding, DraftFieldBinding):
            self._install_editor(item, binding, placement, spec=spec)
            return None
        if placement.editor != "auto":
            self._install_editor(item, binding, placement, spec=spec)
            return None
        if isinstance(grammar, (Array, SetOf)) and getattr(grammar, "array_access", False):
            return self._render_array(binding, placement, grammar, item, path, append=append)
        if isinstance(grammar, GrammarSequence):
            return self._render_sequence(binding, placement, grammar, item, path)
        if isinstance(grammar, Table):
            return self._render_table(binding, placement, grammar, item, path)
        self._install_editor(item, binding, placement, spec=spec)
        return None

    def _render_array(
        self,
        binding: Any,
        placement: FieldPlacement,
        grammar: Any,
        item: QTreeWidgetItem,
        path: InputParameterPath,
        *,
        append: bool,
    ) -> Any:
        value = binding.model_value_from(binding.parameters)
        values = _items(value)
        minimum = getattr(grammar, "min_length", None)
        maximum = getattr(grammar, "max_length", None)
        fixed = minimum is not None and minimum == maximum
        incomplete = fixed and (value is None or len(values) < minimum or any(v is None for v in values))
        self._install_editor(item, binding, placement)
        self._render_array_children(binding, placement, grammar, item, path, append=append)
        item.setData(0, self._STRUCTURAL_KEY_ROLE, _structure_key("array", (len(values), fixed, incomplete, maximum)))
        return item.data(0, self._STRUCTURAL_KEY_ROLE)

    def _render_sequence(
        self,
        binding: Any,
        placement: FieldPlacement,
        grammar: GrammarSequence,
        item: QTreeWidgetItem,
        path: InputParameterPath,
    ) -> Any:
        value = binding.model_value_from(binding.parameters)
        values = _sequence_values(grammar, value)
        if values is None:
            self._clear_children(item)
            self._install_editor(item, binding, placement)
            key = _structure_key("sequence-leaf", None)
            item.setData(0, self._STRUCTURAL_KEY_ROLE, key)
            return key

        self._install_editor(item, binding, placement)
        self._clear_children(item)
        names = getattr(grammar, "names", None)
        labels = [f"[{i}]" for i in range(len(grammar.types))]
        if isinstance(names, Mapping):
            for name, index in names.items():
                if isinstance(index, int) and 0 <= index < len(labels):
                    labels[index] = str(name)
        for index, subtype in enumerate(grammar.types):
            child_placement = FieldPlacement(path, labels[index])
            child_binding = sequence_item_binding(
                binding, index, child_placement, value_type=subtype, allows_unset=False
            )
            child = self._new_item(item, labels[index], str(subtype))
            self._render_value(child_binding, child_placement, subtype, child, path)
        key = _structure_key("sequence", tuple(id(t) for t in grammar.types))
        item.setData(0, self._STRUCTURAL_KEY_ROLE, key)
        return key

    def _render_table(
        self,
        binding: Any,
        placement: FieldPlacement,
        grammar: Table,
        item: QTreeWidgetItem,
        path: InputParameterPath,
    ) -> Any:
        self._clear_children(item)
        value = binding.model_value_from(binding.parameters)
        if value is None:
            self._set_value_label(item, "<Table>")
            key = _structure_key("table", None)
            item.setData(0, self._STRUCTURAL_KEY_ROLE, key)
            return key
        try:
            array = value if isinstance(value, np.ndarray) else grammar.convert(value)
        except Exception:  # noqa: BLE001 - preserve opaque input fallback.
            self._set_value_label(item, "<Data>")
            key = _structure_key("table", None)
            item.setData(0, self._STRUCTURAL_KEY_ROLE, key)
            return key
        if not isinstance(array, np.ndarray):
            self._set_value_label(item, "<Data>")
            key = _structure_key("table", None)
            item.setData(0, self._STRUCTURAL_KEY_ROLE, key)
            return key

        self._set_value_label(item, "<Table>")
        sequence = grammar.sequence
        if array.dtype.names:
            names = list(array.dtype.names)
            rows = range(len(array))
            cells_for_row = lambda row: [(name, row, name, index) for index, name in enumerate(names)]
        else:
            data = np.asarray(array)
            if data.ndim == 1:
                if len(sequence.types) != 1:
                    key = _structure_key("table", (data.shape, "opaque"))
                    item.setData(0, self._STRUCTURAL_KEY_ROLE, key)
                    return key
                data = data.reshape((-1, 1))
            if data.ndim != 2:
                key = _structure_key("table", (data.shape, "opaque"))
                item.setData(0, self._STRUCTURAL_KEY_ROLE, key)
                return key
            names = getattr(grammar, "names", None) or [f"[{i}]" for i in range(data.shape[1])]
            rows = range(data.shape[0])
            cells_for_row = lambda row: [(names[col] if col < len(names) else f"[{col}]", row, col, col) for col in range(data.shape[1])]

        for row_index in rows:
            row_item = self._new_item(item, f"[{row_index}]", "row")
            for label, row, column, column_index in cells_for_row(row_index):
                subtype = sequence.types[column_index] if column_index < len(sequence.types) else String()
                cell_placement = FieldPlacement(path, str(label))
                cell_binding = table_cell_binding(
                    binding, row, column, cell_placement, value_type=subtype
                )
                cell = self._new_item(row_item, str(label), str(subtype))
                self._render_value(cell_binding, cell_placement, subtype, cell, path)
        key = _structure_key("table", (array.shape, array.dtype.names))
        item.setData(0, self._STRUCTURAL_KEY_ROLE, key)
        return key

    def _render_repeated(
        self,
        option: Any,
        path: InputParameterPath,
        placement: FieldPlacement,
        item: QTreeWidgetItem,
        type_label: str,
        *,
        spec: ExpertFieldSpec | None = None,
    ) -> Any:
        root = SessionFieldBinding(self.session, placement, "expert")
        grammar = option._definition.type
        repeated = option._definition.is_repeated
        value = _all_values(option)
        self._clear_children(item)
        if repeated.is_dict:
            mapping = value if isinstance(value, Mapping) else {}
            default = mapping_value_binding(
                root, "def", placement, value_type=grammar,
                default=option.default_value, allows_unset=True,
            )
            if isinstance(grammar, (Array, SetOf)) and getattr(grammar, "array_access", False):
                whole_placement = replace(placement, editor="text")
                self._install_editor(item, default, whole_placement)
            else:
                self._render_value(default, placement, grammar, item, path, append=False)
            if isinstance(grammar, (Array, SetOf)) and getattr(grammar, "array_access", False):
                group = self._new_item(item, "Default items", str(grammar.type), "Items of the default value")
                self._render_array_children(default, placement, grammar, group, path, append=False)
                group.setData(0, self._COLLAPSE_ROLE, True)
            keys = sorted(
                (key for key in mapping if key != "def"),
                key=lambda key: (not isinstance(key, int), key),
            )
            for key in keys:
                child_placement = FieldPlacement(path, f"[{key}]", editor=placement.editor)
                binding = mapping_value_binding(
                    root, key, child_placement, value_type=grammar,
                    default=option.default_value, allows_unset=True,
                )
                child = self._new_item(item, child_placement.label, str(grammar))
                if isinstance(grammar, (Array, SetOf)) and getattr(grammar, "array_access", False):
                    child.setData(0, self._COLLAPSE_ROLE, True)
                    whole_placement = replace(child_placement, editor="text")
                    self._install_editor(child, binding, whole_placement)
                    self._render_array_children(binding, child_placement, grammar, child, path, append=False)
                else:
                    self._render_value(binding, child_placement, grammar, child, path)
                self._install_action(
                    child,
                    "Remove repeated value",
                    f"Remove repeated value {key}",
                    lambda current=binding: current.set_value(None),
                    remove=True,
                )
            numeric = [key for key in keys if isinstance(key, int)]
            next_key = max(numeric, default=0) + 1
            append_placement = FieldPlacement(
                path,
                f"[{next_key}]",
                editor=("text" if isinstance(grammar, (Array, SetOf)) else placement.editor),
                special_value_text="Add value…",
            )
            append_binding = mapping_value_binding(
                root, next_key, append_placement, value_type=grammar,
                allows_unset=False, allow_empty=True,
            )
            append_item = self._new_item(item, append_placement.label, str(grammar), "Add numbered value")
            append_item.setData(0, self._APPEND_ROLE, True)
            self._install_editor(append_item, append_binding, append_placement)
            if isinstance(grammar, (Array, SetOf)) and getattr(grammar, "array_access", False):
                self._render_array_children(
                    append_binding, append_placement, grammar, append_item, path, append=False
                )
            key = _structure_key("repeated-dict", tuple(keys))
        else:
            sequence = _items(value)
            summary = f"<{len(sequence)} value{'s' if len(sequence) != 1 else ''}>"
            self._set_value_label(item, summary)
            for index, _entry in enumerate(sequence):
                self._render_sequence_occurrence(root, grammar, path, item, index, append=False)
            self._render_sequence_occurrence(root, grammar, path, item, len(sequence), append=True)
            key = _structure_key("repeated-sequence", len(sequence))
        item.setData(0, self._STRUCTURAL_KEY_ROLE, self._structural_key(option, spec))
        self._option_rows[path] = item
        return key

    def _render_array_children(
        self,
        binding: Any,
        placement: FieldPlacement,
        grammar: Any,
        item: QTreeWidgetItem,
        path: InputParameterPath,
        *,
        append: bool,
    ) -> None:
        self._clear_children(item)
        value = binding.model_value_from(binding.parameters)
        values = _items(value)
        minimum = getattr(grammar, "min_length", None)
        maximum = getattr(grammar, "max_length", None)
        fixed = minimum is not None and minimum == maximum
        incomplete = fixed and (value is None or len(values) < minimum or any(v is None for v in values))
        item.setData(0, self._DRAFT_ROLE, bool(incomplete))
        display = list(values)
        if fixed:
            display.extend([None] * max(0, minimum - len(display)))
        draft = FixedArrayDraft(binding, minimum, value) if incomplete else None
        for index, component in enumerate(display):
            child_placement = FieldPlacement(path, f"[{index}]")
            child_binding = (
                DraftFieldBinding(binding, draft, index, child_placement)
                if draft is not None
                else array_item_binding(binding, index, child_placement, allows_unset=False)
            )
            child = self._new_item(item, child_placement.label, str(grammar.type))
            if isinstance(child_binding, DraftFieldBinding):
                self._install_editor(child, child_binding, child_placement)
            else:
                self._render_value(child_binding, child_placement, grammar.type, child, path)
        if append and not fixed and (maximum is None or len(values) < maximum):
            index = len(values)
            child_placement = FieldPlacement(path, f"[{index}]", special_value_text="Append…")
            child_binding = array_item_binding(
                binding, index, child_placement, append=True, allow_empty=True
            )
            child = self._new_item(item, child_placement.label, str(grammar.type), "Append new item")
            child.setData(0, self._APPEND_ROLE, True)
            self._render_value(child_binding, child_placement, grammar.type, child, path)
        item.setData(0, self._STRUCTURAL_KEY_ROLE, _structure_key("array", (len(values), fixed, incomplete, maximum)))

    def _render_sequence_occurrence(
        self,
        root: Any,
        grammar: Any,
        path: InputParameterPath,
        parent: QTreeWidgetItem,
        index: int,
        *,
        append: bool,
    ) -> None:
        label = f"[{index + 1}]"
        placement = FieldPlacement(
            path, label, special_value_text="Add value…" if append else None
        )
        binding = sequence_value_binding(
            root, index, placement, value_type=grammar,
            allows_unset=not append, allow_empty=append,
            append=append, remove_on_none=not append,
        )
        item = self._new_item(parent, label, str(grammar), "Add numbered value" if append else "")
        if append:
            item.setData(0, self._APPEND_ROLE, True)
        if isinstance(grammar, (Array, SetOf)) and getattr(grammar, "array_access", False):
            whole_placement = replace(placement, editor="text")
            self._install_editor(item, binding, whole_placement)
            if not append:
                item.setData(0, self._COLLAPSE_ROLE, True)
                self._render_array_children(binding, placement, grammar, item, path, append=False)
        else:
            self._render_value(binding, placement, grammar, item, path, append=not append)
        if not append:
            self._install_action(
                item, "Remove repeated value", f"Remove repeated value {index + 1}",
                lambda current=binding: current.set_value(None), remove=True,
            )

    def _install_editor(
        self,
        item: QTreeWidgetItem,
        binding: Any,
        placement: FieldPlacement,
        *,
        spec: ExpertFieldSpec | None = None,
    ) -> ParameterValueEditor:
        existing = self.tree.itemWidget(item, 2)
        if isinstance(existing, ParameterValueEditor):
            editor = existing
            editor.refresh()
        else:
            editor = create_editor(binding, placement, atoms=self._atoms, parent=self.tree)
            self.tree.setItemWidget(item, 2, editor)
            self._set_editor(item, editor)
            editor.refresh()
        self._apply_placement_presentation(editor, placement)
        if spec and spec.minimum_width:
            editor.setMinimumWidth(spec.minimum_width)
            self.tree.setColumnWidth(2, max(spec.minimum_width, self.tree.columnWidth(2)))
        dependencies = set(placement.paths)
        dependencies.update(getattr(editor, "dependencies", ()))
        self._dependency_editors[id(editor)] = (editor, item, dependencies, placement)
        item.setData(0, self._VALUE_EDITOR_ROLE, True)
        return editor

    def _install_full_editor(self, item: QTreeWidgetItem, path: InputParameterPath, spec: ExpertFieldSpec) -> None:
        self._install_action(
            item,
            f"Open full editor for {'.'.join(path)}",
            f"Open full editor for {'.'.join(path)}",
            lambda p=path, s=spec: self._open_full_editor(p, s),
            icon=QStyle.StandardPixmap.SP_FileDialogDetailedView,
        )

    def _install_action(
        self,
        item: QTreeWidgetItem,
        label: str,
        tooltip: str,
        callback: Any,
        *,
        remove: bool = False,
        icon: QStyle.StandardPixmap | None = None,
    ) -> None:
        button = QToolButton(self.tree)
        button.setAutoRaise(True)
        button.setToolTip(tooltip)
        button.setAccessibleName(label)
        if icon is not None:
            button.setIcon(self.style().standardIcon(icon))
        elif remove:
            button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCloseButton))
        else:
            button.setText(label)
        button.clicked.connect(lambda _checked=False, action=callback: action())
        self.tree.setItemWidget(item, 3, button)

    def _set_value_label(self, item: QTreeWidgetItem, text: str) -> None:
        item.setText(2, text)
        item.setToolTip(2, text)
        label = QLabel(text)
        label.setToolTip(text)
        self.tree.setItemWidget(item, 2, label)
        item.setData(0, self._VALUE_EDITOR_ROLE, False)

    def _apply_placement_presentation(self, editor: ParameterValueEditor, placement: FieldPlacement) -> None:
        text = placement.special_value_text
        if not text:
            return
        if isinstance(editor, QLineEdit):
            editor.setPlaceholderText(text)
        elif hasattr(editor, "setSpecialValueText"):
            editor.setSpecialValueText(text)

    def _clear_children(self, item: QTreeWidgetItem) -> None:
        self._unregister_subtree(item, include_root=False)
        while item.childCount():
            item.removeChild(item.child(0))
        self._refresh_editor_errors()

    def _unregister_subtree(self, item: QTreeWidgetItem, *, include_root: bool = True) -> None:
        targets = []
        if include_root:
            targets.append(item)
        targets.extend(item.child(index) for index in range(item.childCount()))
        for child in targets:
            self._unregister_subtree(child, include_root=False)
            editor = self.tree.itemWidget(child, 2)
            if editor is not None:
                self._dependency_editors.pop(id(editor), None)
            self._editor_errors.pop(id(child), None)

    def _clear_registries(self) -> None:
        self._option_rows.clear()
        self._dependency_editors.clear()
        self._editor_errors.clear()

    def _prune_registries(self) -> None:
        self._dependency_editors = {
            key: (editor, item, deps, placement)
            for key, (editor, item, deps, placement) in self._dependency_editors.items()
            if not sip.isdeleted(editor)
            and not sip.isdeleted(item)
            and self.tree.itemWidget(item, 2) is editor
        }
        self._refresh_editor_errors()

    def _set_editor(self, item: QTreeWidgetItem, editor: ParameterValueEditor) -> None:
        editor.validationChanged.connect(
            lambda message, row=item: self._display_editor_error(row, row.text(0), message)
        )
        item.setSizeHint(2, editor.sizeHint())

    def _display_editor_error(self, item: QTreeWidgetItem, label: str, message: str) -> None:
        key = id(item)
        if message:
            self._editor_errors[key] = (item, label, message)
        else:
            self._editor_errors.pop(key, None)
        self._refresh_editor_errors()

    def _refresh_editor_errors(self) -> None:
        self._editor_errors = {
            key: (item, label, error)
            for key, (item, label, error) in self._editor_errors.items()
            if not sip.isdeleted(item)
        }
        messages = [f"{label}: {error}" for _, label, error in self._editor_errors.values()]
        self.error_label.setText("\n".join(messages))
        self.error_label.setVisible(bool(messages))
        self.validationChanged.emit(bool(messages))

    def _editor_widgets(self):
        def visit(item):
            if item.data(0, self._VALUE_EDITOR_ROLE):
                yield item, self.tree.itemWidget(item, 2)
            for index in range(item.childCount()):
                yield from visit(item.child(index))
        return list(visit(self.tree.invisibleRootItem()))

    def _collapse_groups(self, root: QTreeWidgetItem | None = None) -> None:
        root = root or self.tree.invisibleRootItem()
        def visit(item):
            if item.data(0, self._COLLAPSE_ROLE):
                item.setExpanded(False)
            for index in range(item.childCount()):
                visit(item.child(index))
        visit(root)

    def _update_changed_style(self, option: Any, item: QTreeWidgetItem, *, refresh_filter: bool = True) -> None:
        try:
            changed = bool(option.is_changed())
            related = item.data(0, self._RELATED_PATHS_ROLE) or ()
            changed = changed or any(resolve_option(self.parameters, path).is_changed() for path in related)
        except Exception:  # noqa: BLE001 - partial values remain displayable.
            changed = False
        item.setData(0, self._CHANGED_ROLE, changed)
        font = item.font(0)
        font.setBold(changed)
        item.setFont(0, font)
        if refresh_filter:
            self.apply_filter(self.filter_edit.text())

    def _open_full_editor(self, path: InputParameterPath, spec: ExpertFieldSpec) -> None:
        option = resolve_option(self.parameters, path)
        dialog = ExpertFieldEditorDialog(
            self.parameters, path, spec, atoms=self._atoms, parent=self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            placement = FieldPlacement(path, option.name)
            SessionFieldBinding(self.session, placement, "expert").set_value(dialog.value)
