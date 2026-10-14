"""Session-independent entry points for browsing durable calculation data."""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QGroupBox, QPushButton, QVBoxLayout, QWidget


class BrowserPanel(QGroupBox):
    """Request browsers that are broader than the current workspace results."""

    calculationJobsRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Browse", parent)

        layout = QVBoxLayout(self)
        self.calculation_jobs_button = QPushButton("Calculation Jobs…", self)
        self.calculation_jobs_button.clicked.connect(
            lambda _checked=False: self.calculationJobsRequested.emit()
        )
        layout.addWidget(self.calculation_jobs_button)
