"""Guided chooser for obtaining a detached structure candidate."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.flows import structure_candidates
from guy4ase.gui.flows.structure_candidates import StructureCandidate


class StructureSourceDialog(QDialog):
    """Offer the standard non-workspace ways to obtain an atomic structure."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        recent_files: RecentFiles | None = None,
        title: str = "Choose Structure",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(520)
        self._candidate: StructureCandidate | None = None

        if recent_files is None:
            recent_files = RecentFiles()
            recent_files.load()
        self._recent_files = recent_files

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Choose how to obtain the structure. The selected structure is kept "
            "detached until the enclosing workflow accepts it.",
            self,
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        create_group = QGroupBox("Create structure", self)
        create_layout = QVBoxLayout(create_group)
        self._add_action(
            create_layout,
            "Create a 3D Structure",
            "Build a periodic bulk crystal",
            self._create,
        )
        self._add_action(
            create_layout,
            "Create Structure from Prototype Database",
            "Start from a crystallographic structure prototype",
            self._create_from_database,
        )
        layout.addWidget(create_group)

        load_group = QGroupBox("Load structure", self)
        load_layout = QVBoxLayout(load_group)
        self._add_action(
            load_layout,
            "Download Structure from Online Database",
            "Search an online crystallographic database",
            self._download,
        )
        self._add_action(
            load_layout,
            "Load a Structure",
            "Open a supported atomic structure file",
            self._load_file,
        )

        recent = self._recent_files.paths("structure")
        self._recent_combo: QComboBox | None = None
        if recent:
            recent_label = QLabel("Recent structures", load_group)
            load_layout.addWidget(recent_label)
            self._recent_combo = QComboBox(load_group)
            for path in recent:
                self._recent_combo.addItem(Path(path).name, path)
            self._recent_combo.setToolTip("Recently used structure files")
            load_layout.addWidget(self._recent_combo)
            use_recent = QPushButton("Use Selected Recent Structure", load_group)
            use_recent.clicked.connect(self._load_recent)
            load_layout.addWidget(use_recent)
        layout.addWidget(load_group)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _add_action(layout, title: str, description: str, callback) -> None:
        button = QPushButton(f"{title}\n{description}")
        button.setMinimumHeight(54)
        button.setToolTip(description)
        button.clicked.connect(callback)
        layout.addWidget(button)

    def _accept_candidate(self, candidate: StructureCandidate | None) -> None:
        if candidate is None:
            return
        self._candidate = candidate
        self.accept()

    def _create(self) -> None:
        self._accept_candidate(
            structure_candidates.create_structure_candidate(self)
        )

    def _create_from_database(self) -> None:
        self._accept_candidate(
            structure_candidates.create_structure_from_database_candidate(self)
        )

    def _download(self) -> None:
        self._accept_candidate(
            structure_candidates.download_structure_candidate(self)
        )

    def _load_file(self) -> None:
        candidate = structure_candidates.choose_structure_candidate(self)
        if candidate is not None and candidate.source_path is not None:
            self._recent_files.remember("structure", candidate.source_path)
        self._accept_candidate(candidate)

    def _load_recent(self) -> None:
        if self._recent_combo is None:
            return
        path = Path(str(self._recent_combo.currentData()))
        if not path.exists():
            QMessageBox.warning(
                self,
                "Missing File",
                f"File not found:\n{path}",
            )
            self._recent_files.forget("structure", path)
            return
        self._accept_candidate(
            structure_candidates.load_structure_candidate(path, self)
        )

    def candidate(self) -> StructureCandidate | None:
        return self._candidate


def select_structure_source(
    parent: QWidget | None = None,
    *,
    recent_files: RecentFiles | None = None,
    title: str = "Choose Structure",
) -> StructureCandidate | None:
    """Run the guided source chooser and return its detached candidate."""
    dialog = StructureSourceDialog(
        parent,
        recent_files=recent_files,
        title=title,
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.candidate()
