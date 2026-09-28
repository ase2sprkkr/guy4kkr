"""Editors bound to an :class:`InputParametersSession`."""
from __future__ import annotations

import ast
from typing import Any

import numpy as np
from ase2sprkkr.common.grammar_types import Energy, Keyword
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLineEdit,
    QSizePolicy,
    QSpinBox,
    QWidget,
)

from guy4ase.gui.input_parameters.bindings import (
    InputParameterPath,
    resolve_option,
    values_equal,
)
from guy4ase.gui.input_parameters.defaults import default_text
from guy4ase.gui.input_parameters.energy import (
    EnergyState,
    convert_energy,
)
from guy4ase.gui.input_parameters.keyword_choices import (
    keyword_current_value,
    keyword_items,
)
from guy4ase.gui.input_parameters.session import InputParametersSession
from guy4ase.gui.input_parameters.specs.schema import Choice, FieldPlacement
from guy4ase.gui.input_parameters.tooltips import parameter_tooltip
from guy4ase.gui.widgets.input_parameters.energy import EnergyEditor
from guy4ase.gui.widgets.input_parameters.kpath import VectorEditor
from guy4ase.gui.widgets.input_parameters.registry import create_compound_editor
from guy4ase.gui.widgets.nullable_spinbox import NullableDoubleSpinBox, NullableSpinBox

EDITOR_WIDTH = 280


def _first(value: Any, fallback: Any = None) -> Any:
    if isinstance(value, np.ndarray):
        return value.flat[0] if value.size else fallback
    if isinstance(value, (list, tuple)):
        return value[0] if value else fallback
    return fallback if value is None else value


def _render_literal(value: Any, fallback: Any) -> str:
    value = fallback if value is None else value
    if value is None:
        return ""
    def plain(item):
        if isinstance(item, np.ndarray):
            return plain(item.tolist())
        if isinstance(item, dict):
            return {key: plain(child) for key, child in item.items()}
        if isinstance(item, (tuple, list)):
            return [plain(child) for child in item]
        if isinstance(item, np.generic):
            return item.item()
        return item
    return repr(plain(value))


