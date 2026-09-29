"""Explicit lifecycle contract for registered compound parameter editors."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget

from guy4ase.gui.input_parameters.bindings import InputParameterPath


class CompoundParameterEditor(QWidget):
    """Base class for controls created through the compound-editor registry.

    Concrete editors implement :meth:`refresh` and :meth:`commit`. The other
    hooks have useful defaults, so adding a registered editor does not require
    knowledge of optional attributes inspected elsewhere in the GUI.
    """

    validationChanged = pyqtSignal(str)

    dependencies: tuple[InputParameterPath, ...] = ()
    full_width = False
    help_text = ""

    def refresh(self) -> None:
        """Replace the displayed draft from the bound parameter source."""
        raise NotImplementedError

    def commit(self) -> bool:
        """Commit the current draft, returning whether it is valid."""
        raise NotImplementedError

    def focus_for_history(
        self,
        _path: InputParameterPath,
        _index: int | None,
    ) -> None:
        """Focus the value selected by Undo/Redo navigation."""
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def set_editor_tooltip(self, text: str) -> None:
        """Apply a composed tooltip; editors with child controls may override."""
        self.setToolTip(text)
