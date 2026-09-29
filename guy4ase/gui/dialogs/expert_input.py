"""Dialog to view and edit ase2sprkkr InputParameters."""
from __future__ import annotations

from collections.abc import Sequence as AbcSequence
from typing import Any, Optional

import numpy as np
from ase2sprkkr.common.configuration_containers import (
    Section,  # type: ignore
)
from ase2sprkkr.common.grammar_types import (  # type: ignore
    Array,
    Energy,
    SetOf,
    String,
    Table,
)
from ase2sprkkr.common.grammar_types import (
    Sequence as GrammarSequence,
)
from ase2sprkkr.input_parameters.input_parameters import InputParameters  # type: ignore
from PyQt6 import sip
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTreeWidgetItem,
    QWidget,
)

from guy4ase.gui.dialogs._tree_base import _TreeDialogBase
from guy4ase.gui.dialogs.input_file import InputFileEditor
from guy4ase.gui.input_parameters.bindings import InputParametersBinding
from guy4ase.gui.input_parameters.energy import (
    EnergyState,
    bound_energy_state,
    reference_selectable,
    set_bound_energy,
)
from guy4ase.gui.input_parameters.validation import validate_setup
from guy4ase.gui.widgets.input_parameters.energy import EnergyEditor
from guy4ase.gui.widgets.input_parameters.relativistic_scaling import (
    RelativisticScalingEditor,
)
from guy4ase.gui.widgets.input_parameters.scalar import create_option_editor
from guy4ase.gui.widgets.input_parameters.value_editor import ParameterValueEditor


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


class _TreeEditorBinding(InputParametersBinding):
    """Presentation adapter; parameter access stays in InputParametersBinding."""

    def __init__(self, dialog, item):
        self.dialog, self.item = dialog, item
        self.editor = None
        super().__init__(lambda: dialog._params, self._value_changed)

    def _value_changed(self, path):
        self.dialog._update_changed_style(self.option(path), self.item)
        self.refresh()

    def refresh(self):
        self.editor.refresh()
        self.item.setSizeHint(2, self.editor.sizeHint())
        self.dialog._tree.doItemsLayout()