class ParameterEditor(QWidget):
    """A presentation widget that commits one path through the session."""

    validationChanged = pyqtSignal(object, str, str)
    externalActionRequested = pyqtSignal()

    def __init__(
        self,
        session: InputParametersSession,
        placement: FieldPlacement,
        page_id: str,
        *,
        atoms: Any = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.placement = placement
        self.path: InputParameterPath = placement.path
        self.page_id = page_id
        self.atoms = atoms
        self._refreshing = False
        self._error = ""
        self._disabled_reason = ""
        self._presentation_help = ""
        self._null_sentinel: float | int | None = None
        self._value_type = self.session.option(self.path)._definition.type
        self._nullable = True  # Clearing resets to the backend default, or unsets.
        if placement.index is not None:
            self._value_type = self._value_type.type
        self._uses_keyword_choices = isinstance(self._value_type, Keyword) and not placement.editor

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.control = self._create_control()
        self.full_width = bool(getattr(self.control, "full_width", False))
        if not self.full_width:
            self.control.setFixedWidth(EDITOR_WIDTH)
        layout.addWidget(self.control, 1)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        if not self.full_width:
            self.setFixedWidth(EDITOR_WIDTH)

        option = self.session.option(self.path)
        self._base_tooltip = parameter_tooltip(
            option,
            self.path[0],
            self.path[-1],
            placement.label,
        )
        extra_help = getattr(self.control, "help_text", "")
        if extra_help:
            self._base_tooltip += f"\n{extra_help}"
        self.setToolTip(self._base_tooltip)
        self.control.setToolTip(self._base_tooltip)
        if hasattr(self.control, "set_editor_tooltip"):
            self.control.set_editor_tooltip(self._base_tooltip)
        self._connect_control()
        self.session.editApplied.connect(self._session_changed)
        self.refresh()

    def _session_changed(self, paths, reset):
        """Preserve unrelated drafts; replacements and history explicitly discard them."""
        dependencies = set(self.placement.paths)
        dependencies.update(getattr(self.control, "dependencies", ()))
        if reset or dependencies.intersection(paths):
            self.refresh()

    def _create_control(self) -> QWidget:
        spec = self.placement
        if spec.editor:
            return create_compound_editor(
                spec.editor,
                self.session,
                spec,
                self.page_id,
                atoms=self.atoms,
                parent=self,
            )
        if spec.kind == "energy":
            def state():
                value = self.session.value(self.path)
                number = (
                    None
                    if value is None
                    else float(value.to_value("Ry") if hasattr(value, "to_value") else value)
                )
                return EnergyState(
                    number,
                    "Ry",
                    explicit=self.session.option(self.path).is_set(),
                )
            def apply(value, unit, _relative):
                value = (None if value is None else (value, unit) if isinstance(self._value_type, Energy)
                         else convert_energy(value, unit, 'Ry'))
                self.session.set_value(self.path, value,
                                       source_page=self.page_id, text=f"Change {spec.label.rstrip(':')}")
            return EnergyEditor(state, apply, self, with_reference=False,
                                minimum=spec.minimum if spec.minimum is not None else -1e9)
        if spec.kind == "vector":
            return VectorEditor(self.session, self.path, self.page_id, self)
        if spec.kind == "integer":
            editor = NullableSpinBox(self)
            minimum = int(spec.minimum if spec.minimum is not None else -2147483647)
            if self._nullable:
                self._null_sentinel = minimum - int(spec.step or 1)
                minimum = int(self._null_sentinel)
                editor.set_unset_value(minimum)
            editor.setRange(minimum,
                            int(spec.maximum if spec.maximum is not None else 2147483647))
            editor.setSingleStep(int(spec.step or 1))
            editor.setKeyboardTracking(False)
            if spec.special_value_text:
                editor.setSpecialValueText(spec.special_value_text)
            return editor
        if spec.kind == "real":
            editor = NullableDoubleSpinBox(self)
            editor.setDecimals(spec.decimals)
            minimum = float(spec.minimum if spec.minimum is not None else -1e16)
            if self._nullable:
                self._null_sentinel = minimum - float(spec.step or .1)
                minimum = float(self._null_sentinel)
                editor.set_unset_value(minimum)
            editor.setRange(minimum,
                            float(spec.maximum if spec.maximum is not None else 1e16))
            editor.setSingleStep(float(spec.step or .1))
            editor.setKeyboardTracking(False)
            if spec.special_value_text:
                editor.setSpecialValueText(spec.special_value_text)
            return editor
        if spec.kind == "boolean":
            return QCheckBox(self)
        if self._uses_keyword_choices or spec.kind in {"choice", "keyword"}:
            combo = QComboBox(self)
            choices = list(spec.choices)
            if self._uses_keyword_choices:
                items = list(keyword_items(self.session.option(self.path), index=spec.index, atoms=self.atoms))
                labels = {choice.value: choice.label for choice in choices}
                choices = [Choice(description if value is None else labels.get(value,
                                  f"{value}: {description}" if description else str(value)), value)
                           for value, description in items]
            for choice in choices:
                combo.addItem(choice.label, choice.value)
                combo.setItemData(combo.count() - 1, choice.label, Qt.ItemDataRole.ToolTipRole)
            if spec.descriptions:
                combo.view().setMinimumWidth(560)
            return combo
        editor = QLineEdit(self)
        return editor

    def _connect_control(self) -> None:
        control = self.control
        if isinstance(control, (QSpinBox, QDoubleSpinBox, QLineEdit)):
            control.editingFinished.connect(self.commit)
        elif isinstance(control, QCheckBox):
            control.toggled.connect(lambda _checked: self.commit())
        elif isinstance(control, QComboBox):
            control.currentIndexChanged.connect(lambda _index: self.commit())
        elif self.placement.editor:
            control.validationChanged.connect(self._set_error)
            action = getattr(control, "externalActionRequested", None)
            if action is not None:
                action.connect(self.externalActionRequested)
        elif isinstance(control, (VectorEditor, EnergyEditor)):
            control.validationChanged.connect(self._set_error)

    def _read_value(self) -> Any:
        """Decode the widget draft, including unset sentinels, without storing it."""
        spec = self.placement
        control = self.control
        if isinstance(control, QSpinBox):
            if self._nullable and not control.cleanText().strip() and not control.is_default_display():
                return None
            value: Any = int(control.value())
            if self._nullable and value == control.minimum():
                return None
            if spec.special_value_text and spec.minimum is not None and value == int(spec.minimum):
                return None
            return value
        if isinstance(control, QDoubleSpinBox):
            if self._nullable and not control.cleanText().strip() and not control.is_default_display():
                return None
            value = float(control.value())
            if self._nullable and value == control.minimum():
                return None
            if spec.special_value_text and spec.minimum is not None and value == float(spec.minimum):
                return None
            return value
        if isinstance(control, QCheckBox):
            return bool(control.isChecked())
        if isinstance(control, QComboBox):
            return control.currentData()
        if isinstance(control, QLineEdit):
            text = control.text().strip()
            if spec.kind == "literal":
                value = None if not text else ast.literal_eval(text)
                return value
            return text or None
        return None

    def commit(self) -> bool:
        """Apply this draft through the session, reporting errors without raising.

        Return success, not whether a value changed. Indexed fields replace
        only their array component; compound widgets implement their own commit.
        """
        if self._refreshing or not self.control.isEnabled():
            return True
        if self.placement.editor:
            return self.control.commit()
        if isinstance(self.control, (VectorEditor, EnergyEditor)):
            return self.control.commit()
        try:
            value = self._read_value()
            if values_equal(value, self._shown):
                self._set_error('')
                return True
            def update(parameters):
                option = resolve_option(parameters, self.path)
                if self.placement.index is not None:
                    values = list(option())
                    index = self.placement.index
                    # A missing second mesh starts with the first mesh. Never
                    # discard the other component when editing a single one.
                    while len(values) <= index:
                        values.append(values[0])
                    values[index] = value
                    option.set(values)
                else:
                    option.set(value)

            self.session.mutate(update, source_page=self.page_id, path=self.path,
                                field_index=self.placement.index,
                                text=f"Change {self.placement.label.rstrip(':')}")
        except Exception as exc:
            self._set_error(str(exc))
            return False
        self._set_error("")
        return True

    def refresh(self) -> None:
        """Replace the draft from session state without creating an edit.

        Implicit backend defaults are placeholders, never GUI-invented values.
        A deliberate refresh also clears local validation errors.
        """
        self._refreshing = True
        try:
            value = self.session.value(self.path)
            option = self.session.option(self.path)
            default = option.default_value
            implicit = not option.is_set() and value is not None
            spec = self.placement
            if spec.index is not None:
                values = list(value) if value is not None else []
                value = values[spec.index] if len(values) > spec.index else None
                if default is not None:
                    default = default[spec.index] if len(default) > spec.index else None
                if value is None and spec.index == 1 and self.path in (("ENERGY", "GRID"), ("ENERGY", "NE")):
                    value = self.session.single_site_value(self.path)
            control = self.control
            if spec.editor:
                control.refresh()
            elif isinstance(control, (VectorEditor, EnergyEditor)):
                control.refresh()
            elif isinstance(control, QSpinBox):
                fallback = self._null_sentinel if value is None and self._nullable else 0
                control.setValue(int(_first(value, fallback)))
                control.lineEdit().setPlaceholderText(default_text(default))
                if implicit and value is not None:
                    control.show_default(int(_first(value)), default_text(default))
            elif isinstance(control, QDoubleSpinBox):
                fallback = self._null_sentinel if value is None and self._nullable else 0.
                control.setValue(float(_first(value, fallback)))
                control.lineEdit().setPlaceholderText(default_text(default))
                if implicit and value is not None:
                    control.show_default(float(_first(value)), default_text(default))
            elif isinstance(control, QCheckBox):
                control.setChecked(bool(value))
            elif isinstance(control, QComboBox):
                if self._uses_keyword_choices:
                    option = self.session.option(self.path)
                    value = keyword_current_value(option, self._value_type, value)
                self._set_combo_value(control, value, unavailable=self._uses_keyword_choices)
            elif isinstance(control, QLineEdit):
                if implicit:
                    value = None
                if spec.kind == "literal":
                    control.setText(_render_literal(value, None))
                else:
                    control.setText('' if value is None else str(value))
                control.setPlaceholderText(default_text(default))
        finally:
            self._refreshing = False
        self._shown = self._read_value()
        self._set_error("")

    @staticmethod
    def _set_combo_value(combo: QComboBox, value: Any, *, unavailable: bool = False) -> None:
        """Show imported unknown values explicitly instead of selecting a valid fallback."""
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                combo.setCurrentIndex(index)
                return
        if value is None:
            combo.setCurrentIndex(-1)
            combo.setPlaceholderText("Not set")
        else:
            # Do not silently present an unrecognised imported value as the
            # first choice, even if a schema changes between versions.
            label = f"{value} (current value, unavailable)" if unavailable else str(value)
            combo.addItem(label, value)
            if unavailable:
                combo.model().item(combo.count() - 1).setEnabled(False)
            combo.setCurrentIndex(combo.count() - 1)

    def _set_error(self, message: str) -> None:
        if message == self._error:
            return
        self._error = message
        if message:
            self.control.setStyleSheet("border: 2px solid palette(highlight);")
        else:
            self.control.setStyleSheet("")
        self._update_tooltip()
        self.validationChanged.emit(self.path, self.page_id, message)

    def _update_tooltip(self) -> None:
        tooltip = self._base_tooltip
        if self._presentation_help:
            tooltip += f"\n\n{self._presentation_help}"
        if self._disabled_reason:
            tooltip += f"\n\nDisabled: {self._disabled_reason}"
        if self._error:
            tooltip += f"\n\nInvalid value: {self._error}"
        self.setToolTip(tooltip)
        self.control.setToolTip(tooltip)
        if hasattr(self.control, "set_editor_tooltip"):
            self.control.set_editor_tooltip(tooltip)

    def set_parameter_enabled(self, enabled: bool, reason: str | None = None) -> None:
        """Disable interaction with an explanation, retaining the underlying value."""
        self.control.setEnabled(enabled)
        self._disabled_reason = "" if enabled else reason or ""
        self._update_tooltip()

    def set_presentation_help(self, text: str | None) -> None:
        """Add rule-derived help without replacing validation or option help."""
        self._presentation_help = text or ""
        self._update_tooltip()

    def focus_for_history(self, path: InputParameterPath, index: int | None) -> None:
        """Focus the value restored by Undo/Redo without exposing editor internals."""
        if self.placement.editor:
            self.control.focus_for_history(path, index)
        elif isinstance(self.control, VectorEditor):
            self.control.table.setFocus(Qt.FocusReason.OtherFocusReason)
        else:
            self.control.setFocus(Qt.FocusReason.OtherFocusReason)
