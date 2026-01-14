"""Dialog to view and edit ase2sprkkr InputParameters.

First pass implementation:
- Uses QTreeWidget: top-level items are sections.
- Each section shows its non-expert options directly; expert options placed under a child item named "expert".
- Option rows display name, type, and an editor widget appropriate for grammar_type.
- Unknown types fall back to plain text entry.
- On accept, values are written back to the original InputParameters object.

This file avoids importing heavy ase2sprkkr modules until a dialog is actually used.
"""
from __future__ import annotations

from typing import Any, Optional, Dict

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTreeWidget, QTreeWidgetItem,
    QWidget, QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox, QFileDialog, QLabel,
    QComboBox
)
from PyQt6.QtCore import Qt, QObject, pyqtSignal
import numpy as np

from ase2sprkkr.input_parameters.input_parameters import InputParameters  # type: ignore
from ase2sprkkr.common.configuration_containers import Section  # type: ignore
from ase2sprkkr.common.grammar_types import (
    Integer, Real, Boolean, String, Keyword, Energy, Array
)  # type: ignore


class _ValueChangedEvent(QObject):
    changed = pyqtSignal(object)

def coalesce(*args):
    for a in args:
        if a is not None:
            return a
    return None

def _editor_integer(opt: Any, item: QTreeWidgetItem) -> QWidget:
    grammar_type = opt._definition.grammar_type
    current = opt._value
    ev = _ValueChangedEvent()
    lo = coalesce(grammar_type.min, np.iinfo(np.int32).min)
    hi = coalesce(grammar_type.max, np.iinfo(np.int32).max)
    box = QSpinBox()
    box.setRange(lo,hi)
    try:
        box.setValue(int(opt._value))
    except Exception:
        pass
    box.valueChanged.connect(lambda v: ev.changed.emit(v))
    return box, ev

def _editor_real(opt: Any, item: QTreeWidgetItem):
    grammar_type = opt._definition.grammar_type
    ev = _ValueChangedEvent()
    lo = coalesce(grammar_type.min, -1e16)
    hi = coalesce(grammar_type.max, 1e16)
    box = QDoubleSpinBox()
    box.setDecimals(8)
    box.setRange(lo, hi)
    box.setSingleStep((hi - lo) / 1000.0 if hi - lo < 1e6 else 1.0)
    try:
        box.setValue(opt._value)
    except Exception:
        pass
    box.valueChanged.connect(lambda v: ev.changed.emit(float(v)))
    return box, ev

def _editor_energy(opt: Any, item: QTreeWidgetItem):
    grammar_type = opt._definition.grammar_type
    current = opt._value
    ev = _ValueChangedEvent()
    lo = coalesce(grammar_type.min, -1e16)
    hi = coalesce(grammar_type.max, 1e16)

    cont = QWidget()
    h = QHBoxLayout(cont)
    h.setContentsMargins(0, 0, 0, 0)
    val_spin = QDoubleSpinBox()
    val_spin.setDecimals(8)
    val_spin.setRange(lo, hi)
    val_spin.setSingleStep((hi - lo) / 1000.0 if hi - lo < 1e6 else 1.0)
    try:
        if isinstance(current, (tuple, list)) and len(current) == 2:
            val_spin.setValue(float(current[0]))
        elif current is not None:
            val_spin.setValue(float(current))
    except Exception:
        pass
    units = getattr(grammar_type, 'units', {}) or {}
    unit_combo = QComboBox()
    for key in units.keys():
        unit_combo.addItem(str(key))
    try:
        if isinstance(current, (tuple, list)) and len(current) == 2:
            idx = unit_combo.findText(str(current[1]))
            if idx >= 0:
                unit_combo.setCurrentIndex(idx)
    except Exception:
        pass
    h.addWidget(val_spin, 3)
    h.addWidget(unit_combo, 1)
    cont._energy_value = val_spin
    cont._energy_unit = unit_combo

    def _get_energy_value():
        return (val_spin.value(), unit_combo.currentText())

    val_spin.valueChanged.connect(lambda _v: ev.changed.emit(_get_energy_value()))
    unit_combo.currentTextChanged.connect(lambda _t: ev.changed.emit(_get_energy_value()))
    return cont, ev


