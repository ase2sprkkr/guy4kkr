from __future__ import annotations

from typing import Optional, Any, Dict, Sequence
from pathlib import Path
import json
import os

from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QGroupBox, QPushButton, QLabel, QTableWidget, QTableWidgetItem,
    QMenuBar, QMenu, QFileDialog, QMessageBox, QGridLayout, QHeaderView,
    QToolButton, QPlainTextEdit, QStackedWidget, QStyle, QDialog,
    QDialogButtonBox, QCheckBox
)
from PyQt6.QtGui import QAction, QColor
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib import cm
from matplotlib.colors import to_hex
import numpy as np
import re
import platformdirs

from ase import Atoms
from ase.io import read as ase_read, write as ase_write

from .lattice import plot_lattice, plot_sites_in_lattice
from .common import chain_dialogs
from .spacegroup_selector import select_spacegroup
from .element_assignment import select_site_elements
from .input_parameters_dialog import select_input_parameters


class MainWindow(QMainWindow):
    """Main application window for structure creation, loading, and manipulation."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Guy4ASE - Structure Manager")
        self.resize(1400, 800)

        self.atoms: Optional[Any] = None  # ASE Atoms object
        self._site_colors: Dict[str, str] = {}
        self._hovered_atom_index: Optional[int] = None
        self._input_parameters = None
        self.input_params_preview: Optional[QPlainTextEdit] = None
        self.save_input_btn: Optional[QPushButton] = None
        self.directory: Optional[str] = None
        self._directory_label: Optional[QLabel] = None
        self._directory_choose_btn: Optional[QToolButton] = None
        self._sprkkr_run_window: Optional[QWidget] = None
        self._last_sprkkr_result: Optional[Any] = None

        self._recent_files: list[str] = []
        self._recent_menu: Optional[QMenu] = None
        self._recent_start_button: Optional[QToolButton] = None
        self._recent_start_menu: Optional[QMenu] = None

        self._left_stack: Optional[QStackedWidget] = None
        self._left_content_widget: Optional[QWidget] = None

        self._build_ui()
        self._load_recent_files()
        self._refresh_recent_menu()
        self._update_structure_view()

    def _update_input_params_preview(self) -> None:
        if self.input_params_preview is None:
            return
        if self._input_parameters is None:
            self.input_params_preview.setPlainText("")
            if self.save_input_btn is not None:
                self.save_input_btn.setEnabled(False)
            return
        try:
            txt = self._input_parameters.to_string(validate=False)
        except Exception:
            txt = str(self._input_parameters)
        self.input_params_preview.setPlainText(txt)
        if self.save_input_btn is not None:
            self.save_input_btn.setEnabled(True)

    def _update_directory_label(self) -> None:
        if self._directory_label is None:
            return
        if not self.directory:
            self._directory_label.setText("—")
            self._directory_label.setToolTip("")
            return
        self._directory_label.setText(self.directory)
        self._directory_label.setToolTip(self.directory)

    def _choose_directory(self) -> None:
        start_dir = self.directory or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Select Directory", start_dir)
        if not chosen:
            return
        self.directory = str(chosen)
        self._update_directory_label()
        self.enable_run_calculation()

    def _config_dir(self) -> Path:
        config_home = platformdirs.user_config_dir('guy4ase', appauthor='ase2sprkkr')
        if config_home:
            return Path(config_home)
        return Path.home() / ".config"

    def _recent_files_path(self) -> Path:
        return self._config_dir() / "recent_files.json"

    def _load_recent_files(self) -> None:
        path = self._recent_files_path()
        try:
            if not path.exists():
                self._recent_files = []
                return
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                self._recent_files = [str(p) for p in data if isinstance(p, str)]
            else:
                self._recent_files = []
        except Exception:
            self._recent_files = []

    def _save_recent_files(self) -> None:
        path = self._recent_files_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self._recent_files, indent=2), encoding="utf-8")
        except Exception:
            # Non-fatal (e.g. read-only home); keep UI working.
            pass

    def _add_recent_file(self, file_path: str) -> None:
        file_path = str(Path(file_path))
        try:
            self._recent_files.remove(file_path)
            self._recent_files.insert(0, file_path)
        except ValueError:
            self._recent_files = self._recent_files[:9]
            self._recent_files.insert(0, file_path)
        self._save_recent_files()
        self._refresh_recent_menu()

    def _clear_recent_files(self) -> None:
        self._recent_files = []
        self._save_recent_files()
        self._refresh_recent_menu()

    def _refresh_recent_menu(self) -> None:
        if self._recent_menu is not None:
            self._recent_menu.clear()

            if not self._recent_files:
                empty_action = QAction("(No recent files)", self)
                empty_action.setEnabled(False)
                self._recent_menu.addAction(empty_action)
            else:
                for file_path in self._recent_files:
                    action = QAction(file_path, self)
                    action.triggered.connect(lambda _checked=False, p=file_path: self._open_recent_file(p))
                    self._recent_menu.addAction(action)

                self._recent_menu.addSeparator()
                clear_action = QAction("Clear Recent", self)
                clear_action.triggered.connect(self._clear_recent_files)
                self._recent_menu.addAction(clear_action)

        self._refresh_recent_start_button()

    def _refresh_recent_start_button(self) -> None:
        btn = self._recent_start_button
        if btn is None:
            return

        has_recent = bool(self._recent_files)
        btn.setVisible(has_recent)
        if not has_recent:
            return

        most_recent = self._recent_files[0]
        btn.setText(f"Continue: {Path(most_recent).name}")
        btn.setToolTip(most_recent)

        menu = self._recent_start_menu
        if menu is None:
            menu = QMenu(btn)
            self._recent_start_menu = menu
            btn.setMenu(menu)

        menu.clear()
        for file_path in self._recent_files[1:]:
            action = QAction(file_path, self)
            action.triggered.connect(lambda _checked=False, p=file_path: self._open_recent_file(p))
            menu.addAction(action)

        if self._recent_files[1:]:
            menu.addSeparator()

        clear_action = QAction("Clear Recent", self)
        clear_action.triggered.connect(self._clear_recent_files)
        menu.addAction(clear_action)

        # Primary click action loads most recent
        try:
            btn.clicked.disconnect()
        except TypeError:
            pass
        btn.clicked.connect(lambda _checked=False, p=most_recent: self._open_recent_file(p))

    def _open_recent_file(self, file_path: str) -> None:
        path = Path(file_path)
        if not path.exists():
            QMessageBox.warning(self, "Missing File", f"File not found:\n{file_path}")
            self._recent_files = [p for p in self._recent_files if p != file_path]
            self._save_recent_files()
            self._refresh_recent_menu()
            return
        self._load_structure_from_path(file_path)

    def _load_structure_from_path(self, file_path: str) -> None:
        try:
            atoms = ase_read(file_path)
            self.set_structure(atoms)
            self._add_recent_file(file_path)
        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Failed to load structure:\n{str(e)}")

    def _build_ui(self) -> None:
        """Build the main UI layout."""
        # Menu bar
        menubar = self.menuBar()

        # Structure menu
        structure_menu = menubar.addMenu("&Structure")

        create_action = QAction("&Create New...", self)
        create_action.setShortcut("Ctrl+N")
        create_action.triggered.connect(self._on_create_structure)
        structure_menu.addAction(create_action)

        load_action = QAction("&Load from File...", self)
        load_action.setShortcut("Ctrl+O")
        load_action.triggered.connect(self._on_load_structure)
        structure_menu.addAction(load_action)

        self._recent_menu = structure_menu.addMenu("Open &Recent")

        assign_elements_action = QAction("&Edit the structure...", self)
        assign_elements_action.setShortcut("Ctrl+E")
        assign_elements_action.triggered.connect(self._on_assign_elements)
        structure_menu.addAction(assign_elements_action)

        download_action = QAction("&Download from Materials Project...", self)
        download_action.triggered.connect(self._on_download_structure)
        structure_menu.addAction(download_action)

        structure_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        structure_menu.addAction(exit_action)

        # Help menu
        help_menu = menubar.addMenu("&Help")
        about_action = QAction("&About", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)

        # Central widget with splitter
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        # Left/center panel: structure viewer
        viewer_widget = QWidget()
        viewer_layout = QVBoxLayout(viewer_widget)

        # Stack left panel: welcome vs loaded-structure content
        self._left_stack = QStackedWidget(viewer_widget)
        viewer_layout.addWidget(self._left_stack, 1)

        # Welcome page (shown when no structure loaded)
        self.welcome_widget = QWidget(self._left_stack)
        welcome_layout = QVBoxLayout(self.welcome_widget)
        welcome_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        welcome_label = QLabel("No Structure Loaded")
        welcome_label.setStyleSheet("font-size: 18pt; font-weight: bold; color: #666;")
        welcome_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_layout.addWidget(welcome_label)

        welcome_layout.addSpacing(20)

        subtitle = QLabel("Choose an option to get started:")
        subtitle.setStyleSheet("font-size: 11pt; color: #888;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_layout.addWidget(subtitle)

        welcome_layout.addSpacing(30)

        # Action buttons
        btn_width = 250

        create_btn = QPushButton("Create New Structure")
        create_btn.setMinimumWidth(btn_width)
        create_btn.setMinimumHeight(45)
        create_btn.setStyleSheet("font-size: 11pt; padding: 8px;")
        create_btn.clicked.connect(self._on_create_structure)
        welcome_layout.addWidget(create_btn, 0, Qt.AlignmentFlag.AlignCenter)

        welcome_layout.addSpacing(15)

        load_btn = QPushButton("Load from File...")
        load_btn.setMinimumWidth(btn_width)
        load_btn.setMinimumHeight(45)
        load_btn.setStyleSheet("font-size: 11pt; padding: 8px;")
        load_btn.clicked.connect(self._on_load_structure)
        welcome_layout.addWidget(load_btn, 0, Qt.AlignmentFlag.AlignCenter)

        # Recent start button (shown only when there are recent files)
        self._recent_start_button = QToolButton(self.welcome_widget)
        self._recent_start_button.setMinimumWidth(btn_width)
        self._recent_start_button.setMinimumHeight(45)
        self._recent_start_button.setStyleSheet("font-size: 11pt; padding: 8px;")
        self._recent_start_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self._recent_start_button.hide()
        welcome_layout.addWidget(self._recent_start_button, 0, Qt.AlignmentFlag.AlignCenter)

        welcome_layout.addSpacing(15)

        download_btn = QPushButton("Download from Materials Project...")
        download_btn.setMinimumWidth(btn_width)
        download_btn.setMinimumHeight(45)
        download_btn.setStyleSheet("font-size: 11pt; padding: 8px;")
        download_btn.clicked.connect(self._on_download_structure)
        welcome_layout.addWidget(download_btn, 0, Qt.AlignmentFlag.AlignCenter)

        welcome_layout.addStretch(1)

        self._left_stack.addWidget(self.welcome_widget)

        # Content page (shown when a structure is loaded)
        self._left_content_widget = QWidget(self._left_stack)
        content_layout = QVBoxLayout(self._left_content_widget)

        # Visualization row: visualization on left, quick actions on right
        top_row = QWidget(self._left_content_widget)
        top_row_l = QHBoxLayout(top_row)
        top_row_l.setContentsMargins(0, 0, 0, 0)

        vis_group = QGroupBox("Structure Visualization")
        self.vis_layout = QVBoxLayout(vis_group)
        self.fig = Figure(figsize=(6, 6))
        self.ax = self.fig.add_subplot(111, projection='3d')
        self.canvas = FigureCanvas(self.fig)
        self.vis_layout.addWidget(self.canvas)
        top_row_l.addWidget(vis_group, 1)

        quick_actions = QGroupBox("Structure actions", top_row)
        quick_actions_l = QVBoxLayout(quick_actions)
        quick_actions_l.setContentsMargins(0, 0, 0, 0)
        quick_actions_l.setSpacing(8)

        self.save_btn = QPushButton("Save Structure...")
        self.save_btn.setMinimumWidth(150)
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._on_save_structure)
        quick_actions_l.addWidget(self.save_btn)

        self.assign_elements_btn = QPushButton("Edit the structure")
        self.assign_elements_btn.setEnabled(False)
        self.assign_elements_btn.clicked.connect(self._on_assign_elements)
        quick_actions_l.addWidget(self.assign_elements_btn)

        quick_actions_l.addStretch(1)
        quick_actions.setMaximumWidth(220)
        top_row_l.addWidget(quick_actions, 0)

        content_layout.addWidget(top_row, 2)

        # Lattice parameters
        lattice_group = QGroupBox("Lattice Parameters")
        lattice_layout = QGridLayout(lattice_group)

        self.lattice_labels = {}
        params = ['a', 'b', 'c', 'α', 'β', 'γ']
        for i, param in enumerate(params):
            label = QLabel(f"{param}:")
            value = QLabel("–")
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lattice_layout.addWidget(label, i // 3, (i % 3) * 2)
            lattice_layout.addWidget(value, i // 3, (i % 3) * 2 + 1)
            self.lattice_labels[param] = value

        lattice_layout.addWidget(QLabel("Lattice vectors (Å):"), 2, 0, 1, 6)
        self.lattice_matrix_labels = []
        for i in range(3):
            row_labels = []
            for j in range(3):
                lbl = QLabel("–")
                lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                lattice_layout.addWidget(lbl, 3 + i, j * 2, 1, 2)
                row_labels.append(lbl)
            self.lattice_matrix_labels.append(row_labels)

        # Structure information (moved beside lattice parameters)
        info_group = QGroupBox("Structure Information")
        info_layout = QVBoxLayout(info_group)
        self.converged_label = QLabel("")
        self.converged_label.setStyleSheet("font-weight: bold;")
        info_layout.addWidget(self.converged_label)

        self.info_label = QLabel("No structure loaded.\n\nUse Structure menu to create, load, or download a structure.")
        self.info_label.setWordWrap(True)
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        info_layout.addWidget(self.info_label)

        params_row = QWidget()
        params_row_l = QHBoxLayout(params_row)
        params_row_l.setContentsMargins(0, 0, 0, 0)
        params_row_l.addWidget(lattice_group, 1)
        params_row_l.addWidget(info_group, 1)

        content_layout.addWidget(params_row, 0)

        # Atomic positions table
        positions_group = QGroupBox("Atomic Positions")
        positions_layout = QVBoxLayout(positions_group)
        self.positions_table = QTableWidget(0, 9)
        self.positions_table.setHorizontalHeaderLabels(["Site", "Element", "Color", "x (Å)", "y (Å)", "z (Å)", "x (scaled)", "y (scaled)", "z (scaled)"])
        self.positions_table.horizontalHeader().setStretchLastSection(False)
        self.positions_table.verticalHeader().setVisible(False)
        header = self.positions_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.positions_table.setColumnWidth(0, 80)
        self.positions_table.setColumnWidth(1, 160)
        self.positions_table.setColumnWidth(2, 30)
        self.positions_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.positions_table.setMouseTracking(True)
        self.positions_table.viewport().setMouseTracking(True)
        self.positions_table.cellEntered.connect(self._on_positions_table_hovered)
        self.positions_table.viewport().installEventFilter(self)
        positions_layout.addWidget(self.positions_table)
        content_layout.addWidget(positions_group, 1)

        self._left_stack.addWidget(self._left_content_widget)
        self._left_stack.setCurrentWidget(self.welcome_widget)

        splitter.addWidget(viewer_widget)

        # Right panel: actions
        actions_widget = QWidget()
        actions_layout = QVBoxLayout(actions_widget)
        actions_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        actions_group = QWidget()
        actions_group_layout = QVBoxLayout(actions_group)

        actions_group_layout.addSpacing(5)

        sprkkr_label = QLabel("SPRKKR Tools:")
        sprkkr_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        actions_group_layout.addWidget(sprkkr_label)

        self.create_input_btn = QPushButton("Create SPRKKR Input File...")
        self.create_input_btn.clicked.connect(self._on_create_sprkkr_input)
        actions_group_layout.addWidget(self.create_input_btn)

        self.load_input_btn = QPushButton("Load SPRKKR Input File...")
        self.load_input_btn.clicked.connect(self._on_load_sprkkr_input)
        actions_group_layout.addWidget(self.load_input_btn)

        self.load_output_btn = QPushButton("Load SPRKKR Output File...")
        self.load_output_btn.clicked.connect(self._on_load_sprkkr_output)
        actions_group_layout.addWidget(self.load_output_btn)

        self.save_input_btn = QPushButton("Save SPRKKR Input File...")
        self.save_input_btn.setEnabled(False)
        self.save_input_btn.clicked.connect(self._on_save_sprkkr_input)
        actions_group_layout.addWidget(self.save_input_btn)

        self.input_params_preview = QPlainTextEdit()
        self.input_params_preview.setReadOnly(True)
        self.input_params_preview.mouseDoubleClickEvent = lambda *args: self._on_create_sprkkr_input
        self.input_params_preview.setPlaceholderText("SPRKKR input parameters preview")
        self.input_params_preview.setMinimumHeight(120)
        actions_group_layout.addWidget(self.input_params_preview)

        dir_row = QWidget()
        dir_row_l = QHBoxLayout(dir_row)
        dir_row_l.setContentsMargins(0, 0, 0, 0)
        dir_row_l.setSpacing(6)
        dir_caption = QLabel("Directory:")
        dir_row_l.addWidget(dir_caption)
        self._directory_label = QLabel("—")
        self._directory_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        dir_row_l.addWidget(self._directory_label, 1)
        self._directory_choose_btn = QToolButton()
        self._directory_choose_btn.setToolTip("Choose directory")
        self._directory_choose_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self._directory_choose_btn.clicked.connect(self._choose_directory)
        dir_row_l.addWidget(self._directory_choose_btn, 0)
        actions_group_layout.addWidget(dir_row)

        self._update_directory_label()

        self.run_calc_btn = QPushButton("Run SPRKKR Calculation...")
        self.run_calc_btn.setEnabled(False)
        self.run_calc_btn.clicked.connect(self._on_run_sprkkr_calculation)
        actions_group_layout.addWidget(self.run_calc_btn)

        actions_group_layout.addStretch(1)
        actions_layout.addWidget(actions_group)

        actions_widget.setMaximumWidth(350)
        splitter.addWidget(actions_widget)

        # Set splitter sizes
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        try:
            splitter.setSizes([1000, 350])
        except Exception:
            pass

    def _on_create_structure(self) -> None:
        """Create a new structure using the dialog chain."""
        result = chain_dialogs(
            select_spacegroup,
            select_site_elements,
            back=True,
            kwargs={ 'parent': self }
        )
        # chain_dialogs now returns the actual result from the last dialog
        # select_site_elements returns an Atoms object or None
        if result is not None:
            self.set_structure(result)

    def _on_load_structure(self) -> None:
        """Load structure from file."""
        from ase.io.formats import ioformats

        exts = {
            f"*.{ext}"
            for fmt in ioformats.values()
            for ext in (fmt.extensions or [])
        }
        exts = sorted(exts)

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Structure File",
            "",
            f"Structure Files ({' '.join(exts)});;All Files (*)"
        )

        if file_path:
            self._load_structure_from_path(file_path)

    def _on_download_structure(self) -> None:
        """Download structure from Materials Project."""
        QMessageBox.information(
            self,
            "Materials Project",
            "Materials Project integration not yet implemented.\n\n"
            "This feature will allow downloading structures by material ID or searching the database."
        )
        # TODO: Implement Materials Project API integration

    def _on_save_structure(self) -> None:
        """Save current structure to file."""
        if self.atoms is None:
            return

        from ase.io.formats import ioformats
        exts = {
            " ".join((f"*.{ext}" for ext in (fmt.extensions))) : fmt.name
            for fmt in ioformats.values() if fmt.extensions
        }
        exts["*"] = "All Files"

        file_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save Structure File",
            "",
            ";;".join(f"{v} ({k})" for k, v in exts.items())
        )

        if file_path:
            # Extract the extension from the selected filter
            import re
            match = re.search(r"\*\.(\w+)", selected_filter)
            if match:
                ext = match.group(1)
                if not file_path.lower().endswith("." + ext):
                    file_path += "." + ext
            try:
                ase_write(file_path, self.atoms)
                self._add_recent_file(file_path)
            except Exception as e:
                QMessageBox.critical(self, "Save Error", f"Failed to save structure:\n{str(e)}")

    def _on_create_sprkkr_input(self) -> None:
        params = select_input_parameters(self.atoms, parent=self)
        if params is None:
            return
        self.set_input_parameters(params)

    def _on_load_sprkkr_input(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Input File",
            "",
            "SPRKKR Input Files (*.inp *.in *.txt);;All Files (*)"
        )
        if file_path:
            self._load_sprkkr_input_from_path(file_path)

    def _load_sprkkr_input_from_path(self, file_path: str) -> None:
        try:
            from ase2sprkkr.input_parameters.input_parameters import InputParameters  # type: ignore
            params = InputParameters.from_file(file_path)
        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Failed to load input parameters:\n{str(e)}")
            return
        self.set_input_parameters(params)

    def _choose_output_related_load_options(self, input_available: bool, potential_available: bool) -> Optional[tuple[bool, bool]]:
        dialog = QDialog(self)
        dialog.setWindowTitle("Load Associated Files")
        layout = QVBoxLayout(dialog)

        intro = QLabel("Load associated files from the selected SPRKKR output?")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        input_cb = QCheckBox("Load associated input file")
        input_cb.setChecked(True)
        input_cb.setEnabled(input_available)
        layout.addWidget(input_cb)
        if not input_available:
            layout.addWidget(QLabel("  Associated input file is not available."))

        potential_cb = QCheckBox("Load associated potential as structure")
        potential_cb.setChecked(True)
        potential_cb.setEnabled(potential_available)
        layout.addWidget(potential_cb)
        if not potential_available:
            layout.addWidget(QLabel("  Associated potential file is not available."))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return (input_cb.isChecked(), potential_cb.isChecked())

    def _on_load_sprkkr_output(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load SPRKKR Output File",
            "",
            "SPRKKR Output Files (*.out *.log *.txt);;All Files (*)"
        )
        if not file_path:
            return

        try:
            from ase2sprkkr.outputs.task_result import TaskResult  # type: ignore
            parsed = TaskResult.from_file(file_path)
            result = parsed.run() if hasattr(parsed, 'run') else parsed
        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Failed to load SPRKKR output:\n{str(e)}")
            return

        self._last_sprkkr_result = result

        input_path = None
        potential_path = None
        try:
            if hasattr(result, 'files') and 'input' in result.files:
                input_path = result.path_to('input')
        except Exception:
            input_path = None
        try:
            if hasattr(result, 'files') and 'potential' in result.files:
                potential_path = result.path_to('potential')
        except Exception:
            potential_path = None

        input_available = bool(input_path and Path(input_path).is_file())
        potential_available = bool(potential_path and Path(potential_path).is_file())

        options = self._choose_output_related_load_options(input_available, potential_available)
        if options is None:
            return

        load_input, load_potential = options

        if load_input and input_available and input_path is not None:
            self._load_sprkkr_input_from_path(input_path)

        if load_potential and potential_available and potential_path is not None:
            try:
                from ase2sprkkr.potentials.potentials import Potential  # type: ignore
                atoms = Potential.from_file(potential_path).atoms
                self.set_structure(atoms)
            except Exception as e:
                QMessageBox.warning(self, "Potential Load Warning", f"Failed to load structure from potential:\n{str(e)}")

        self.directory = str(Path(file_path).resolve().parent)
        self._update_directory_label()
        self.enable_run_calculation()

    def _on_save_sprkkr_input(self) -> None:
        if self._input_parameters is None:
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Input File",
            "",
            "SPRKKR Input Files (*.inp *.in *.txt);;All Files (*)"
        )
        if not file_path:
            return

        try:
            if hasattr(self._input_parameters, "to_file"):
                self._input_parameters.to_file(file_path)
                return
            try:
                txt = self._input_parameters.to_string(validate=False)
            except Exception:
                txt = str(self._input_parameters)
            Path(file_path).write_text(txt, encoding="utf-8")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save input parameters:\n{str(e)}")

    def set_input_parameters(self, params: Any) -> None:
        self._input_parameters = params
        self._update_input_params_preview()
        if self.save_input_btn is not None:
            self.save_input_btn.setEnabled(bool(self._input_parameters))
        self.enable_run_calculation()
        self.create_input_btn.setText("Edit SPRKKR Input File...")

    def _on_run_sprkkr_calculation(self) -> None:
        """Run SPRKKR calculation."""
        if self.atoms is None or self._input_parameters is None or not self.directory:
            return

        from .sprkkr_run_window import SprkkrRunWindow

        self._sprkkr_run_window = SprkkrRunWindow(
            atoms=self.atoms,
            input_parameters=self._input_parameters,
            directory=self.directory,
            parent=self,
        )
        self._sprkkr_run_window.show()

    def handle_sprkkr_finished_result(self, result: Any) -> None:
        self._last_sprkkr_result = result

    def _on_about(self) -> None:
        """Show about dialog."""
        QMessageBox.about(
            self,
            "About Guy4ASE",
            "Guy4ASE - Structure Manager\n\n"
            "A tool for creating, loading, and manipulating atomic structures\n"
            "with integration for SPRKKR calculations.\n\n"
            "Built with ASE and PyQt6."
        )

    def set_structure(self, atoms: Any) -> None:  # atoms is ASE Atoms object
        """Set the current structure and update all views."""
        self.atoms = atoms
        self._update_structure_view()
        self._enable_actions(True)
        self._update_input_params_preview()

    def _enable_actions(self, enabled: bool) -> None:
        """Enable or disable action buttons based on structure availability."""
        self.save_btn.setEnabled(enabled)
        self.assign_elements_btn.setEnabled(enabled)
        self.enable_run_calculation()

    def enable_run_calculation(self) -> None:
        enabled = bool(self.atoms is not None and self._input_parameters and self.directory)
        self.run_calc_btn.setEnabled(enabled)

    def _update_structure_view(self) -> None:
        """Update all structure visualization and information panels."""
        if self.atoms is None:
            self._clear_view()
            return

        if self._left_stack is not None and self._left_content_widget is not None:
            self._left_stack.setCurrentWidget(self._left_content_widget)

        self._update_visualization()
        self._update_lattice_params()
        self._update_positions_table()
        self._update_info_label()

    def _clear_view(self) -> None:
        """Clear all visualization panels."""
        if self._left_stack is not None:
            self._left_stack.setCurrentWidget(self.welcome_widget)
        self._site_colors = {}

        for lbl in self.lattice_labels.values():
            lbl.setText("–")

        for row in self.lattice_matrix_labels:
            for lbl in row:
                lbl.setText("–")

        self.positions_table.setRowCount(0)
        self._hovered_atom_index = None
        self.info_label.setText("No structure loaded.\n\nUse Structure menu to create, load, or download a structure.")
        self._update_input_params_preview()

    def _on_positions_table_hovered(self, row: int, column: int) -> None:
        if self.atoms is None:
            return
        if row < 0 or row >= len(self.atoms):
            return
        if self._hovered_atom_index == row:
            return
        self._hovered_atom_index = row
        self._update_visualization()

    def _on_assign_elements(self) -> None:
        if self.atoms is None:
            return

        result = select_site_elements(self.atoms, parent=self, back=False)
        if isinstance(result, str):
            return
        if result is None:
            return
        self.set_structure(result)

    def eventFilter(self, obj, event):  # type: ignore[override]
        if obj is getattr(self, 'positions_table', None).viewport():
            if event.type() == QEvent.Type.Leave:
                if self._hovered_atom_index is not None:
                    self._hovered_atom_index = None
                    self._update_visualization()
        return super().eventFilter(obj, event)

    def _update_visualization(self) -> None:
        """Update 3D visualization of the structure."""
        if self.atoms is None:
            return
        self.ax.clear()

        arrays = getattr(self.atoms, 'arrays', {})
        kinds = arrays.get('spacegroup_kinds')
        lattice = self.atoms.get_cell()
        plot_lattice(self.ax, lattice)

        scaled = self.atoms.get_scaled_positions()
        if kinds is None:
            kinds = list(range(len(scaled)))
        self._site_colors = color_map = self._compute_site_colors(kinds)

        start = 0
        def view(pos, color, hoovered=False):
            if hoovered:
                size = 60
                color = 'black'
            else:
                size = 40
            plot_sites_in_lattice(
                self.ax,
                lattice,
                pos.reshape((-1, 3)),
                color=color,
                edgecolor='black',
                linewidths=0.9,
                s=size
            )

        old = None
        for idx, kind in enumerate(kinds):
            if idx == self._hovered_atom_index:
                kind = view
            if kind != old:
                if old is not None:
                    view(scaled[start:idx], color_map.get(old, '#1f77b4'), old is view)
                start = idx
                old = kind

        view(scaled[start:], color_map.get(old, '#1f77b4'), old is view)
        self.canvas.draw()

    def _update_lattice_params(self) -> None:
        """Update lattice parameters display."""
        if self.atoms is None:
            return

        try:
            cell = self.atoms.get_cell()
            lengths = cell.lengths()
            angles = cell.angles()

            self.lattice_labels['a'].setText(f"{lengths[0]:.4f} Å")
            self.lattice_labels['b'].setText(f"{lengths[1]:.4f} Å")
            self.lattice_labels['c'].setText(f"{lengths[2]:.4f} Å")
            self.lattice_labels['α'].setText(f"{angles[0]:.2f}°")
            self.lattice_labels['β'].setText(f"{angles[1]:.2f}°")
            self.lattice_labels['γ'].setText(f"{angles[2]:.2f}°")

            # Update matrix
            for i in range(3):
                for j in range(3):
                    self.lattice_matrix_labels[i][j].setText(f"{cell[i, j]:8.4f}")
        except Exception as e:
            print(f"Lattice params error: {e}")

    def _update_positions_table(self) -> None:
        """Update atomic positions table."""
        if self.atoms is None:
            self.positions_table.setRowCount(0)
            return

        positions = self.atoms.get_positions()
        symbols = self.atoms.get_chemical_symbols()
        arrays = getattr(self.atoms, 'arrays', {})
        empty = [None] * len(symbols)
        kinds = arrays.get('spacegroup_kinds', empty)
        occs = self.atoms.info.get('occupancy', {})
        labels = arrays.get('labels', empty)
        color_lookup = self._site_colors
        self.positions_table.setRowCount(len(positions))
        scaled_positions = self.atoms.get_scaled_positions()
        counter = {}

        for i, (sym, pos, scaled_pos, kind, label) in enumerate(zip(symbols, positions, scaled_positions, kinds, labels)):
            if not label:
                if sym in counter:
                    counter[sym] += 1
                else:
                    counter[sym] = 1
                label = f"{sym}.{counter[sym]}"

            occ = occs.get(str(kinds[i]), None) if kind is not None else None
            comp_text = self._format_site_composition(occ) or sym

            item_site = QTableWidgetItem(label)
            item_comp = QTableWidgetItem(comp_text)

            color_hex = color_lookup.get(kind, '#1f77b4')
            item_color = QTableWidgetItem("")
            qcolor = QColor(color_hex)
            item_color.setBackground(qcolor)
            #r, g, b, _ = qcolor.getRgb()
            #luminance = 0.299 * r + 0.587 * g + 0.114 * b
            #if luminance < 140:
            #    item_color.setForeground(QColor("white"))

            self.positions_table.setItem(i, 0, item_site)
            self.positions_table.setItem(i, 1, item_comp)
            self.positions_table.setItem(i, 2, item_color)
            align_num = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

            for j in range(0, 3):
                item = QTableWidgetItem(f"{pos[j]:.4f}")
                item.setTextAlignment(align_num)
                self.positions_table.setItem(i, 3 + j, item)

                item_scaled = QTableWidgetItem(f"{scaled_pos[j]:.4f}")
                item_scaled.setTextAlignment(align_num)
                self.positions_table.setItem(i, 6 + j, item_scaled)


    def _update_info_label(self) -> None:
        """Update structure information label."""
        if self.atoms is None:
            return
        if self.atoms and hasattr(self.atoms, 'has_potential') and \
            self.atoms.has_potential():
                status = self.atoms.potential.SCF_INFO.SCFSTATUS()
                if status != 'START':
                    self.converged_label.setText(f"SCF Status: {status}")
        else:
            self.converged_label.setText("")

        n_atoms = len(self.atoms)
        formula_raw = self.atoms.get_chemical_formula()
        assigned_counts = self._collect_assigned_counts()

        if assigned_counts:
            formula_text = self._format_formula_from_counts(assigned_counts)
            info_text = f"Assigned formula: {formula_text}\n"
        else:
            info_text = f"Formula: {formula_raw}\n"

        info_text += f"Number of atoms: {n_atoms}\n"

        info_text += "\nComposition:\n"
        if assigned_counts:
            for element, count in sorted(assigned_counts.items()):
                info_text += f"  {element}: {count:.2f}\n"
        else:
            from collections import Counter
            symbols = self.atoms.get_chemical_symbols()
            species_count = Counter(symbols)
            for element, count in sorted(species_count.items()):
                info_text += f"  {element}: {count}\n"

        self.info_label.setText(info_text)

    def _compute_site_colors(self, spacegroup_kinds: Sequence[Any]) -> Dict[Any, str]:
        kinds = list(set(spacegroup_kinds))
        cmap = cm.get_cmap('tab20', max(len(kinds), 1))
        base_colors = list(getattr(cmap, 'colors', []))
        if not base_colors:
            steps = max(len(kinds), 1)
            base_colors = [cmap(i / max(steps - 1, 1)) for i in range(steps)]
        colors: Dict[Any, str] = {}
        n = len(base_colors)
        for idx, kind in enumerate(kinds):
            rgba = base_colors[idx % n]
            colors[kind] = to_hex(rgba)
        return colors

    def _format_site_composition(self, occ_dict: Any) -> str:
        if not isinstance(occ_dict, dict) or not occ_dict:
            return None
        parts = []
        for species, value in occ_dict.items():
            try:
                val = float(value)
            except Exception:
                continue
            if val <= 0.0:
                continue
            sym = re.sub(r'_\d+$', '', species)
            parts.append(f"{sym}:{val:.2f}")
        return ", ".join(parts) if parts else None

    def _collect_assigned_counts(self) -> Dict[str, float]:
        arrays = getattr(self.atoms, 'arrays', {}) if self.atoms is not None else {}
        occs = arrays.get('occupancy') if 'occupancy' in arrays else None
        counts: Dict[str, float] = {}
        if occs is None or len(occs) == 0:
            return counts
        for entry in occs:
            if not isinstance(entry, dict):
                continue
            for species, value in entry.items():
                sym = getattr(species, 'symbol', str(species))
                try:
                    counts[sym] = counts.get(sym, 0.0) + float(value)
                except Exception:
                    continue
        return counts

    def _format_formula_from_counts(self, counts: Dict[str, float]) -> str:
        if not counts:
            return "—"
        positives = [v for v in counts.values() if v > 1e-6]
        if not positives:
            return "—"
        min_val = min(positives)
        normalized = {sym: value / min_val for sym, value in counts.items() if value > 1e-6}
        parts = []
        for sym, val in sorted(normalized.items()):
            if abs(val - 1.0) < 1e-2:
                suffix = ""
            elif abs(val - round(val)) < 1e-2:
                whole = int(round(val))
                suffix = "" if whole == 1 else str(whole)
            else:
                suffix = f"{val:.2f}"
            parts.append(f"{sym}{suffix}")
        return "".join(parts) if parts else "—"
