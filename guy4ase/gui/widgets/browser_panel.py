"""Session-independent entry points for durable calculation data."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QGroupBox, QPushButton, QVBoxLayout, QWidget

from guy4ase.gui.application.persistent_jobs import PersistentJobSource
from guy4ase.gui.application.projects import ProjectRepository, ProjectSource
from guy4ase.gui.dialogs.project_browser import ProjectBrowserDialog


class BrowserPanel(QGroupBox):
    """Own durable browser sources and open the project browser."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        repository: ProjectSource | None = None,
        job_source: PersistentJobSource | None = None,
    ) -> None:
        super().__init__("Browse", parent)
        self._repository = (
            repository if repository is not None else ProjectRepository()
        )
        self._job_source = (
            job_source if job_source is not None else PersistentJobSource()
        )
        self._project_browser: ProjectBrowserDialog | None = None

        layout = QVBoxLayout(self)
        self.project_browser_button = QPushButton("Project Browser…", self)
        self.project_browser_button.clicked.connect(self.open_project_browser)
        layout.addWidget(self.project_browser_button)

    def open_project_browser(self) -> None:
        dialog = self._project_browser
        if dialog is not None:
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            return

        dialog = ProjectBrowserDialog(
            self,
            repository=self._repository,
            job_source=self._job_source,
        )
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.destroyed.connect(self._project_browser_closed)
        self._project_browser = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _project_browser_closed(self, *_args) -> None:
        self._project_browser = None
