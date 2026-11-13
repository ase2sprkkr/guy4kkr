"""Common draft/commit boundary for ordinary parameter controls."""
from copy import deepcopy

from PyQt6.QtCore import QObject, pyqtSignal

from guy4ase.gui.input_parameters.bindings import values_equal


class EditorValidationError(ValueError):
    """A user-editable draft failed local conversion or validation."""


class EditorCommit(QObject):
    """Keep presentation drafts separate from storage and report input errors.

    The initial displayed value is a baseline, not a value to write back: it
    may be rounded or clamped. Call refresh only after an intentional model
    refresh. ``apply_value`` errors are programming/model failures and therefore
    propagate; only explicit ``EditorValidationError`` instances are presented
    as invalid user input.
    """

    validationChanged = pyqtSignal(str)

    def __init__(self, widget, read_value, apply_value):
        super().__init__(widget)
        self.widget = widget
        self.read_value = read_value
        self.apply_value = apply_value
        self.error = ''
        self._shown = deepcopy(read_value())

    def refresh(self):
        self._shown = deepcopy(self.read_value())
        self._set_error('')

    def _set_error(self, message):
        self.error = message
        self.widget.setStyleSheet('border: 2px solid palette(highlight);' if message else '')
        self.widget.setToolTip(message)
        self.validationChanged.emit(message)

    def commit(self, *_args):
        if not self.widget.isEnabled():
            return True
        try:
            draft = self.read_value()
            if not values_equal(draft, self._shown):
                self.apply_value(draft)
                self._shown = deepcopy(self.read_value())
        except EditorValidationError as error:
            self._set_error(str(error))
            return False
        self._set_error('')
        return True
