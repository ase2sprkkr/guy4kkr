"""Grammar-aware scalar editors shared independently of dialog layout."""
from __future__ import annotations

from typing import Any

import numpy as np
from ase2sprkkr.common.grammar_types import (
    Array,
    Boolean,
    Energy,
    Flag,
    Integer,
    Keyword,
    Real,
    SetOf,
    String,
    Table,
)
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLineEdit,
    QWidget,
)

from guy4ase.gui.input_parameters.keyword_choices import (
    keyword_current_value,
    keyword_items,
)
from guy4ase.gui.widgets.nullable_spinbox import NullableDoubleSpinBox, NullableSpinBox


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


def create_scalar_editor(
    grammar_type: Any,
    current_value: Any,
    on_value: callable,
    *,
    read_only: bool = False,
    allow_empty: bool = False,
    option: Any = None,
    atoms: Any = None,
) -> QWidget:
    if grammar_type is None:
        grammar_type = String()

    nullable = False
    if option is not None and option._definition.type is grammar_type:
        optional = option._definition.is_optional
        nullable = bool(optional(option) if callable(optional) else optional) and option.default_value is None

    if isinstance(grammar_type, Integer):
        editor = NullableSpinBox()
        minimum = coalesce(getattr(grammar_type, 'min', None), np.iinfo(np.int32).min + int(nullable))
        editor.setRange(minimum - int(nullable), coalesce(getattr(grammar_type, 'max', None), np.iinfo(np.int32).max))
        if nullable:
            editor.set_unset_value(editor.minimum())
            editor.setValue(editor.minimum())
        try:
            if current_value is not None:
                editor.setValue(int(current_value))
        except Exception:
            pass
        editor.setReadOnly(read_only)
        editor.valueChanged.connect(lambda value: on_value(None if nullable and value == editor.minimum() else int(value)))
        return editor

    if isinstance(grammar_type, Real):
        editor = NullableDoubleSpinBox()
        lo = coalesce(getattr(grammar_type, 'min', None), -1e16)
        hi = coalesce(getattr(grammar_type, 'max', None), 1e16)
        editor.setDecimals(8)
        editor.setRange(lo - max(1., abs(lo) * 1e-12) if nullable else lo, hi)
        if nullable:
            editor.set_unset_value(editor.minimum())
            editor.setValue(editor.minimum())
        editor.setSingleStep((hi - lo) / 1000.0 if hi - lo < 1e6 else 1.0)
        try:
            if current_value is not None:
                editor.setValue(float(current_value))
        except Exception:
            pass
        editor.setReadOnly(read_only)
        editor.valueChanged.connect(lambda value: on_value(None if nullable and value == editor.minimum() else float(value)))
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
        current_value = keyword_current_value(option, grammar_type, current_value)
        current_index = -1
        for idx, (keyword, info) in enumerate(keyword_items(option, value_type=grammar_type, atoms=atoms)):
            label = info if keyword is None else f"{keyword}: {info}" if info else str(keyword)
            editor.addItem(label, keyword)
            editor.setItemData(idx, label, Qt.ItemDataRole.ToolTipRole)
            if current_value == keyword:
                current_index = idx
        if current_index == -1 and current_value is not None:
            editor.addItem(f"{current_value} (current value, unavailable)", current_value)
            current_index = editor.count() - 1
            editor.model().item(current_index).setEnabled(False)
        editor.setCurrentIndex(current_index)
        if read_only:
            editor.setEnabled(False)
        editor.currentIndexChanged.connect(lambda _index: on_value(editor.currentData()))
        return editor

    editor = QLineEdit()
    if nullable:
        editor.setPlaceholderText("Not set")
    if current_value is not None:
        editor.setText(_stringify_value(grammar_type, current_value, fallback=str(current_value)))
    editor.setReadOnly(read_only)

    def commit() -> None:
        text = editor.text().strip()
        if allow_empty and not text:
            _mark_editor_valid(editor)
            return
        try:
            value = grammar_type.parse(text) if text else None
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
