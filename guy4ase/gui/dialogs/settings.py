"""Application settings dialog."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from guy4ase.gui.application.settings import ApplicationSettings


def available_viewers() -> tuple[str, ...]:
    """Return viewer names understood by ASE."""
    from ase.visualize.viewers import VIEWERS

    return tuple(sorted(str(name) for name in VIEWERS))


class SettingsDialog(QDialog):
    """Edit application-wide preferences."""

    def __init__(
        self,
        settings: ApplicationSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self._settings = settings

        layout = QVBoxLayout(self)
        visualization = QGroupBox("Visualization", self)
        form = QFormLayout(visualization)

        self.viewer = QComboBox(visualization)
        viewers = available_viewers()
        self.viewer.addItems(viewers)
        if settings.viewer not in viewers:
            self.viewer.addItem(settings.viewer)
        self.viewer.setCurrentText(settings.viewer)
        self.viewer.setToolTip("ASE viewer used for atomic structures")
        form.addRow("Structure viewer:", self.viewer)
        layout.addWidget(visualization)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self) -> None:  # type: ignore[override]
        previous = self._settings.viewer
        self._settings.viewer = self.viewer.currentText()
        if not self._settings.save():
            self._settings.viewer = previous
            QMessageBox.critical(
                self,
                "Cannot Save Settings",
                f"Could not write settings to:\n{self._settings.path}",
            )
            return
        super().accept()


def edit_settings(
    settings: ApplicationSettings,
    parent: QWidget | None = None,
) -> bool:
    """Open the application settings dialog."""
    dialog = SettingsDialog(settings, parent)
    return dialog.exec() == QDialog.DialogCode.Accepted