def _editor_boolean(opt: Any, item: QTreeWidgetItem):
    current = opt._value
    ev = _ValueChangedEvent()
    cb = QCheckBox()
    try:
        cb.setChecked(bool(current))
    except Exception:
        pass
    cb.toggled.connect(lambda v: ev.changed.emit(bool(v)))
    return cb, ev


def _editor_keyword(opt: Any, item: QTreeWidgetItem):
    grammar_type = opt._definition.grammar_type
    current = opt._value
    ev = _ValueChangedEvent()
    from PyQt6.QtWidgets import QComboBox

    combo = QComboBox()
    for kw, info in grammar_type.items():
        if info is None:
            info = str(kw)
        else:
            info = str(kw) + ": " + str(info)
        combo.addItem(info, kw)
        if current == kw:
            combo.setCurrentIndex(combo.count() - 1)
    combo.currentTextChanged.connect(lambda t: ev.changed.emit(t))
    return combo, ev


def _editor_array(opt: Any, item: QTreeWidgetItem):
    grammar_type = opt._definition.grammar_type
    current = opt._value
    ev = _ValueChangedEvent()
    edit = QLineEdit()
    if current is not None:
        if isinstance(current, (list, tuple)):
            edit.setText(",".join(map(str, current)))
        else:
            edit.setText(str(current))
    edit.textChanged.connect(lambda _t: ev.changed.emit(_get_editor_value(edit)))
    return edit, ev


def _editor_unknown(opt: Any, item: QTreeWidgetItem):
    grammar_type = opt._definition.grammar_type
    current = opt._value
    ev = _ValueChangedEvent()
    edit = QLineEdit()
    if current is not None:
        edit.setText(str(current))
    edit.textChanged.connect(lambda _t: ev.changed.emit(_get_editor_value(edit)))
    return edit, ev


def _editor_string(opt: Any, item: QTreeWidgetItem):
    current = opt._value
    ev = _ValueChangedEvent()
    edit = QLineEdit()
    if current is not None:
        edit.setText(str(current))

    def changed(_t: str):
        try:
            out = opt._definition.grammar_type.parse(_t)
        except Exception as e:
            edit.setStyleSheet("border: 2px solid red;")
            edit.setToolTip(str(e))
        else:
            edit.setStyleSheet("")
            edit.setToolTip("")
            ev.changed.emit(out)

    edit.textChanged.connect(changed)
    return edit, ev

_EDITOR_DISPATCH = {
    Integer: _editor_integer,
    Real: _editor_real,
    Energy: _editor_energy,
    Boolean: _editor_boolean,
    Keyword: _editor_keyword,
    Array: _editor_array,
    String: _editor_string,
}


def _make_editor(opt: Any, item: QTreeWidgetItem):
    grammar_type = getattr(getattr(opt, '_definition', None), 'grammar_type', None)
    cls = grammar_type.__class__ if grammar_type is not None else None
    fn = _EDITOR_DISPATCH.get(cls, _editor_unknown)
    editor, ev = fn(opt, item)
    # Keep event alive; caller may also access via `editor._changed_event.changed`.
    editor._changed_event = ev
    return editor, ev

