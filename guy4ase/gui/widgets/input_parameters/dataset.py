"""Prominent editor and naming helpers for ``CONTROL.DATASET``."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from uuid import uuid4

from PyQt6.QtCore import QRegularExpression
from PyQt6.QtGui import QRegularExpressionValidator
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QWidget

from guy4ase.gui.input_parameters.session import InputParametersSession


DATASET_PATH = ("CONTROL", "DATASET")
_FILENAME_COMPONENT = re.compile(r"[^A-Za-z0-9_.-]+")


def filename_component(value: str) -> str:
    """Convert a DATASET value to a safe single filename component."""
    return _FILENAME_COMPONENT.sub("_", value.strip()).strip("._")


def _structure_name(atoms: Any) -> str:
    if atoms is None:
        return "case"
    try:
        name = atoms.get_chemical_formula()
    except Exception:
        return "case"
    return filename_component(name) or "case"


def generated_dataset(
    mode: str,
    atoms: Any = None,
    *,
    now: datetime | None = None,
    uuid_hex: str | None = None,
) -> str | None:
    """Return the configured default DATASET, or ``None`` to leave it unset."""
    if mode == "empty":
        return None
    base = _structure_name(atoms)
    if mode == "datetime":
        stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S_%f")[:-3]
        return f"{base}_{stamp}"
    if mode == "uuid":
        token = (uuid_hex or uuid4().hex)[:12]
        return f"{base}_{token}"
    raise ValueError(f"Unknown DATASET default mode {mode!r}.")


def apply_default_dataset(
    parameters: Any,
    mode: str,
    atoms: Any = None,
) -> None:
    """Populate an unset DATASET using the injected application preference."""
    option = parameters.CONTROL.DATASET
    if option.is_set():
        return
    value = generated_dataset(mode, atoms)
    if value is not None:
        option.set(value)


def dataset_value(parameters: Any) -> str | None:
    """Return an explicitly set DATASET without materializing its default."""
    try:
        option = parameters.CONTROL.DATASET
        if not option.is_set():
            return None
        value = option()
    except (AttributeError, TypeError):
        return None
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class DatasetEditor(QWidget):
    """Keep a visible DATASET field synchronized with an input session."""

    def __init__(
        self,
        session: InputParametersSession,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Dataset:", self))
        self.edit = QLineEdit(self)
        self.edit.setClearButtonEnabled(True)
        self.edit.setValidator(
            QRegularExpressionValidator(
                QRegularExpression(r"[A-Za-z0-9_.-]*"),
                self.edit,
            )
        )
        self.edit.setPlaceholderText("Leave empty for ASE2SPRKKR automatic naming")
        self.edit.setToolTip(
            "SPR-KKR uses CONTROL.DATASET as the base name for auxiliary result "
            "files. Allowed characters: letters, digits, '.', '_' and '-'. Use a "
            "different DATASET for parallel runs in one directory."
        )
        layout.addWidget(self.edit, 1)
        self.edit.editingFinished.connect(self.commit)
        self.session.parametersReplaced.connect(self._refresh)
        self.session.valueChanged.connect(self._value_changed)
        self._refresh()

    def _value_changed(self, path: object) -> None:
        if path == DATASET_PATH:
            self._refresh()

    def _refresh(self) -> None:
        option = self.session.option(DATASET_PATH)
        value = str(option()) if option.is_set() and option() is not None else ""
        if self.edit.text() != value:
            self.edit.setText(value)

    def commit(self) -> bool:
        """Synchronously apply the current DATASET draft if it changed."""
        value = self.edit.text().strip() or None
        option = self.session.option(DATASET_PATH)
        current = str(option()) if option.is_set() and option() is not None else None
        if value == current:
            return True
        self.session.set_value(
            DATASET_PATH,
            value,
            source_page="dataset",
            text="Change DATASET",
        )
        return True
