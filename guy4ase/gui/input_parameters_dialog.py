"""Dialog to view and edit ase2sprkkr InputParameters."""
from __future__ import annotations

from typing import Any, Optional
from collections.abc import Mapping, Sequence as AbcSequence
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTreeWidget, QTreeWidgetItem,
    QWidget, QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox, QLabel,
    QComboBox, QFileDialog, QMessageBox, QToolButton, QStyle
)
from PyQt6.QtCore import Qt
import numpy as np

from ase2sprkkr.input_parameters.input_parameters import InputParameters  # type: ignore
from ase2sprkkr.common.configuration_containers import Section  # type: ignore
from ase2sprkkr.common.configuration_containers import ConfigurationContainer  # type: ignore
from ase2sprkkr.common.repeated_configuration_containers import RepeatedConfigurationContainer  # type: ignore
from ase2sprkkr.common.options import BaseOption  # type: ignore
from ase2sprkkr.common.grammar_types import (  # type: ignore
    Integer, Real, Boolean, String, Keyword, Energy, Array,
    Sequence as GrammarSequence, Table, SetOf, Flag,
)


def coalesce(*args):
    for a in args:
        if a is not None:
            return a
    return None


def _mark_editor_invalid(editor: QWidget, message: str) -> None:
    editor.setStyleSheet("border: 2px solid red;")
    editor.setToolTip(message)


def _mark_editor_valid(editor: QWidget) -> None:
    editor.setStyleSheet("")
    editor.setToolTip("")


