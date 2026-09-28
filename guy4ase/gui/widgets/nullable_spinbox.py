"""Numeric inputs where deleting the text really selects the unset value."""
from PyQt6.QtGui import QValidator
from PyQt6.QtWidgets import QDoubleSpinBox, QSpinBox


class _NullableSpinBox:
    _unset_value = None

    def set_unset_value(self, value):
        self._unset_value = value
        self.setSpecialValueText("Not set")
        self.editingFinished.connect(self._finish_empty)

    def _finish_empty(self):
        if not self.cleanText().strip():
            self.setValue(self._unset_value)
            # Qt can leave the line edit blank when the value was already
            # updated to the sentinel during keyboard tracking.
            self.lineEdit().setText(self.specialValueText())

    def validate(self, text, position):
        if self._unset_value is not None and not text.strip():
            return QValidator.State.Acceptable, text, position
        return super().validate(text, position)

    def valueFromText(self, text):
        if self._unset_value is not None and not text.strip():
            return self._unset_value
        return super().valueFromText(text)


class NullableSpinBox(_NullableSpinBox, QSpinBox):
    pass


class NullableDoubleSpinBox(_NullableSpinBox, QDoubleSpinBox):
    pass