class InputParametersDialog(_TreeDialogBase):
    """Edit an isolated parameter copy; only the accepted result is published."""
    _CHANGED_ROLE = Qt.ItemDataRole.UserRole
    _VALUE_EDITOR_ROLE = Qt.ItemDataRole.UserRole + 2

    def __init__(
        self,
        params: InputParameters,
        parent: Optional[QWidget] = None,
        *,
        show_changed_only: bool = False,
        calculate_mode: bool = False,
        directory: Optional[str] = None,
        atoms: Any = None,
    ):
        self._params = params.copy(copy_values=True)
        self._atoms = atoms
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
        self.edit_input_btn = self._add_footer_button('Edit input file…', self._edit_input_file)
        self.cancel_btn = self._add_footer_button('Cancel', self.reject)
        self.ok_btn = self._add_footer_button('Calculate' if calculate_mode else 'OK', self._on_ok)
        self._editor_error = QLabel(self)
        self._editor_error.setWordWrap(True)
        self._editor_error.hide()
        self._root_layout.insertWidget(self._root_layout.count() - 1, self._editor_error)
        self._build_tree()
        self._changed_only_checkbox.setChecked(show_changed_only)

    def _build_tree(self) -> None:
        self._special_editors = {}
        self._editor_errors = {}
        self._editor_error.hide()
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
            if parent.name == 'ENERGY' and opt.name in ('EMINEV', 'EMAXEV') and opt.name[:-2] in parent:
                continue  # One shared editor for each absolute/relative pair.
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
        grammar_type = opt._definition.type
        info = opt.info
        type_text = str(grammar_type)
        item = QTreeWidgetItem([opt.name, type_text, '', info])
        item.setToolTip(1, type_text)
        item.setToolTip(3, info)
        self._add_child(parent_item, item)
        self._update_changed_style(opt, item, refresh_filter=False)

        path = tuple(opt._get_path().split('.'))
        if path[0] == 'ENERGY' and opt.name in ('EMIN', 'EMAX') and opt.name + 'EV' in opt._container:
            self._build_energy_option(opt, item, path, paired=True)
        elif isinstance(grammar_type, Energy):
            self._build_energy_option(opt, item, path)
        elif path in {('MODE', 'C'), ('MODE', 'SOC')}:
            self._build_scaling_option(opt, item, path)
        elif isinstance(grammar_type, (Array, SetOf)):
            self._build_array_option(opt, item, grammar_type)
        elif isinstance(grammar_type, GrammarSequence):
            self._build_sequence_option(opt, item, grammar_type)
        elif isinstance(grammar_type, Table):
            self._build_table_option(opt, item, grammar_type)
        else:
            value = _option_value(opt)
            editor = create_option_editor(
                grammar_type,
                value,
                lambda new_value, o=opt, option_item=item: self._set_option_value(o, option_item, new_value),
                option=opt,
                atoms=self._atoms,
            )
            self._set_editor(item, editor, '.'.join(path))

    def _build_energy_option(self, opt, item, path, paired=False):
        binding = _TreeEditorBinding(self, item)
        if paired:
            name = opt.name
            item.setText(0, f'{name} / {name}EV')
            item.setData(0, Qt.ItemDataRole.UserRole + 1, ('ENERGY', name + 'EV'))
            item.setText(1, 'Energy')
            item.setToolTip(3, opt.info + '\n' + opt._container[name + 'EV'].info)
            def apply(value, unit, relative):
                set_bound_energy(self._params, name, value, unit, relative)
                self._update_changed_style(binding.option(path), item)
                self._refresh_energy_editors()
            editor = EnergyEditor(lambda: bound_energy_state(self._params, name), apply, self._tree,
                                  reference_selectable=lambda: reference_selectable(self._params, name))
        else:
            def state():
                value = binding.value(path)
                return EnergyState(None if value is None else float(value.to_value('Ry')), 'Ry',
                                   explicit=binding.option(path).is_set())
            def apply(value, unit, _relative):
                binding.set_value(path, None if value is None else (value, unit))
            editor = create_option_editor(
                opt._definition.type,
                None,
                editor_kind="energy",
                parent=self._tree,
                energy_state=state,
                energy_apply=apply,
            )
        binding.editor = editor
        editor.setMinimumWidth(320)
        self._special_editors[path] = (binding, item)
        self._set_editor(item, editor, '.'.join(path))
        self._tree.setColumnWidth(2, max(320, self._tree.columnWidth(2)))
        binding.refresh()
        self._update_changed_style(opt, item, refresh_filter=False)

    def _refresh_energy_editors(self):
        for binding, _item in self._special_editors.values():
            if isinstance(binding.editor, EnergyEditor):
                binding.refresh()

    def _build_scaling_option(self, opt, item, path):
        binding = _TreeEditorBinding(self, item)
        editor = RelativisticScalingEditor(binding, path, 'expert', self._tree)
        binding.editor = editor
        editor.setMinimumWidth(280)
        self._special_editors[path] = (binding, item)
        self._set_editor(item, editor, '.'.join(path))
        self._tree.setColumnWidth(2, max(280, self._tree.columnWidth(2)))
        binding.refresh()

    def _set_option_value(self, opt: Any, item: QTreeWidgetItem, value: Any) -> None:
        opt.set(value)
        self._update_changed_style(opt, item)
        self._refresh_energy_editors()

    def _update_changed_style(
        self,
        opt: Any,
        item: QTreeWidgetItem,
        *,
        refresh_filter: bool = True,
    ) -> None:
        try:
            changed = bool(opt.is_changed())
            paired = item.data(0, Qt.ItemDataRole.UserRole + 1)
            if paired:
                changed = changed or self._params[paired[0]][paired[1]].is_changed()
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
        """Show a compound value's grammar text alongside its structured child editors."""
        def apply(value):
            opt.set(value)
            self._update_changed_style(opt, item)
            self._rebuild_compound_option(opt, item)
        editor = create_option_editor(grammar_type, _option_value(opt), apply,
                          option=opt, atoms=self._atoms, read_only=not editable)
        self._set_editor(item, editor)
        item.setToolTip(2, editor.text())

    def _set_editor(self, item, editor, error_label=None):
        """Install a control and surface value-editor validation uniformly."""
        if not isinstance(editor, ParameterValueEditor):
            raise TypeError("Expert value controls must implement ParameterValueEditor")
        item.setData(0, self._VALUE_EDITOR_ROLE, True)
        self._tree.setItemWidget(item, 2, editor)
        editor.validationChanged.connect(
            lambda message: self._display_editor_error(
                item, error_label or item.text(0), message))

    def _display_editor_error(self, item, label, message):
        key = id(item)
        if message:
            self._editor_errors[key] = (item, label, message)
        else:
            self._editor_errors.pop(key, None)
        self._refresh_editor_errors()

    def _refresh_editor_errors(self):
        self._editor_errors = {
            key: (item, label, error)
            for key, (item, label, error) in self._editor_errors.items()
            if not sip.isdeleted(item)
        }
        messages = list(
            f"{label}: {error}"
            for _item, label, error in self._editor_errors.values()
        )
        self._editor_error.setText('\n'.join(messages))
        self._editor_error.setVisible(bool(messages))

    def _editor_widgets(self):
        """Snapshot registered value editors; a commit may rebuild child rows."""
        def walk(item):
            if item.data(0, self._VALUE_EDITOR_ROLE):
                yield item, self._tree.itemWidget(item, 2)
            for index in range(item.childCount()):
                yield from walk(item.child(index))
        return list(walk(self._tree.invisibleRootItem()))

    def _build_array_option(self, opt: Any, item: QTreeWidgetItem, grammar_type: Any) -> None:
        self._build_summary_editor(opt, item, grammar_type, editable=True)
        values = _mutable_sequence(_option_value(opt))
        for index, value in enumerate(values):
            child = QTreeWidgetItem([f'[{index}]', str(grammar_type.type), '', ''])
            self._add_child(item, child)
            editor = create_option_editor(
                grammar_type.type,
                value,
                lambda new_value, idx=index, o=opt, parent_item=item: self._update_array_value(o, parent_item, idx, new_value),
                option=opt,
                atoms=self._atoms,
            )
            self._set_editor(child, editor)

        max_length = getattr(grammar_type, 'max_length', None)
        if max_length is None or len(values) < max_length:
            append_item = QTreeWidgetItem([f'[{len(values)}]', str(grammar_type.type), '', 'Append new item'])
            self._add_child(item, append_item)
            editor = create_option_editor(
                grammar_type.type,
                None,
                lambda new_value, idx=len(values), o=opt, parent_item=item: self._update_array_value(o, parent_item, idx, new_value),
                allow_empty=True,
                option=opt,
                atoms=self._atoms,
            )
            self._set_editor(append_item, editor)

    def _update_array_value(self, opt: Any, item: QTreeWidgetItem, index: int, value: Any) -> None:
        values = _mutable_sequence(_option_value(opt))
        if index < len(values):
            values[index] = value
        else:
            values.append(value)
        opt.set(values)
        self._update_changed_style(opt, item)
        self._rebuild_compound_option(opt, item)
        self._refresh_energy_editors()

    def _build_sequence_option(self, opt: Any, item: QTreeWidgetItem, grammar_type: GrammarSequence) -> None:
        self._build_summary_editor(opt, item, grammar_type, editable=True)
        values = _mutable_sequence(_option_value(opt))
        labels = _reverse_names_map(getattr(grammar_type, 'names', None), len(grammar_type.types))
        for index, subtype in enumerate(grammar_type.types):
            value = values[index] if index < len(values) else None
            child = QTreeWidgetItem([labels[index], str(subtype), '', ''])
            self._add_child(item, child)
            editor = create_option_editor(
                subtype,
                value,
                lambda new_value, idx=index, o=opt, parent_item=item: self._update_sequence_value(o, parent_item, idx, new_value),
            )
            self._set_editor(child, editor)

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
                    editor = create_option_editor(
                        subtype,
                        cell_value,
                        lambda new_value, r=row_index, c=column_name, o=opt, parent_item=item: self._update_table_field(o, parent_item, r, c, new_value),
                    )
                    self._set_editor(cell_item, editor)
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
                editor = create_option_editor(
                    subtype,
                    cell_value,
                    lambda new_value, r=row_index, c=col_index, o=opt, parent_item=item: self._update_table_cell(o, parent_item, r, c, new_value),
                )
                self._set_editor(cell_item, editor)

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

    def _edit_input_file(self) -> None:
        """Rebuild from parsed input, restoring the previous model if rebuilding fails."""
        focus = QApplication.focusWidget()
        if focus is not None:
            focus.clearFocus()
        try:
            def apply(parameters):
                previous = self._params
                self._params = parameters
                try:
                    self._build_tree()
                except Exception:
                    self._params = previous
                    self._build_tree()
                    raise
            editor = InputFileEditor(self._params, self, apply_parameters=apply)
            editor.exec()
        except Exception as exc:
            QMessageBox.critical(self, 'Input File Error', str(exc))

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
        focus = QApplication.focusWidget()
        if focus is not None:
            focus.clearFocus()
        self._editor_error.hide()
        for item, editor in self._editor_widgets():
            if editor is None or sip.isdeleted(editor) or sip.isdeleted(item):
                continue
            if not editor.commit():
                self._filter_edit.clear()
                self._changed_only_checkbox.setChecked(False)
                parent = item.parent()
                while parent is not None:
                    parent.setExpanded(True)
                    parent = parent.parent()
                self._tree.scrollToItem(item)
                editor.setFocus()
                return
        try:
            validate_setup(self._params)
        except Exception as error:
            self._editor_error.setText(str(error))
            self._editor_error.show()
            return
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
    atoms: Any = None,
) -> Any:
    """Open the expert editor, returning parameters (optionally directory) or None.

    The supplied object is never modified. Cancel discards the isolated draft;
    callers must use the returned object on acceptance.
    """
    dlg = InputParametersDialog(
        params,
        parent=parent,
        show_changed_only=show_changed_only,
        calculate_mode=calculate_mode,
        directory=directory,
        atoms=atoms,
    )
    code = dlg.exec()
    if code == QDialog.DialogCode.Accepted:
        if return_directory:
            return dlg.result(), dlg.directory()
        return dlg.result()
    return None


def select_input_parameters(
    atoms: Any,
    parent: Optional[QWidget] = None,
    task: str = "scf",
) -> Optional[InputParameters]:
    """Create fresh parameters for a task and edit them; do not load existing state."""
    from importlib import import_module

    task_module = import_module(f"ase2sprkkr.input_parameters.definitions.{task.lower()}")
    params_def = task_module.input_parameters()
    params = params_def.create_object()
    return edit_input_parameters(params, parent=parent, atoms=atoms)