def _stringify_value(grammar_type: Any, value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    if isinstance(value, np.ndarray) and not isinstance(grammar_type, (Array, SetOf, Table)):
        return "<Data>"
    try:
        return str(grammar_type.string(value))
    except Exception:
        try:
            return str(value)
        except Exception:
            return fallback


def _mutable_sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, AbcSequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return [value]


def _reverse_names_map(names: Any, size: int) -> list[str]:
    labels = [f"[{i}]" for i in range(size)]
    if isinstance(names, dict):
        for name, index in names.items():
            if isinstance(index, int) and 0 <= index < size:
                labels[index] = str(name)
    return labels


def _option_value(opt: Any) -> Any:
    try:
        return opt.get()
    except Exception:
        return getattr(opt, '_value', None)


def _create_scalar_editor(
    grammar_type: Any,
    current_value: Any,
    on_value: callable,
    *,
    read_only: bool = False,
    allow_empty: bool = False,
) -> QWidget:
    if grammar_type is None:
        grammar_type = String()

    if isinstance(grammar_type, Integer):
        editor = QSpinBox()
        editor.setRange(coalesce(getattr(grammar_type, 'min', None), np.iinfo(np.int32).min), coalesce(getattr(grammar_type, 'max', None), np.iinfo(np.int32).max))
        try:
            if current_value is not None:
                editor.setValue(int(current_value))
        except Exception:
            pass
        editor.setReadOnly(read_only)
        editor.valueChanged.connect(lambda value: on_value(int(value)))
        return editor

    if isinstance(grammar_type, Real):
        editor = QDoubleSpinBox()
        lo = coalesce(getattr(grammar_type, 'min', None), -1e16)
        hi = coalesce(getattr(grammar_type, 'max', None), 1e16)
        editor.setDecimals(8)
        editor.setRange(lo, hi)
        editor.setSingleStep((hi - lo) / 1000.0 if hi - lo < 1e6 else 1.0)
        try:
            if current_value is not None:
                editor.setValue(float(current_value))
        except Exception:
            pass
        editor.setReadOnly(read_only)
        editor.valueChanged.connect(lambda value: on_value(float(value)))
        return editor

    if isinstance(grammar_type, Energy):
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        value_box = QDoubleSpinBox(container)
        lo = coalesce(getattr(grammar_type, 'min', None), -1e16)
        hi = coalesce(getattr(grammar_type, 'max', None), 1e16)
        value_box.setDecimals(8)
        value_box.setRange(lo, hi)
        value_box.setSingleStep((hi - lo) / 1000.0 if hi - lo < 1e6 else 1.0)
        unit_box = QComboBox(container)
        units = getattr(grammar_type, 'units', {}) or {}
        for unit in units.keys():
            unit_box.addItem(str(unit))
        try:
            if isinstance(current_value, (list, tuple)) and len(current_value) == 2:
                value_box.setValue(float(current_value[0]))
                idx = unit_box.findText(str(current_value[1]))
                if idx >= 0:
                    unit_box.setCurrentIndex(idx)
            elif current_value is not None:
                value_box.setValue(float(current_value))
        except Exception:
            pass

        def emit_value(*_args) -> None:
            on_value((value_box.value(), unit_box.currentText()))

        value_box.setReadOnly(read_only)
        if read_only:
            unit_box.setEnabled(False)
        value_box.valueChanged.connect(emit_value)
        unit_box.currentTextChanged.connect(emit_value)
        layout.addWidget(value_box, 3)
        layout.addWidget(unit_box, 1)
        return container

    if isinstance(grammar_type, (Boolean, Flag)):
        editor = QCheckBox()
        try:
            editor.setChecked(bool(current_value))
        except Exception:
            pass
        if read_only:
            editor.setEnabled(False)
        editor.toggled.connect(lambda value: on_value(bool(value)))
        return editor

    if isinstance(grammar_type, Keyword):
        editor = QComboBox()
        current_index = 0
        for idx, (keyword, info) in enumerate(grammar_type.items()):
            label = str(keyword) if info is None else f"{keyword}: {info}"
            editor.addItem(label, keyword)
            if current_value == keyword:
                current_index = idx
        editor.setCurrentIndex(current_index)
        if read_only:
            editor.setEnabled(False)
        editor.currentIndexChanged.connect(lambda _index: on_value(editor.currentData()))
        return editor

    editor = QLineEdit()
    if current_value is not None:
        editor.setText(_stringify_value(grammar_type, current_value, fallback=str(current_value)))
    editor.setReadOnly(read_only)

    def commit() -> None:
        text = editor.text().strip()
        if allow_empty and not text:
            _mark_editor_valid(editor)
            return
        try:
            value = grammar_type.parse(text)
        except Exception:
            try:
                value = grammar_type.convert(text)
                grammar_type.validate(value)
            except Exception as e:
                _mark_editor_invalid(editor, str(e))
                return
        try:
            on_value(value)
        except Exception as e:
            _mark_editor_invalid(editor, str(e))
            return
        _mark_editor_valid(editor)
        try:
            editor.setText(_stringify_value(grammar_type, value, fallback=text))
        except Exception:
            pass

    editor.editingFinished.connect(commit)
    return editor


class _TreeDialogBase(QDialog):
    def __init__(self, title: str, parent: Optional[QWidget] = None, *, filter_all_columns: bool = False):
        super().__init__(parent)
        self._filter_all_columns = filter_all_columns
        self.setWindowTitle(title)
        self.resize(800, 600)

        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filter by name…")
        self._filter_clear_btn = QPushButton("Clear")
        self._expand_all_btn = QPushButton("Expand all")
        self._collapse_all_btn = QPushButton("Collapse all")

        self._tree = QTreeWidget()
        self._tree.setColumnCount(4)
        self._tree.setHeaderLabels(['Name', 'Type', 'Value', 'Comment'])
        self._tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._tree.setColumnWidth(0, 300)

        root = QVBoxLayout(self)
        self._root_layout = root
        header = QWidget(self)
        header_l = QHBoxLayout(header)
        header_l.setContentsMargins(0, 0, 0, 0)
        header_l.addWidget(QLabel("Search:"))
        header_l.addWidget(self._filter_edit, 1)
        header_l.addWidget(self._filter_clear_btn)
        header_l.addStretch(1)
        header_l.addWidget(self._expand_all_btn)
        header_l.addWidget(self._collapse_all_btn)
        self._header_layout = header_l
        root.addWidget(header, 0)
        root.addWidget(self._tree, 1)

        self._footer = QHBoxLayout()
        self._footer.addStretch(1)
        root.addLayout(self._footer)

        self._filter_edit.textChanged.connect(self._apply_filter)
        self._filter_clear_btn.clicked.connect(self._clear_filter)
        self._expand_all_btn.clicked.connect(self._tree.expandAll)
        self._collapse_all_btn.clicked.connect(self._tree.collapseAll)

    def _add_footer_button(self, text: str, slot: callable) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(slot)
        self._footer.addWidget(button)
        return button

    def _add_child(self, parent: Optional[QTreeWidgetItem], child: QTreeWidgetItem) -> None:
        if parent is None:
            self._tree.addTopLevelItem(child)
        else:
            parent.addChild(child)

    def _clear_filter(self) -> None:
        self._filter_edit.setText("")
        self._filter_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _item_filter_texts(self, item: QTreeWidgetItem) -> list[str]:
        if self._filter_all_columns:
            return [item.text(i) or "" for i in range(self._tree.columnCount())]
        return [item.text(0) or ""]

    def _apply_filter(self, text: str) -> None:
        needle = (text or "").strip().lower()

        def visit(item: QTreeWidgetItem) -> bool:
            if not needle:
                for i in range(item.childCount()):
                    visit(item.child(i))
                item.setHidden(False)
                return True

            self_match = any(needle in column.lower() for column in self._item_filter_texts(item))
            child_match = False
            for i in range(item.childCount()):
                if visit(item.child(i)):
                    child_match = True
            visible = self_match or child_match
            item.setHidden(not visible)
            return visible

        for i in range(self._tree.topLevelItemCount()):
            visit(self._tree.topLevelItem(i))


class InputParametersDialog(_TreeDialogBase):
    _CHANGED_ROLE = Qt.ItemDataRole.UserRole

    def __init__(
        self,
        params: InputParameters,
        parent: Optional[QWidget] = None,
        *,
        show_changed_only: bool = False,
        calculate_mode: bool = False,
        directory: Optional[str] = None,
    ):
        self._params = params
        self._calculate_mode = calculate_mode
        self._directory = directory or ''
        super().__init__('Edit Input Parameters', parent=parent, filter_all_columns=False)
        if calculate_mode:
            directory_row = QWidget(self)
            directory_layout = QHBoxLayout(directory_row)
            directory_layout.setContentsMargins(0, 0, 0, 0)
            directory_layout.addWidget(QLabel('Working directory:'))
            self._directory_edit = QLineEdit(self._directory, directory_row)
            self._directory_edit.setPlaceholderText('Select a calculation directory')
            directory_layout.addWidget(self._directory_edit, 1)
            choose_directory = QPushButton('Browse…', directory_row)
            choose_directory.clicked.connect(self._choose_directory)
            directory_layout.addWidget(choose_directory)
            self._root_layout.insertWidget(1, directory_row)
        else:
            self._directory_edit = None
        self._changed_only_checkbox = QCheckBox('Show changed only')
        self._header_layout.insertWidget(3, self._changed_only_checkbox)
        self._changed_only_checkbox.toggled.connect(lambda _checked: self._apply_filter(self._filter_edit.text()))
        self.load_btn = self._add_footer_button('Load input…', self._load_input)
        self.cancel_btn = self._add_footer_button('Cancel', self.reject)
        self.ok_btn = self._add_footer_button('Calculate' if calculate_mode else 'OK', self._on_ok)
        self._build_tree()
        self._changed_only_checkbox.setChecked(show_changed_only)

    def _build_tree(self) -> None:
        self._tree.clear()
        self._build_section(self._params)
        self._tree.expandAll()
        self._apply_filter(self._filter_edit.text())

    def _apply_filter(self, text: str) -> None:
        if not hasattr(self, '_changed_only_checkbox'):
            super()._apply_filter(text)
            return
        needle = (text or '').strip().lower()
        changed_only = self._changed_only_checkbox.isChecked()

        def visit(item: QTreeWidgetItem) -> bool:
            self_match = not needle or needle in (item.text(0) or '').lower()
            own_changed = bool(item.data(0, self._CHANGED_ROLE))
            child_visible = False
            for index in range(item.childCount()):
                child_visible = visit(item.child(index)) or child_visible

            has_children = item.childCount() > 0
            changed_match = not changed_only or own_changed or child_visible
            visible = (self_match and changed_match) or child_visible
            if has_children and changed_only and not own_changed and not child_visible:
                visible = False
            item.setHidden(not visible)
            return visible

        for index in range(self._tree.topLevelItemCount()):
            visit(self._tree.topLevelItem(index))

    def _build_section(self, parent: Any, treeitem: Optional[QTreeWidgetItem] = None) -> None:
        expert_parent: Optional[QTreeWidgetItem] = None

        def get_expert_parent() -> QTreeWidgetItem:
            nonlocal expert_parent
            if expert_parent is None:
                expert_parent = QTreeWidgetItem(["expert", "", "", "Expert options"])
                self._add_child(treeitem, expert_parent)
            return expert_parent

        for opt in parent:
            if isinstance(opt, Section):
                info = opt.info
                sec_item = QTreeWidgetItem([opt.name, "", "", info])
                sec_item.setToolTip(3, info)
                font = sec_item.font(0)
                font.setBold(True)
                sec_item.setFont(0, font)
                self._add_child(treeitem, sec_item)
                self._build_section(opt, sec_item)
                continue

            parent_item = get_expert_parent() if bool(getattr(opt._definition, 'expert', False)) else treeitem
            self._build_option(opt, parent_item)

    def _build_option(self, opt: Any, parent_item: Optional[QTreeWidgetItem]) -> None:
        grammar_type = opt._definition.grammar_type
        info = opt.info
        type_text = str(grammar_type)
        item = QTreeWidgetItem([opt.name, type_text, '', info])
        item.setToolTip(1, type_text)
        item.setToolTip(3, info)
        self._add_child(parent_item, item)
        self._update_changed_style(opt, item, refresh_filter=False)

        if isinstance(grammar_type, (Array, SetOf)):
            self._build_array_option(opt, item, grammar_type)
        elif isinstance(grammar_type, GrammarSequence):
            self._build_sequence_option(opt, item, grammar_type)
        elif isinstance(grammar_type, Table):
            self._build_table_option(opt, item, grammar_type)
        else:
            value = _option_value(opt)
            editor = _create_scalar_editor(
                grammar_type,
                value,
                lambda new_value, o=opt, option_item=item: self._set_option_value(o, option_item, new_value),
            )
            self._tree.setItemWidget(item, 2, editor)

    def _set_option_value(self, opt: Any, item: QTreeWidgetItem, value: Any) -> None:
        opt.set(value)
        self._update_changed_style(opt, item)

    def _update_changed_style(
        self,
        opt: Any,
        item: QTreeWidgetItem,
        *,
        refresh_filter: bool = True,
    ) -> None:
        try:
            changed = bool(opt.is_changed())
        except Exception:
            changed = False
        item.setData(0, self._CHANGED_ROLE, changed)
        font = item.font(0)
        font.setBold(changed)
        item.setFont(0, font)
        if refresh_filter and hasattr(self, '_changed_only_checkbox'):
            self._apply_filter(self._filter_edit.text())

    def _clear_children(self, item: QTreeWidgetItem) -> None:
        while item.childCount():
            item.removeChild(item.child(0))

    def _rebuild_compound_option(self, opt: Any, item: QTreeWidgetItem) -> None:
        self._clear_children(item)
        grammar_type = opt._definition.grammar_type
        if isinstance(grammar_type, (Array, SetOf)):
            self._build_array_option(opt, item, grammar_type)
        elif isinstance(grammar_type, GrammarSequence):
            self._build_sequence_option(opt, item, grammar_type)
        elif isinstance(grammar_type, Table):
            self._build_table_option(opt, item, grammar_type)

    def _build_summary_editor(self, opt: Any, item: QTreeWidgetItem, grammar_type: Any, *, editable: bool) -> None:
        value = _option_value(opt)
        editor = QLineEdit()
        editor.setText(_stringify_value(grammar_type, value))
        editor.setReadOnly(not editable)

        if editable:
            def commit() -> None:
                text = editor.text().strip()
                try:
                    value = grammar_type.parse(text)
                    opt.set(value)
                except Exception as e:
                    _mark_editor_invalid(editor, str(e))
                    return
                _mark_editor_valid(editor)
                self._update_changed_style(opt, item)
                editor.setText(_stringify_value(grammar_type, _option_value(opt)))
                self._rebuild_compound_option(opt, item)

            editor.editingFinished.connect(commit)

        self._tree.setItemWidget(item, 2, editor)
        item.setToolTip(2, editor.text())

    def _build_array_option(self, opt: Any, item: QTreeWidgetItem, grammar_type: Any) -> None:
        self._build_summary_editor(opt, item, grammar_type, editable=True)
        values = _mutable_sequence(_option_value(opt))
        for index, value in enumerate(values):
            child = QTreeWidgetItem([f'[{index}]', str(grammar_type.type), '', ''])
            self._add_child(item, child)
            editor = _create_scalar_editor(
                grammar_type.type,
                value,
                lambda new_value, idx=index, o=opt, parent_item=item: self._update_array_value(o, parent_item, idx, new_value),
            )
            self._tree.setItemWidget(child, 2, editor)

        max_length = getattr(grammar_type, 'max_length', None)
        if max_length is None or len(values) < max_length:
            append_item = QTreeWidgetItem([f'[{len(values)}]', str(grammar_type.type), '', 'Append new item'])
            self._add_child(item, append_item)
            editor = _create_scalar_editor(
                grammar_type.type,
                None,
                lambda new_value, idx=len(values), o=opt, parent_item=item: self._update_array_value(o, parent_item, idx, new_value),
                allow_empty=True,
            )
            self._tree.setItemWidget(append_item, 2, editor)

    def _update_array_value(self, opt: Any, item: QTreeWidgetItem, index: int, value: Any) -> None:
        values = _mutable_sequence(_option_value(opt))
        if index < len(values):
            values[index] = value
        else:
            values.append(value)
        opt.set(values)
        self._update_changed_style(opt, item)
        self._rebuild_compound_option(opt, item)

    def _build_sequence_option(self, opt: Any, item: QTreeWidgetItem, grammar_type: GrammarSequence) -> None:
        self._build_summary_editor(opt, item, grammar_type, editable=True)
        values = _mutable_sequence(_option_value(opt))
        labels = _reverse_names_map(getattr(grammar_type, 'names', None), len(grammar_type.types))
        for index, subtype in enumerate(grammar_type.types):
            value = values[index] if index < len(values) else None
            child = QTreeWidgetItem([labels[index], str(subtype), '', ''])
            self._add_child(item, child)
            editor = _create_scalar_editor(
                subtype,
                value,
                lambda new_value, idx=index, o=opt, parent_item=item: self._update_sequence_value(o, parent_item, idx, new_value),
            )
            self._tree.setItemWidget(child, 2, editor)

    def _update_sequence_value(self, opt: Any, item: QTreeWidgetItem, index: int, value: Any) -> None:
        current = _mutable_sequence(_option_value(opt))
        grammar_type = opt._definition.grammar_type
        while len(current) < len(grammar_type.types):
            current.append(None)
        current[index] = value
        opt.set(current)
        self._update_changed_style(opt, item)
        self._rebuild_compound_option(opt, item)

    def _build_table_option(self, opt: Any, item: QTreeWidgetItem, grammar_type: Table) -> None:
        item.setText(2, '<Table>')
        item.setToolTip(2, '<Table>')
        table_label = QLabel('<Table>')
        table_label.setToolTip('<Table>')
        self._tree.setItemWidget(item, 2, table_label)

        value = _option_value(opt)
        if value is None:
            return
        if not isinstance(value, np.ndarray):
            try:
                value = grammar_type.convert(value)
            except Exception:
                item.setText(2, '<Data>')
                return
        if not isinstance(value, np.ndarray):
            item.setText(2, '<Data>')
            return

        if value.dtype.names:
            column_names = list(value.dtype.names)
            for row_index in range(len(value)):
                row_item = QTreeWidgetItem([f'[{row_index}]', 'row', '', ''])
                self._add_child(item, row_item)
                for col_index, column_name in enumerate(column_names):
                    subtype = grammar_type.sequence.types[col_index] if col_index < len(grammar_type.sequence.types) else String()
                    cell_value = value[row_index][column_name]
                    if isinstance(cell_value, np.generic):
                        cell_value = cell_value.item()
                    cell_item = QTreeWidgetItem([str(column_name), str(subtype), '', ''])
                    self._add_child(row_item, cell_item)
                    editor = _create_scalar_editor(
                        subtype,
                        cell_value,
                        lambda new_value, r=row_index, c=column_name, o=opt, parent_item=item: self._update_table_field(o, parent_item, r, c, new_value),
                    )
                    self._tree.setItemWidget(cell_item, 2, editor)
            return

        array = np.asarray(value)
        if array.ndim == 1:
            if len(grammar_type.sequence.types) == 1:
                array = array.reshape((-1, 1))
            else:
                item.setText(2, '<Data>')
                return
        if array.ndim != 2:
            item.setText(2, '<Data>')
            return

        column_names = list(getattr(grammar_type, 'names', []) or [f'[{i}]' for i in range(array.shape[1])])
        for row_index in range(array.shape[0]):
            row_item = QTreeWidgetItem([f'[{row_index}]', 'row', '', ''])
            self._add_child(item, row_item)
            for col_index in range(array.shape[1]):
                subtype = grammar_type.sequence.types[col_index] if col_index < len(grammar_type.sequence.types) else String()
                cell_value = array[row_index, col_index]
                if isinstance(cell_value, np.generic):
                    cell_value = cell_value.item()
                name = column_names[col_index] if col_index < len(column_names) else f'[{col_index}]'
                cell_item = QTreeWidgetItem([str(name), str(subtype), '', ''])
                self._add_child(row_item, cell_item)
                editor = _create_scalar_editor(
                    subtype,
                    cell_value,
                    lambda new_value, r=row_index, c=col_index, o=opt, parent_item=item: self._update_table_cell(o, parent_item, r, c, new_value),
                )
                self._tree.setItemWidget(cell_item, 2, editor)

    def _update_table_field(self, opt: Any, item: QTreeWidgetItem, row_index: int, column_name: str, value: Any) -> None:
        current = np.array(_option_value(opt), copy=True)
        current[row_index][column_name] = value
        opt.set(current)
        self._update_changed_style(opt, item)
        self._rebuild_compound_option(opt, item)

    def _update_table_cell(self, opt: Any, item: QTreeWidgetItem, row_index: int, column_index: int, value: Any) -> None:
        current = np.array(_option_value(opt), copy=True)
        current[row_index, column_index] = value
        opt.set(current)
        self._update_changed_style(opt, item)
        self._rebuild_compound_option(opt, item)

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
            self._params = InputParameters.from_file(file_path)
        except Exception as exc:
            QMessageBox.critical(self, 'Load Error', f'Failed to load input parameters:\n{exc}')
            return
        self._build_tree()
        self._changed_only_checkbox.setChecked(True)

    def _choose_directory(self) -> bool:
        start = self._directory_edit.text().strip() if self._directory_edit is not None else self._directory
        selected = QFileDialog.getExistingDirectory(self, 'Select Calculation Directory', start)
        if not selected:
            return False
        self._directory = str(selected)
        if self._directory_edit is not None:
            self._directory_edit.setText(self._directory)
        return True

    def _on_ok(self) -> None:
        if self._calculate_mode:
            self._directory = self._directory_edit.text().strip() if self._directory_edit is not None else ''
            if not self._directory and not self._choose_directory():
                return
        self.accept()

    def result(self) -> Optional[InputParameters]:
        return getattr(self, '_params', None)

    def directory(self) -> str:
        if self._directory_edit is not None:
            return self._directory_edit.text().strip()
        return self._directory


def edit_input_parameters(
    params: InputParameters,
    parent: Optional[QWidget] = None,
    *,
    show_changed_only: bool = False,
    calculate_mode: bool = False,
    directory: Optional[str] = None,
    return_directory: bool = False,
) -> Any:
    dlg = InputParametersDialog(
        params,
        parent=parent,
        show_changed_only=show_changed_only,
        calculate_mode=calculate_mode,
        directory=directory,
    )
    code = dlg.exec()
    if code == QDialog.DialogCode.Accepted:
        if return_directory:
            return dlg.result(), dlg.directory()
        return dlg.result()
    return None


class ReadOnlyObjectDialog(_TreeDialogBase):
    def __init__(self, value: Any, title: str = 'View Value', parent: Optional[QWidget] = None):
        self._value = value
        self._visited: set[int] = set()
        self._child_dialogs: list[ReadOnlyObjectDialog] = []
        super().__init__(title, parent=parent, filter_all_columns=True)
        self._tree.setColumnCount(5)
        self._tree.setHeaderLabels(['Name', 'Type', 'Value', 'Comment', 'Actions'])
        self._tree.setColumnWidth(4, 140)
        self.close_btn = self._add_footer_button('Close', self.close)
        self._build_tree()

    def _build_tree(self) -> None:
        self._visited.clear()
        self._add_value('value', self._value, None)
        self._tree.expandToDepth(1)

    def _safe_text(self, value: Any) -> str:
        if isinstance(value, BaseOption):
            try:
                value = value()
            except Exception as exc:
                return f'<error: {exc}>'
        if value is None:
            return 'None'
        if isinstance(value, np.ndarray):
            return '<Data>'
        if isinstance(value, str):
            return value
        try:
            return str(value)
        except Exception:
            return repr(value)

    def _is_scalar(self, value: Any) -> bool:
        if isinstance(value, BaseOption):
            try:
                value = value()
            except Exception:
                return True
        scalar_types = (str, bytes, int, float, bool, complex, type(None), Path)
        if isinstance(value, scalar_types):
            return True
        if isinstance(value, (np.generic, np.ndarray)):
            return True
        return False

    def _iter_object_items(self, value: Any) -> list[tuple[str, Any, str]]:
        if isinstance(value, np.ndarray):
            return []
        if isinstance(value, RepeatedConfigurationContainer):
            values = value._values
            iterable = values.items() if isinstance(values, Mapping) else enumerate(values)
            return [(f'[{key}]', item, '') for key, item in iterable]
        if isinstance(value, ConfigurationContainer):
            return [(str(key), item, '') for key, item in value.items().items()]
        if isinstance(value, Mapping):
            return [(str(key), item, '') for key, item in value.items()]
        if isinstance(value, AbcSequence) and not isinstance(value, (str, bytes, bytearray)):
            return [(f'[{idx}]', item, '') for idx, item in enumerate(value)]
        if hasattr(value, '__dict__'):
            out = []
            for key, item in vars(value).items():
                if key.startswith('_'):
                    continue
                if callable(item):
                    continue
                out.append((str(key), item, ''))
            return out
        return []

    def _add_value(self, name: str, value: Any, parent: Optional[QTreeWidgetItem]) -> None:
        type_name = type(value).__name__
        display = self._safe_text(value)
        if len(display) > 500:
            display = display[:497] + '...'

        item = QTreeWidgetItem([name, type_name, display if self._is_scalar(value) else '', ''])
        item.setToolTip(1, type_name)
        if display:
            item.setToolTip(2, display)
        self._add_child(parent, item)
        self._add_actions(item, value)

        if self._is_scalar(value):
            return

        obj_id = id(value)
        if obj_id in self._visited:
            item.setText(3, 'Already shown above')
            return
        self._visited.add(obj_id)

        children = self._iter_object_items(value)
        if not children:
            item.setText(2, display)
            return

        for child_name, child_value, comment in children:
            child = QTreeWidgetItem([child_name, type(child_value).__name__, '', comment])
            self._add_child(item, child)
            if self._is_scalar(child_value):
                child_display = self._safe_text(child_value)
                child.setText(2, child_display)
                child.setToolTip(2, child_display)
                self._add_actions(child, child_value)
            else:
                item.removeChild(child)
                self._add_value(child_name, child_value, item)

    def _add_actions(self, item: QTreeWidgetItem, value: Any) -> None:
        actions_method = getattr(value, 'actions', None)
        if not callable(actions_method):
            return
        try:
            actions = tuple(actions_method())
        except Exception:
            return
        if not actions:
            return

        holder = QWidget(self._tree)
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        icon_map = {
            'plot': QStyle.StandardPixmap.SP_FileDialogContentsView,
            'save': QStyle.StandardPixmap.SP_DialogSaveButton,
            'open': QStyle.StandardPixmap.SP_DialogOpenButton,
            'open_directory': QStyle.StandardPixmap.SP_DirOpenIcon,
            'edit': QStyle.StandardPixmap.SP_FileDialogDetailedView,
            'data': QStyle.StandardPixmap.SP_FileDialogDetailedView,
        }
        for action in actions:
            button = QToolButton(holder)
            button.setAutoRaise(True)
            button.setIcon(self.style().standardIcon(icon_map.get(action, QStyle.StandardPixmap.SP_FileIcon)))
            labels = {'data': 'View data', 'open_directory': 'Open containing directory'}
            button.setToolTip(labels.get(action, action.capitalize()))
            button.clicked.connect(lambda _checked=False, v=value, a=action: self._execute_action(v, a))
            layout.addWidget(button)
        layout.addStretch(1)
        self._tree.setItemWidget(item, 4, holder)

    def _execute_action(self, value: Any, action: str) -> None:
        try:
            method = getattr(value, action)
            result = method()
            if action in {'data', 'edit'}:
                dialog = ReadOnlyObjectDialog(result, title=f'View {value.name}', parent=self)
                self._child_dialogs.append(dialog)
                dialog.destroyed.connect(
                    lambda _obj=None, dlg=dialog: self._child_dialogs.remove(dlg)
                    if dlg in self._child_dialogs else None
                )
                dialog.show()
        except Exception as exc:
            QMessageBox.critical(self, 'Action Error', f"Failed to execute action '{action}':\n{exc}")


def show_readonly_object_dialog(value: Any, title: str = 'View Value', parent: Optional[QWidget] = None) -> ReadOnlyObjectDialog:
    dlg = ReadOnlyObjectDialog(value, title=title, parent=parent)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    return dlg


def select_input_parameters(
    atoms: Any,
    parent: Optional[QWidget] = None,
    task: str = "scf",
) -> Optional[InputParameters]:
    """Open the input-parameters editor and return the resulting InputParameters."""
    from importlib import import_module

    task_module = import_module(f"ase2sprkkr.input_parameters.definitions.{task.lower()}")
    params_def = task_module.input_parameters()
    params = params_def.create_object()
    return edit_input_parameters(params, parent=parent)
