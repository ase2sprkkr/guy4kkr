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
from PyQt6.QtWidgets import QCheckBox, QComboBox, QLineEdit, QWidget

from guy4ase.gui.input_parameters.defaults import default_text
from guy4ase.gui.input_parameters.energy import EnergyState, convert_energy
from guy4ase.gui.input_parameters.field_binding import FieldValue
from guy4ase.gui.input_parameters.keyword_choices import (
    keyword_allows_unset,
    keyword_items,
)
from guy4ase.gui.input_parameters.specs.schema import FieldPlacement
from guy4ase.gui.widgets.input_parameters.commit import EditorCommit
from guy4ase.gui.widgets.input_parameters.energy import EnergyEditor
from guy4ase.gui.widgets.input_parameters.kpath import VectorEditor
from guy4ase.gui.widgets.input_parameters.value_editor import ParameterValueEditor
from guy4ase.gui.widgets.nullable_spinbox import (
    NullableDoubleSpinBox,
    NullableSpinBox,
)


def coalesce(*args):
    for value in args:
        if value is not None:
            return value
    return None


def _first(value: Any, fallback: Any = None) -> Any:
    if isinstance(value, np.ndarray):
        return value.flat[0] if value.size else fallback
    if isinstance(value, (list, tuple)):
        return value[0] if value else fallback
    return fallback if value is None else value


