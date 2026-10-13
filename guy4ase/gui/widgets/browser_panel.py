"""Session-independent entry points for browsing durable calculation data."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QGroupBox, QPushButton, QVBoxLayout, QWidget

from guy4ase.gui.dialogs.project_browser import ProjectBrowserDialog


class BrowserPanel(QGroupBox):
    """Host browsers backed by durable data rather than the current session."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Browse", parent)
        self._project_browser: ProjectBrowserDialog | None = None

        layout = QVBoxLayout(self)
        self.calculation_jobs_button = QPushButton("Project Browser…", self)
        self.calculation_jobs_button.clicked.connect(self.open_project_browser)
        layout.addWidget(self.calculation_jobs_button)

    def open_project_browser(self) -> None:
        """Show persistent projects, their calculation jobs, and results."""
        dialog = self._project_browser
        if dialog is not None:
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            return

        dialog = ProjectBrowserDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.destroyed.connect(self._project_browser_closed)
        self._project_browser = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _project_browser_closed(self, *_args) -> None:
        self._project_browser = None
