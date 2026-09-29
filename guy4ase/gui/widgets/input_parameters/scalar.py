"""Grammar-aware scalar editors shared independently of dialog layout."""
from __future__ import annotations

import ast
from collections.abc import Callable
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
from PyQt6.QtCore import QSignalBlocker, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QLineEdit,
    QWidget,
)

from guy4ase.gui.input_parameters.defaults import default_text
from guy4ase.gui.input_parameters.energy import EnergyState
from guy4ase.gui.input_parameters.keyword_choices import (
    keyword_current_value,
    keyword_items,
)
from guy4ase.gui.input_parameters.specs.schema import FieldPlacement
from guy4ase.gui.widgets.input_parameters.commit import EditorCommit
from guy4ase.gui.widgets.input_parameters.energy import EnergyEditor
from guy4ase.gui.widgets.input_parameters.kpath import VectorEditor
from guy4ase.gui.widgets.nullable_spinbox import NullableDoubleSpinBox, NullableSpinBox


def coalesce(*args):
    for a in args:
        if a is not None:
            return a
    return None


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


def create_option_editor(
    grammar_type: Any,
    current_value: Any,
    on_value: Callable[[Any], None] | None = None,
    *,
    placement: FieldPlacement | None = None,
    read_only: bool = False,
    allow_empty: bool = False,
    option: Any = None,
    atoms: Any = None,
    parent: QWidget | None = None,
    session: Any = None,
    path: tuple[str, ...] | None = None,
    page_id: str | None = None,
    energy_state: Callable[[], EnergyState] | None = None,
    energy_apply: Callable[[float | None, str, bool], None] | None = None,
) -> QWidget:
    """Build an editor from grammar metadata and optional presentation overrides.

    ``option`` supplies optional/default and atom-dependent Keyword metadata;
    an array element's grammar alone does not inherit its parent's optionality.
    ``allow_empty`` makes blank fallback text a no-op, rather than an unset edit.
    Scalar editors require ``on_value``. Energy and vector editors use their
    own callbacks because they implement compound interactions.
    """
    if grammar_type is None:
        grammar_type = String()

    kind = placement.kind if placement is not None else "auto"
    if kind == "energy" or isinstance(grammar_type, Energy):
        read_energy_state = energy_state
        if read_energy_state is None:
            def read_energy_state():
                if isinstance(current_value, (list, tuple)) and len(current_value) == 2:
                    value, unit = current_value
                else:
                    value, unit = current_value, "Ry"
                return EnergyState(None if value is None else float(value), str(unit))
        apply_energy = energy_apply
        if apply_energy is None:
            raise ValueError("Energy editors require energy_apply")
        editor = EnergyEditor(
            read_energy_state,
            apply_energy,
            parent,
            with_reference=False,
            minimum=(placement.minimum if placement is not None and placement.minimum is not None else -1e9),
        )
        editor.number.setReadOnly(read_only)
        editor.units.setEnabled(not read_only)
        return editor

    if kind == "vector":
        if session is None or path is None or page_id is None:
            raise ValueError("Vector editors require a session, path, and page id")
        return VectorEditor(session, path, page_id, parent)

    if on_value is None:
        raise ValueError("Scalar editors require an on_value callback")

    whole_option = (
        placement is None
        and option is not None
        and option._definition.type is grammar_type
    )
    nullable = False
    if placement is not None:
        nullable = True
    elif whole_option:
        optional = option._definition.is_optional
        nullable = bool(optional(option) if callable(optional) else optional) or option.default_value is not None

    def show_numeric_default(editor):
        if whole_option:
            editor.lineEdit().setPlaceholderText(default_text(option.default_value))
            if not option.is_set() and option() is not None:
                with QSignalBlocker(editor):
                    editor.show_default(option(), default_text(option.default_value))

    def apply_number(editor, value):
        on_value(value)
        show_numeric_default(editor)

    def read_number(editor, value_type):
        if nullable and not editor.cleanText().strip() and not editor.is_default_display():
            return None
        value = value_type(editor.value())
        if nullable and value == value_type(editor.minimum()):
            return None
        if (placement is not None and placement.special_value_text
                and placement.minimum is not None
                and value == value_type(placement.minimum)):
            return None
        return value

    if kind == "integer" or isinstance(grammar_type, Integer):
        editor = NullableSpinBox(parent)
        if placement is not None:
            minimum = coalesce(placement.minimum, getattr(grammar_type, 'min', None), -2147483647)
            maximum = coalesce(placement.maximum, getattr(grammar_type, 'max', None), 2147483647)
            step = placement.step or 1
            if nullable:
                minimum -= int(step)
            editor.setSingleStep(int(step))
            if placement.special_value_text:
                editor.setSpecialValueText(placement.special_value_text)
        else:
            minimum = coalesce(getattr(grammar_type, 'min', None), np.iinfo(np.int32).min + int(nullable))
            maximum = coalesce(getattr(grammar_type, 'max', None), np.iinfo(np.int32).max)
        editor.setRange(minimum - int(nullable) if placement is None else minimum, maximum)
        if nullable:
            editor.set_unset_value(editor.minimum())
            editor.setValue(editor.minimum())
        try:
            if current_value is not None:
                editor.setValue(int(current_value))
        except Exception:
            pass
        editor.setReadOnly(read_only)
        show_numeric_default(editor)
        editor.setKeyboardTracking(False)
        commit = EditorCommit(
            editor,
            lambda: read_number(editor, int),
            lambda value: apply_number(editor, value),
        )
        editor.valueChanged.connect(commit.commit)
        return editor

    if kind == "real" or isinstance(grammar_type, Real):
        editor = NullableDoubleSpinBox(parent)
        lo = coalesce(placement.minimum if placement is not None else None, getattr(grammar_type, 'min', None), -1e16)
        hi = coalesce(placement.maximum if placement is not None else None, getattr(grammar_type, 'max', None), 1e16)
        decimals = placement.decimals if placement is not None else 8
        editor.setDecimals(decimals)
        if placement is not None:
            step = placement.step or .1
            lower = lo - float(step) if nullable else lo
            editor.setSingleStep(float(step))
            if placement.special_value_text:
                editor.setSpecialValueText(placement.special_value_text)
        else:
            lower = lo - max(1., abs(lo) * 1e-12) if nullable else lo
            editor.setSingleStep((hi - lo) / 1000.0 if hi - lo < 1e6 else 1.0)
        editor.setRange(lower, hi)
        if nullable:
            editor.set_unset_value(editor.minimum())
            editor.setValue(editor.minimum())
        try:
            if current_value is not None:
                editor.setValue(float(current_value))
        except Exception:
            pass
        editor.setReadOnly(read_only)
        show_numeric_default(editor)
        editor.setKeyboardTracking(False)
        commit = EditorCommit(
            editor,
            lambda: read_number(editor, float),
            lambda value: apply_number(editor, value),
        )
        editor.valueChanged.connect(commit.commit)
        return editor

    if kind == "boolean" or isinstance(grammar_type, (Boolean, Flag)):
        editor = QCheckBox(parent)
        try:
            editor.setChecked(bool(current_value))
        except Exception:
            pass
        if read_only:
            editor.setEnabled(False)
        commit = EditorCommit(editor, editor.isChecked, on_value)
        editor.toggled.connect(commit.commit)
        return editor

    if kind in {"choice", "keyword"} or isinstance(grammar_type, Keyword):
        editor = QComboBox(parent)
        current_value = keyword_current_value(option, grammar_type, current_value)
        current_index = -1
        if kind == "choice" and placement is not None:
            items = ((choice.value, choice.label) for choice in placement.choices)
        else:
            items = keyword_items(option, value_type=grammar_type, atoms=atoms)
            labels = {choice.value: choice.label for choice in placement.choices} if placement is not None else {}
            items = (
                (keyword, labels.get(keyword, info if keyword is None else
                 f"{keyword}: {info}" if info else str(keyword)))
                for keyword, info in items
            )
        for idx, (keyword, label) in enumerate(items):
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
        commit = EditorCommit(editor, editor.currentData, on_value)
        editor.currentIndexChanged.connect(commit.commit)
        if placement is not None and placement.descriptions:
            editor.view().setMinimumWidth(560)
        return editor

    editor = QLineEdit(parent)
    editor.setPlaceholderText(default_text(option.default_value) if whole_option else 'Not set')
    if current_value is not None and not (whole_option and not option.is_set()):
        editor.setText(_stringify_value(grammar_type, current_value, fallback=str(current_value)))
    editor.setReadOnly(read_only)

    def apply(text):
        if allow_empty and not text:
            return
        if kind == "literal":
            value = ast.literal_eval(text) if text else None
        else:
            try:
                value = grammar_type.parse(text) if text else None
            except Exception:
                value = grammar_type.convert(text)
                grammar_type.validate(value)
        on_value(value)
        if whole_option:
            editor.setPlaceholderText(default_text(option.default_value))
            if not option.is_set():
                editor.clear()

    commit = EditorCommit(editor, lambda: editor.text().strip(), apply)
    editor.editingFinished.connect(commit.commit)
    return editor