class InputParametersDialog(QDialog):
    def __init__(self, params: InputParameters, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._params = params
        self.setWindowTitle('Edit Input Parameters')
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
        self._build_tree()

        root = QVBoxLayout(self)
        header = QWidget(self)
        header_l = QHBoxLayout(header)
        header_l.setContentsMargins(0, 0, 0, 0)
        header_l.addWidget(QLabel("Search:"))
        header_l.addWidget(self._filter_edit, 1)
        header_l.addWidget(self._filter_clear_btn)
        header_l.addStretch(1)
        header_l.addWidget(self._expand_all_btn)
        header_l.addWidget(self._collapse_all_btn)
        root.addWidget(header, 0)
        root.addWidget(self._tree, 1)
        btns = QHBoxLayout()
        btns.addStretch(1)
        self.cancel_btn = QPushButton('Cancel')
        self.cancel_btn.clicked.connect(self.reject)
        btns.addWidget(self.cancel_btn)
        self.ok_btn = QPushButton('OK')
        self.ok_btn.clicked.connect(self._on_ok)
        btns.addWidget(self.ok_btn)
        root.addLayout(btns)

        self._filter_edit.textChanged.connect(self._apply_filter)
        self._filter_clear_btn.clicked.connect(self._clear_filter)
        self._expand_all_btn.clicked.connect(self._tree.expandAll)
        self._collapse_all_btn.clicked.connect(self._tree.collapseAll)

    def _clear_filter(self) -> None:
        self._filter_edit.setText("")
        self._filter_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _apply_filter(self, text: str) -> None:
        needle = (text or "").strip().lower()

        def visit(item: QTreeWidgetItem) -> bool:
            if not needle:
                for i in range(item.childCount()):
                    visit(item.child(i))
                item.setHidden(False)
                return True

            self_match = needle in (item.text(0) or "").lower()
            child_match = False
            for i in range(item.childCount()):
                if visit(item.child(i)):
                    child_match = True
            visible = self_match or child_match
            item.setHidden(not visible)
            return visible

        for i in range(self._tree.topLevelItemCount()):
            visit(self._tree.topLevelItem(i))

    def _build_tree(self) -> None:
        self._build_section(self._params)

    def _build_section(self, parent, treeitem = None) -> None:

        _expert_parent: Optional[QTreeWidgetItem] = None

        def add(parent_item, child_item):
            if parent_item is None:
                self._tree.addTopLevelItem(child_item)
            else:
                parent_item.addChild(child_item)
        def expert_parent() -> QTreeWidgetItem:
            nonlocal _expert_parent
            if _expert_parent is None:
                _expert_parent = QTreeWidgetItem(["expert", "", "", "Expert options"])
                add(treeitem, _expert_parent)
            return _expert_parent

        # Iterate top-level sections
        for opt in parent:
            if isinstance(opt, Section):
                # Each section is iterable returning options / subsections
                info = opt.info
                sec_item = QTreeWidgetItem([opt.name, "", "", info])
                sec_item.setToolTip(3, info)
                font = sec_item.font(0)
                font.setBold(True)
                sec_item.setFont(0, font)
                add(treeitem, sec_item)
                self._build_section(opt, sec_item)
            else:
                # Some entries may themselves be subsections; skip if not option-like
                is_expert = bool(getattr(opt._definition, 'expert', False))
                parent_item: Any = treeitem
                if is_expert:
                    parent_item = expert_parent()
                info = opt.info
                typ = str(opt._definition.grammar_type)
                item = QTreeWidgetItem([opt.name, typ, '', info])
                item.setToolTip(1, typ)
                item.setToolTip(3, info)
                add(parent_item, item)
                # Editor widget
                editor, ev = _make_editor(opt, item)
                self._tree.setItemWidget(item, 2, editor)
        self._tree.expandAll()

    def _on_ok(self) -> None:
        # write back values
        self.accept()

    def result(self) -> Optional[InputParameters]:
        return getattr(self, '_params', None)


def edit_input_parameters(params: InputParameters, parent: Optional[QWidget] = None) -> Optional[InputParameters]:
    dlg = InputParametersDialog(params, parent=parent)
    code = dlg.exec()
    if code == QDialog.DialogCode.Accepted:
        return dlg.result()
    return None


def select_input_parameters(atoms: Any, parent: Optional[QWidget] = None) -> Optional[InputParameters]:
    """Open the input-parameters editor and return the resulting InputParameters.

    Current implementation uses default SCF input parameters. Atom-dependent wiring
    can be added later.
    """
    # Keep heavy imports local.
    from ase2sprkkr.input_parameters.definitions import scf

    params_def = scf.input_parameters()
    params = params_def.create_object()
    return edit_input_parameters(params, parent=parent)
