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
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from guy4ase.gui.input_parameters.bindings import InputParameterPath, resolve_option
from guy4ase.gui.input_parameters.bsf import (
    EK,
    bsf_mode,
    select_path,
    set_energy_points,
)
from guy4ase.gui.input_parameters.energy import (
    EnergyState,
    bound_energy_state,
    bound_energy_updates,
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
from guy4ase.gui.widgets.input_parameters.kpath import KPathTable, VectorEditor
from guy4ase.gui.widgets.input_parameters.relativistic_scaling import (
    RelativisticScalingEditor,
)
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
        self._null_sentinel: float | int | None = None
        self._value_type = self.session.option(self.path)._definition.type
        if placement.index is not None:
            self._value_type = self._value_type.type
        self._uses_keyword_choices = isinstance(self._value_type, Keyword) and placement.kind != "kpath"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.control = self._create_control()
        if placement.kind != "bsf_vectors":
            self.control.setFixedWidth(EDITOR_WIDTH)
        layout.addWidget(self.control, 1)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        if placement.kind != "bsf_vectors":
            self.setFixedWidth(EDITOR_WIDTH)

        option = self.session.option(self.path)
        self._base_tooltip = parameter_tooltip(
            option,
            self.path[0],
            self.path[-1],
            placement.label,
        )
        if placement.kind == "bsf_mesh":
            self._base_tooltip += "\nNE = 1: k–k map at fixed energy; NE > 1: E–k path. Switching resets mode-specific settings (undoable)."
            self.mode_combo.setToolTip(self._base_tooltip)
            self.energy_count.setToolTip(self._base_tooltip)
        self.setToolTip(self._base_tooltip)
        self.control.setToolTip(self._base_tooltip)
        self._connect_control()
        self.session.parametersReplaced.connect(self.refresh)
        self.refresh()

    def _create_control(self) -> QWidget:
        spec = self.placement
        if spec.kind == "energy_bound":
            name = self.path[-1]
            def apply(value, unit, relative):
                updates = bound_energy_updates(name, value, unit, relative)
                self.session.mutate(lambda parameters: parameters.ENERGY.set(updates),
                                    source_page=self.page_id, path=self.path,
                                    text=f"Change {spec.label.rstrip(':')}")
            return EnergyEditor(
                lambda: bound_energy_state(self.session.working_parameters, name), apply, self)
        if spec.kind == "energy":
            def state():
                value = self.session.value(self.path)
                return EnergyState(None if value is None else float(value.to_value('Ry') if hasattr(value, 'to_value') else value), 'Ry')
            def apply(value, unit, _relative):
                value = (None if value is None else (value, unit) if isinstance(self._value_type, Energy)
                         else convert_energy(value, unit, 'Ry'))
                self.session.set_value(self.path, value,
                                       source_page=self.page_id, text=f"Change {spec.label.rstrip(':')}")
            return EnergyEditor(state, apply, self, with_reference=False,
                                minimum=spec.minimum if spec.minimum is not None else -1e9)
        if spec.kind == "bsf_vectors":
            return KPathTable(self.session, self.page_id, self)
        if spec.kind == "vector":
            return VectorEditor(self.session, self.path, self.page_id, self)
        if spec.kind == "scaling":
            return RelativisticScalingEditor(self.session, self.path, self.page_id, self)
        if spec.kind == "bsf_mesh":
            container = QWidget(self)
            layout = QVBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            self.mode_combo = QComboBox(container)
            self.mode_combo.addItem("E–k: energy range along a path", "EK")
            self.mode_combo.addItem("k–k: plane at fixed energy", "KK")
            self.energy_count = QSpinBox(container)
            self.energy_count.setRange(1, 100000)
            self.energy_count.setPrefix("Energy points: ")
            self.energy_count.setKeyboardTracking(False)
            layout.addWidget(self.mode_combo)
            layout.addWidget(self.energy_count)
            container.setMinimumHeight(self.mode_combo.sizeHint().height()
                                       + self.energy_count.sizeHint().height() + layout.spacing())
            return container
        if spec.kind == "integer":
            editor = NullableSpinBox(self)
            minimum = int(spec.minimum if spec.minimum is not None else -2147483647)
            if spec.nullable:
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
            if spec.nullable:
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
        if spec.kind == "kpath":
            return self._create_kpath_control()
        editor = QLineEdit(self)
        return editor

    def _create_kpath_control(self) -> QWidget:
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.path_combo = QComboBox(container)
        for value, description in keyword_items(self.session.option(self.path), atoms=self.atoms):
            label = description if value is None else f"{value}: {description}" if description else f"Predefined {value}"
            self.path_combo.addItem(label, value)
            if description:
                self.path_combo.setItemData(self.path_combo.count() - 1, description,
                                           Qt.ItemDataRole.ToolTipRole)
        self.path_combo.view().setMinimumWidth(600)
        self.path_summary = QLabel(container)
        self.path_edit = QPushButton("Custom k-path…", container)
        row.addWidget(self.path_combo, 1)
        row.addWidget(self.path_edit)
        layout.addLayout(row)
        layout.addWidget(self.path_summary)
        container.setMinimumHeight(max(self.path_combo.sizeHint().height(), self.path_edit.sizeHint().height())
                                   + self.path_summary.sizeHint().height() + layout.spacing())
        return container

    def _connect_control(self) -> None:
        control = self.control
        if isinstance(control, (QSpinBox, QDoubleSpinBox, QLineEdit)):
            control.editingFinished.connect(self.commit)
        elif isinstance(control, QCheckBox):
            control.toggled.connect(lambda _checked: self.commit())
        elif isinstance(control, QComboBox):
            control.currentIndexChanged.connect(lambda _index: self.commit())
        elif self.placement.kind == "kpath":
            self.path_combo.currentIndexChanged.connect(self._select_predefined_path)
            self.path_edit.clicked.connect(self._edit_kpath)
        elif self.placement.kind == "bsf_mesh":
            self.mode_combo.currentIndexChanged.connect(self._select_bsf_mode)
            self.energy_count.editingFinished.connect(self.commit)
        elif isinstance(control, (KPathTable, VectorEditor, RelativisticScalingEditor, EnergyEditor)):
            control.validationChanged.connect(self._set_error)

    def _select_bsf_mode(self) -> None:
        if self._refreshing:
            return
        points = 200 if self.mode_combo.currentData() == EK else 1
        self._commit_bsf_points(points)

    def _commit_bsf_points(self, points) -> bool:
        """Change BSF sampling/mode in one command, choosing an atom-valid path."""
        try:
            def update(parameters):
                previous_mode = bsf_mode(parameters)
                set_energy_points(parameters, points)
                if previous_mode != EK and points > 1:
                    option = parameters.TASK["KPATH"]
                    available = [value for value, _ in keyword_items(option, atoms=self.atoms) if value is not None]
                    if option() not in available:
                        select_path(parameters, available[0] if available else None)
            self.session.mutate(update,
                                source_page=self.page_id, path=self.path, field_index=0,
                                text="Change BSF mode / energy points")
        except Exception as exc:
            self._set_error(str(exc))
            return False
        self._set_error("")
        return True

    def _read_value(self) -> Any:
        """Decode the widget draft, including unset sentinels, without storing it."""
        spec = self.placement
        control = self.control
        if isinstance(control, QSpinBox):
            if spec.nullable and not control.cleanText().strip():
                return None
            value: Any = int(control.value())
            if spec.nullable and value == self._null_sentinel:
                return None
            if spec.special_value_text and spec.minimum is not None and value == int(spec.minimum):
                return None
            return value
        if isinstance(control, QDoubleSpinBox):
            if spec.nullable and not control.cleanText().strip():
                return None
            value = float(control.value())
            if spec.nullable and value == self._null_sentinel:
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
            if spec.kind in {"literal", "bsf_ka"}:
                value = None if not text else ast.literal_eval(text)
                if spec.kind == "bsf_ka" and value is not None and bsf_mode(self.session.working_parameters) != EK:
                    value = [value]
                return value
            return text or None
        return None

    def commit(self) -> bool:
        """Apply this draft through the session, reporting errors without raising.

        Return success, not whether a value changed. Indexed fields replace
        only their array component; compound widgets implement their own commit.
        """
        if self._refreshing or not self.control.isEnabled() or self.placement.kind in {"kpath", "bsf_vectors"}:
            return True
        if self.placement.kind == "bsf_mesh":
            return self._commit_bsf_points(self.energy_count.value())
        if isinstance(self.control, (VectorEditor, RelativisticScalingEditor, EnergyEditor)):
            return self.control.commit()
        try:
            value = self._read_value()
            def update(parameters):
                option = resolve_option(parameters, self.path)
                if parameters.task_name.lower() == "bsf" and self.path in (
                    ("ENERGY", "EMIN"), ("ENERGY", "EMAX"),
                    ("ENERGY", "EMINEV"), ("ENERGY", "EMAXEV"),
                ):
                    name = self.path[1]
                    updates = {name: value}
                    if value is not None:
                        updates[name[:-2] if name.endswith("EV") else name + "EV"] = None
                    parameters.ENERGY.set(updates)
                    return
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

        Missing values may use display-only fallbacks. This also clears local
        validation errors; refresh does not preserve an invalid widget draft.
        """
        self._refreshing = True
        try:
            value = self.session.value(self.path)
            spec = self.placement
            if spec.index is not None:
                values = list(value) if value is not None else []
                value = values[spec.index] if len(values) > spec.index else None
                if value is None and spec.index == 1 and self.path in (("ENERGY", "GRID"), ("ENERGY", "NE")):
                    value = self.session.single_site_value(self.path)
            control = self.control
            if isinstance(control, (KPathTable, VectorEditor, RelativisticScalingEditor, EnergyEditor)):
                control.refresh()
            elif isinstance(control, QSpinBox):
                fallback = self._null_sentinel if value is None and spec.nullable else (
                    spec.default if spec.default is not None else spec.minimum or 0
                )
                control.setValue(int(_first(value, fallback)))
            elif isinstance(control, QDoubleSpinBox):
                fallback = self._null_sentinel if value is None and spec.nullable else (
                    spec.default if spec.default is not None else spec.minimum or 0.
                )
                control.setValue(float(_first(value, fallback)))
            elif isinstance(control, QCheckBox):
                control.setChecked(bool(value))
            elif isinstance(control, QComboBox):
                if self._uses_keyword_choices:
                    option = self.session.option(self.path)
                    value = keyword_current_value(option, self._value_type, value)
                self._set_combo_value(control, value, unavailable=self._uses_keyword_choices)
            elif isinstance(control, QLineEdit):
                if spec.kind in {"literal", "bsf_ka"}:
                    if spec.kind == "bsf_ka" and value is not None and bsf_mode(self.session.working_parameters) != EK:
                        value = value[0]
                    control.setText(_render_literal(value, spec.default))
                else:
                    control.setText(str(spec.default if value is None and spec.default is not None else value or ""))
            elif spec.kind == "kpath":
                self._refresh_kpath(value)
            elif spec.kind == "bsf_mesh":
                points = int(value)
                self._set_combo_value(self.mode_combo, EK if points > 1 else "KK")
                self.energy_count.setValue(points)
                self.energy_count.setEnabled(points > 1)
        finally:
            self._refreshing = False
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

    def _refresh_kpath(self, value: Any) -> None:
        self._set_combo_value(self.path_combo, value, unavailable=True)
        self.path_edit.setEnabled(value is None and bsf_mode(self.session.working_parameters) == EK)
        if value is not None:
            summary = f"Predefined path {value}"
        else:
            try:
                count = len(self.session.value(("TASK", "KA")))
                summary = f"Custom path, {count} segment(s)"
            except Exception:
                summary = "No path selected"
        self.path_summary.setText(summary)
        if value is not None:
            # Keep the full atom-specific route readable after closing the popup.
            self.path_summary.setText(self.path_combo.currentText())
        self.path_summary.setWordWrap(True)
        for widget in (self.path_combo, self.path_summary, self.path_edit):
            widget.setToolTip(self._base_tooltip)

    def _select_predefined_path(self) -> None:
        if self._refreshing:
            return
        value = self.path_combo.currentData()
        try:
            self.session.mutate(
                lambda parameters: select_path(parameters, value),
                path=self.path,
                source_page=self.page_id,
                text="Select custom K-path" if value is None else "Select predefined K-path",
            )
        except Exception as exc:
            self._set_error(str(exc))

    def _edit_kpath(self) -> None:
        """Run the modal path editor on a candidate, installing accepted edits atomically."""
        if self.atoms is None:
            QMessageBox.warning(self, "K-path", "A structure is required to edit the Brillouin-zone path.")
            return
        try:
            self.session.mutate(
                lambda parameters: parameters.TASK.k_path_gui(self.atoms, parent=self.window()),
                text="Edit custom K-path",
                source_page=self.page_id,
                path=self.path,
            )
        except Exception as exc:
            QMessageBox.critical(self, "K-path Error", str(exc))

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
        if self._disabled_reason:
            tooltip += f"\n\nDisabled: {self._disabled_reason}"
        if self._error:
            tooltip += f"\n\nInvalid value: {self._error}"
        self.setToolTip(tooltip)
        self.control.setToolTip(tooltip)

    def set_parameter_enabled(self, enabled: bool, reason: str | None = None) -> None:
        """Disable interaction with an explanation, retaining the underlying value."""
        self.control.setEnabled(enabled)
        self._disabled_reason = "" if enabled else reason or ""
        self._update_tooltip()
