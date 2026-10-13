"""Session-independent entry points for browsing durable calculation data."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QGroupBox, QPushButton, QVBoxLayout, QWidget

from guy4ase.gui.dialogs.calculation_history import CalculationHistoryDialog


class BrowserPanel(QGroupBox):
    """Host browsers that are broader than the current workspace results.

    Calculation-job history belongs here because it is backed by ASE2SPRKKR's
    persistent execution store, not by the current ``ResultStore``. Project
    browsing can be added alongside it without coupling either browser to the
    result presentation widget.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Browse", parent)
        self._calculation_history: CalculationHistoryDialog | None = None

        layout = QVBoxLayout(self)
        self.calculation_jobs_button = QPushButton("Calculation Jobs…", self)
        self.calculation_jobs_button.clicked.connect(self.open_calculation_jobs)
        layout.addWidget(self.calculation_jobs_button)

    def open_calculation_jobs(self) -> None:
        """Show the persistent ASE2SPRKKR calculation-job browser."""
        dialog = self._calculation_history
        if dialog is not None:
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            return

        dialog = CalculationHistoryDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.destroyed.connect(self._calculation_history_closed)
        self._calculation_history = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _calculation_history_closed(self, *_args) -> None:
        self._calculation_history = None