def _plain_literal(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return _plain_literal(value.tolist())
    if isinstance(value, dict):
        return {key: _plain_literal(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain_literal(child) for child in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def _stringify_value(grammar_type: Any, value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    if isinstance(value, np.ndarray) and not isinstance(
        grammar_type, (Array, SetOf, Table)
    ):
        return "<Data>"
    try:
        return str(grammar_type.string(value))
    except Exception:
        try:
            return str(value)
        except Exception:
            return fallback


class _ScalarValueEditor(ParameterValueEditor):
    """Lifecycle implementation shared by concrete scalar Qt controls."""

    def bind(
        self,
        read_state: Callable[[], FieldValue],
        apply_value: Callable[[Any], None],
    ) -> None:
        self._read_state = read_state
        self._apply_value = apply_value
        self._commit = EditorCommit(self, self._draft, self._apply_draft)
        self.refresh()

    @property
    def validationChanged(self):
        return self._commit.validationChanged

    def refresh(self) -> None:
        with QSignalBlocker(self):
            self._show_state(self._read_state())
        self._commit.refresh()

    def commit(self, *_args: Any) -> bool:
        return self._commit.commit()

    def _draft(self) -> Any:
        raise NotImplementedError

    def _apply_draft(self, value: Any) -> None:
        self._apply_value(value)
        self._sync_display()

    def _sync_display(self) -> None:
        """Re-read the authoritative value after a successful callback."""
        with QSignalBlocker(self):
            self._show_state(self._read_state())

    def _show_state(self, state: FieldValue) -> None:
        raise NotImplementedError


class IntegerEditor(NullableSpinBox, _ScalarValueEditor):
    """Nullable integer input with backend-default placeholder support."""

    def __init__(self, *, nullable: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._nullable = nullable

    def _draft(self) -> int | None:
        if (
            self._nullable
            and not self.cleanText().strip()
            and not self.is_default_display()
        ):
            return None
        value = int(self.value())
        return None if self._nullable and value == int(self.minimum()) else value

    def _show_state(self, state: FieldValue) -> None:
        fallback = self.minimum() if self._nullable else 0
        value = int(_first(state.value, fallback))
        self.setValue(value)
        placeholder = default_text(state.default)
        self.lineEdit().setPlaceholderText(placeholder)
        if state.implicit_default and state.value is not None:
            self.show_default(value, placeholder)


class RealEditor(NullableDoubleSpinBox, _ScalarValueEditor):
    """Nullable real input with backend-default placeholder support."""

    def __init__(self, *, nullable: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._nullable = nullable

    def _draft(self) -> float | None:
        if (
            self._nullable
            and not self.cleanText().strip()
            and not self.is_default_display()
        ):
            return None
        value = float(self.value())
        return None if self._nullable and value == float(self.minimum()) else value

    def _show_state(self, state: FieldValue) -> None:
        fallback = self.minimum() if self._nullable else 0.0
        value = float(_first(state.value, fallback))
        self.setValue(value)
        placeholder = default_text(state.default)
        self.lineEdit().setPlaceholderText(placeholder)
        if state.implicit_default and state.value is not None:
            self.show_default(value, placeholder)


class BooleanEditor(QCheckBox, _ScalarValueEditor):
    """Boolean/flag value editor."""

    def _draft(self) -> bool:
        return self.isChecked()

    def _show_state(self, state: FieldValue) -> None:
        self.setChecked(bool(state.value))


class ChoiceEditor(QComboBox, _ScalarValueEditor):
    """Choice editor which preserves imported values absent from the schema."""

    def __init__(
        self,
        *,
        normalize: Callable[[FieldValue], Any],
        unavailable_unknown: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._normalize = normalize
        self._unavailable_unknown = unavailable_unknown

    def _draft(self) -> Any:
        return self.currentData()

    def _show_state(self, state: FieldValue) -> None:
        value = self._normalize(state)
        for index in range(self.count()):
            if self.itemData(index) == value:
                self.setCurrentIndex(index)
                return
        if value is None:
            self.setCurrentIndex(-1)
            self.setPlaceholderText("Not set")
            return
        label = (
            f"{value} (current value, unavailable)"
            if self._unavailable_unknown
            else str(value)
        )
        self.addItem(label, value)
        if self._unavailable_unknown:
            self.model().item(self.count() - 1).setEnabled(False)
        self.setCurrentIndex(self.count() - 1)


class TextEditor(QLineEdit, _ScalarValueEditor):
    """Text/literal fallback editor using the input grammar for conversion."""

    def __init__(
        self,
        grammar_type: Any,
        *,
        kind: str,
        nullable: bool,
        allow_empty: bool,
        option: Any,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._grammar_type = grammar_type
        self._kind = kind
        self._nullable = nullable
        self._allow_empty = allow_empty
        self._option = option

    def _draft(self) -> str:
        return self.text().strip()

    def _apply_draft(self, text: str) -> None:
        if not text:
            if self._allow_empty:
                return
            if self._nullable:
                self._apply_value(None)
                self._sync_display()
                return
            option_name = getattr(self._option, "name", "Value")
            raise ValueError(f"{option_name} must have a value")
        if self._kind == "literal":
            value = self._grammar_type.convert(ast.literal_eval(text))
        elif isinstance(self._grammar_type, String):
            value = self._grammar_type.convert(text)
        else:
            value = self._grammar_type.parse(text)
        self._grammar_type.validate(value)
        self._apply_value(value)
        self._sync_display()

    def _show_state(self, state: FieldValue) -> None:
        value = None if state.implicit_default else state.value
        if self._kind == "literal" and value is not None:
            text = repr(_plain_literal(value))
        else:
            text = _stringify_value(
                self._grammar_type,
                value,
                fallback="" if value is None else str(value),
            )
        self.setText(text)
        self.setPlaceholderText(default_text(state.default))


def create_option_editor(
    grammar_type: Any,
    current_value: Any,
    on_value: Callable[[Any], None] | None = None,
    *,
    editor_kind: str = "auto",
    placement: FieldPlacement | None = None,
    read_only: bool = False,
    allow_empty: bool = False,
    option: Any = None,
    atoms: Any = None,
    parent: QWidget | None = None,
    session: Any = None,
    path: tuple[str, ...] | None = None,
    page_id: str | None = None,
    read_state: Callable[[], FieldValue] | None = None,
    energy_state: Callable[[], EnergyState] | None = None,
    energy_apply: Callable[[float | None, str, bool], None] | None = None,
) -> ParameterValueEditor:
    """Create the sole lifecycle-aware editor selected for one grammar value."""
    if grammar_type is None:
        grammar_type = String()

    kind = editor_kind
    if kind == "energy":
        read_energy_state = energy_state
        if read_energy_state is None:

            def read_energy_state():
                state = read_state() if read_state is not None else None
                source_value = state.value if state is not None else current_value
                if isinstance(source_value, (list, tuple)) and len(source_value) == 2:
                    value, unit = source_value
                else:
                    value, unit = source_value, "Ry"
                if hasattr(value, "to_value"):
                    value, unit = value.to_value("Ry"), "Ry"
                return EnergyState(
                    None if value is None else float(value),
                    str(unit),
                    explicit=state.explicit if state is not None else True,
                )

        if energy_apply is None:
            if on_value is None:
                raise ValueError("Energy editors require an on_value callback")

            def energy_apply(value, unit, _relative):
                if value is None:
                    converted = None
                elif isinstance(grammar_type, Energy):
                    converted = (value, unit)
                else:
                    converted = convert_energy(value, unit, "Ry")
                on_value(converted)
        editor = EnergyEditor(
            read_energy_state,
            energy_apply,
            parent,
            with_reference=False,
            minimum=(
                placement.minimum
                if placement is not None and placement.minimum is not None
                else -1e9
            ),
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
    nullable = placement is not None
    if whole_option:
        optional = option._definition.is_optional
        nullable = (
            bool(optional(option) if callable(optional) else optional)
            or option.default_value is not None
        )

    current = [current_value]

    def apply_value(value: Any) -> None:
        on_value(value)
        current[0] = value

    if read_state is None:

        def read_state() -> FieldValue:
            if whole_option:
                value = option(all_values=True)
                return FieldValue(
                    value,
                    option.default_value,
                    implicit_default=not option.is_set() and value is not None,
                    explicit=option.is_set(),
                )
            return FieldValue(current[0])

    if kind == "integer" or isinstance(grammar_type, Integer):
        editor = IntegerEditor(nullable=nullable, parent=parent)
        if placement is not None:
            minimum = coalesce(
                placement.minimum,
                getattr(grammar_type, "min", None),
                -2147483647,
            )
            maximum = coalesce(
                placement.maximum,
                getattr(grammar_type, "max", None),
                2147483647,
            )
            step = placement.step or 1
            if nullable:
                minimum -= int(step)
            editor.setSingleStep(int(step))
            if placement.special_value_text:
                editor.setSpecialValueText(placement.special_value_text)
        else:
            minimum = coalesce(
                getattr(grammar_type, "min", None),
                np.iinfo(np.int32).min + int(nullable),
            )
            maximum = coalesce(
                getattr(grammar_type, "max", None), np.iinfo(np.int32).max
            )
        editor.setRange(
            minimum - int(nullable) if placement is None else minimum,
            maximum,
        )
        if nullable:
            editor.set_unset_value(editor.minimum())
        editor.setReadOnly(read_only)
        editor.setKeyboardTracking(False)
        editor.bind(read_state, apply_value)
        editor.valueChanged.connect(editor.commit)
        return editor

    if kind == "real" or isinstance(grammar_type, Real):
        editor = RealEditor(nullable=nullable, parent=parent)
        lo = coalesce(
            placement.minimum if placement is not None else None,
            getattr(grammar_type, "min", None),
            -1e16,
        )
        hi = coalesce(
            placement.maximum if placement is not None else None,
            getattr(grammar_type, "max", None),
            1e16,
        )
        editor.setDecimals(placement.decimals if placement is not None else 8)
        if placement is not None:
            step = placement.step or 0.1
            lower = lo - float(step) if nullable else lo
            editor.setSingleStep(float(step))
            if placement.special_value_text:
                editor.setSpecialValueText(placement.special_value_text)
        else:
            lower = lo - max(1.0, abs(lo) * 1e-12) if nullable else lo
            editor.setSingleStep((hi - lo) / 1000.0 if hi - lo < 1e6 else 1.0)
        editor.setRange(lower, hi)
        if nullable:
            editor.set_unset_value(editor.minimum())
        editor.setReadOnly(read_only)
        editor.setKeyboardTracking(False)
        editor.bind(read_state, apply_value)
        editor.valueChanged.connect(editor.commit)
        return editor

    if kind == "boolean" or isinstance(grammar_type, (Boolean, Flag)):
        editor = BooleanEditor(parent)
        editor.setEnabled(not read_only)
        editor.bind(read_state, apply_value)
        editor.toggled.connect(editor.commit)
        return editor

    if kind in {"choice", "keyword"} or isinstance(grammar_type, Keyword):
        uses_keyword = isinstance(grammar_type, Keyword)
        allows_unset = uses_keyword and keyword_allows_unset(option, grammar_type)
        editor = ChoiceEditor(
            normalize=(
                lambda state: None
                if allows_unset and state.explicit is False
                else state.value
            ),
            unavailable_unknown=uses_keyword,
            parent=parent,
        )
        if kind == "choice" and placement is not None:
            items = ((choice.value, choice.label) for choice in placement.choices)
        else:
            keyword_values = keyword_items(
                option, value_type=grammar_type, atoms=atoms
            )
            labels = (
                {choice.value: choice.label for choice in placement.choices}
                if placement is not None
                else {}
            )
            items = (
                (
                    keyword,
                    labels.get(
                        keyword,
                        info
                        if keyword is None
                        else f"{keyword}: {info}"
                        if info
                        else str(keyword),
                    ),
                )
                for keyword, info in keyword_values
            )
        for index, (keyword, label) in enumerate(items):
            editor.addItem(label, keyword)
            editor.setItemData(index, label, Qt.ItemDataRole.ToolTipRole)
        editor.setEnabled(not read_only)
        if placement is not None and placement.descriptions:
            editor.view().setMinimumWidth(560)
        editor.bind(read_state, apply_value)
        editor.currentIndexChanged.connect(editor.commit)
        return editor

    editor = TextEditor(
        grammar_type,
        kind=kind,
        nullable=nullable,
        allow_empty=allow_empty,
        option=option,
        parent=parent,
    )
    editor.setReadOnly(read_only)
    editor.bind(read_state, apply_value)
    editor.editingFinished.connect(editor.commit)
    return editor
