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
    QWidget, QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox, QFileDialog, QLabel
)
from PyQt6.QtCore import Qt, QObject, pyqtSignal

from ase2sprkkr.input_parameters.input_parameters import InputParameters  # type: ignore
from ase2sprkkr.common.configuration_containers import Section  # type: ignore
from ase2sprkkr.common.grammar_types import (
    Integer, Real, Boolean, String, Keyword, Energy, Array
)  # type: ignore

# --- editor factory helpers ---


class _ValueChangedEvent(QObject):
    changed = pyqtSignal(object)


def _editor_integer(opt: Any, item: QTreeWidgetItem) -> QWidget:
    grammar_type = opt._definition.grammar_type
    current = opt._value
    ev = _ValueChangedEvent()
    try:
        min_v = getattr(grammar_type, 'min', None)
        max_v = getattr(grammar_type, 'max', None)
    except Exception:
        min_v = None
        max_v = None
    use_spin = (
        min_v is not None and max_v is not None
        and isinstance(min_v, int) and isinstance(max_v, int)
        and -2_000_000_000 <= min_v <= 2_000_000_000
        and -2_000_000_000 <= max_v <= 2_000_000_000
    )
    if use_spin:
        box = QSpinBox()
        box.setRange(min_v, max_v)
        try:
            box.setValue(int(current))
        except Exception:
            pass
        box.setToolTip(f"Integer range [{min_v}, {max_v}]")
        box.valueChanged.connect(lambda v: ev.changed.emit(int(v)))
        return box, ev

    edit = QLineEdit()
    if current is not None:
        edit.setText(str(current))
    rng_txt = (
        "(unbounded integer; expected magnitude up to ~1e16)"
        if min_v is None or max_v is None
        else f"[{min_v}, {max_v}]"
    )
    edit.setToolTip(f"Integer {rng_txt}")
    edit.textChanged.connect(lambda _t: ev.changed.emit(_get_editor_value(edit)))
    return edit, ev


def _editor_real(opt: Any, item: QTreeWidgetItem):
    grammar_type = opt._definition.grammar_type
    current = opt._value
    ev = _ValueChangedEvent()
    try:
        min_v = getattr(grammar_type, 'min', None)
        max_v = getattr(grammar_type, 'max', None)
    except Exception:
        min_v = None
        max_v = None
    lo = float(min_v) if isinstance(min_v, (int, float)) else -1e16
    hi = float(max_v) if isinstance(max_v, (int, float)) else 1e16
    box = QDoubleSpinBox()
    box.setDecimals(8)
    box.setRange(lo, hi)
    try:
        box.setValue(float(current))
    except Exception:
        pass
    box.setToolTip(
        f"Real range [{lo}, {hi}]" if (min_v is not None and max_v is not None) else "Unbounded real (~±1e16)"
    )
    box.valueChanged.connect(lambda v: ev.changed.emit(float(v)))
    return box, ev


def _editor_energy(opt: Any, item: QTreeWidgetItem):
    grammar_type = opt._definition.grammar_type
    current = opt._value
    ev = _ValueChangedEvent()
    try:
        min_v = getattr(grammar_type, 'min', None)
        max_v = getattr(grammar_type, 'max', None)
    except Exception:
        min_v = None
        max_v = None
    lo = float(min_v) if isinstance(min_v, (int, float)) else -1e16
    hi = float(max_v) if isinstance(max_v, (int, float)) else 1e16

    cont = QWidget()
    from PyQt6.QtWidgets import QHBoxLayout, QComboBox

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
    cont.setToolTip(f"Energy [{lo}, {hi}] units selectable")
    val_spin.valueChanged.connect(lambda _v: ev.changed.emit(_get_editor_value(cont)))
    unit_combo.currentTextChanged.connect(lambda _t: ev.changed.emit(_get_editor_value(cont)))
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
    keywords = getattr(grammar_type, 'keywords', None)
    if keywords and hasattr(keywords, '__iter__'):
        for kw in keywords:
            combo.addItem(str(kw))
        try:
            idx = combo.findText(str(current))
            if idx >= 0:
                combo.setCurrentIndex(idx)
        except Exception:
            pass
        combo.setToolTip("Keyword enum")
        combo.currentTextChanged.connect(lambda t: ev.changed.emit(t))
        return combo, ev

    edit = QLineEdit()
    if current is not None:
        edit.setText(str(current))
    edit.setToolTip("Keyword (no keyword list provided)")
    edit.textChanged.connect(lambda _t: ev.changed.emit(_get_editor_value(edit)))
    return edit, ev


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
    try:
        min_len = getattr(grammar_type, 'min_length', None)
        max_len = getattr(grammar_type, 'max_length', None)
        item_type = getattr(grammar_type, 'type', None)
        item_cls_name = item_type.__class__.__name__ if item_type is not None else '?'
    except Exception:
        min_len = None
        max_len = None
        item_type = None
        item_cls_name = '?'
    rng = f"[{min_len},{max_len}]" if (min_len is not None and max_len is not None) else "variable length"
    edit.setToolTip(f"Array of {item_cls_name} length {rng}; comma separated values")
    edit._array_item_type = item_type
    edit._array_min = min_len
    edit._array_max = max_len
    edit.textChanged.connect(lambda _t: ev.changed.emit(_get_editor_value(edit)))
    return edit, ev


def _editor_string(opt: Any, item: QTreeWidgetItem):
    current = opt._value
    ev = _ValueChangedEvent()
    edit = QLineEdit()
    if current is not None:
        edit.setText(str(current))
    edit.textChanged.connect(lambda _t: ev.changed.emit(_get_editor_value(edit)))
    return edit, ev


def _editor_unknown(opt: Any, item: QTreeWidgetItem):
    current = opt._value
    ev = _ValueChangedEvent()
    edit = QLineEdit()
    if current is not None:
        edit.setText(str(current))
    edit.textChanged.connect(lambda _t: ev.changed.emit(_get_editor_value(edit)))
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

def _get_editor_value(w: QWidget) -> Any:
    """Extract a python value from an editor widget created by _make_editor."""
    if isinstance(w, QSpinBox):
        return int(w.value())
    if isinstance(w, QDoubleSpinBox):
        return float(w.value())
    if isinstance(w, QCheckBox):
        return bool(w.isChecked())
    from PyQt6.QtWidgets import QComboBox
    if isinstance(w, QComboBox):
        return w.currentText()
    # Energy composite
    if hasattr(w, '_energy_value') and hasattr(w, '_energy_unit'):
        try:
            val = float(w._energy_value.value())
            unit = w._energy_unit.currentText()
            return (val, unit)
        except Exception:
            return None
    from PyQt6.QtWidgets import QLineEdit
    if hasattr(w, '_editor_child'):
        # composite path container
        return _get_editor_value(w._editor_child)  # type: ignore
    if isinstance(w, QLineEdit):
        # Array detection
        if hasattr(w,'_array_item_type'):
            raw = w.text().strip()
            if raw == '':
                return []
            parts = [p.strip() for p in raw.split(',')]
            # Simple conversion for numeric underlying types
            item_type = getattr(w,'_array_item_type',None)
            try:
                if item_type.__class__.__name__ in ('Integer','Real','Energy'):
                    out = []
                    for p in parts:
                        if item_type.__class__.__name__=='Integer':
                            out.append(int(p))
                        else:
                            out.append(float(p))
                    return out
            except Exception:
                pass
            return parts
        return w.text()
    return None


class InputParametersDialog(QDialog):
    def __init__(self, params: InputParameters, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._params = params
        self.setWindowTitle('Edit Input Parameters')
        self.resize(800, 600)
        self._tree = QTreeWidget()
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels(['Name', 'Type', 'Value'])
        self._build_tree()

        root = QVBoxLayout(self)
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

    def _build_tree(self) -> None:
        self._build_section(self._params)

    def _build_section(self, parent, treeitem = None) -> None:
        expert_parent: Optional[QTreeWidgetItem] = None
        # Iterate top-level sections
        for opt in parent:
            if isinstance(opt, Section):
                # Each section is iterable returning options / subsections
                sec_item = QTreeWidgetItem([opt.name])
                if treeitem is not None:
                    treeitem.addChild(sec_item)
                else:
                    self._tree.addTopLevelItem(sec_item)
                self._build_section(opt, sec_item)
            else:
                # Some entries may themselves be subsections; skip if not option-like
                is_expert = bool(getattr(opt._definition, 'expert', False))
                parent_item: Any = treeitem
                if is_expert:
                    if expert_parent is None:
                        if treeitem is None:
                            expert_parent = QTreeWidgetItem(["expert", "", ""])
                            self._tree.addTopLevelItem(expert_parent)
                        else:
                            expert_parent = QTreeWidgetItem(["expert", "", ""])
                            treeitem.addChild(expert_parent)
                    parent_item = expert_parent
                if parent_item is None:
                    item = QTreeWidgetItem([opt.name, str(opt._definition.grammar_type), ''])
                    self._tree.addTopLevelItem(item)
                else:
                    item = QTreeWidgetItem([opt.name, str(opt._definition.grammar_type), ''])
                    parent_item.addChild(item)
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
