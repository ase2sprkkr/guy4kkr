from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

import platformdirs
from ase.io import read as ase_read
from ase.io import write as ase_write
from ase2sprkkr.outputs.task_result import TaskResult
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from guy4ase.gui.dialogs.expert_input import (
    edit_input_parameters,
    select_input_parameters,
)
from guy4ase.gui.dialogs.guided_input import select_guided_input_parameters
from guy4ase.gui.dialogs.object_view import show_readonly_object_dialog
from guy4ase.gui.dialogs.structures.build_2d import select_build_2d_structure
from guy4ase.gui.dialogs.structures.database import select_structure_prototype
from guy4ase.gui.dialogs.structures.element_assignment import select_site_elements
from guy4ase.gui.dialogs.structures.online_database import select_online_structure
from guy4ase.gui.dialogs.structures.spacegroup_selector import (
    select_spacegroup,
    select_spacegroup_from_prototype,
)
from guy4ase.gui.dialogs.structures.transforms import (
    repeat_atoms,
    rotate_atoms,
    scale_atoms,
)
from guy4ase.gui.misc.dialog_flow import chain_dialogs
from guy4ase.gui.plots.lattice import plot_atoms_preview
from guy4ase.gui.widgets.result_actions import ResultActionsWidget


class MainWindow(QMainWindow):
    """Main application window for structure creation, loading, and manipulation."""

    structureChanged = pyqtSignal(object)
    calculationResultChanged = pyqtSignal(object)

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
        self._potential_path: Optional[str] = None
        self._directory_label: Optional[QLabel] = None
        self._potential_path_label: Optional[QLabel] = None
        self._directory_choose_btn: Optional[QToolButton] = None
        self._sprkkr_run_window: Optional[QWidget] = None
        self._last_sprkkr_result: Optional[Any] = None
        self._result_group: Optional[QGroupBox] = None
        self._result_actions_widget: Optional[ResultActionsWidget] = None
        self._open_result_dialogs: list[QDialog] = []

        self._recent_files: Dict[str, list[str]] = {
            'structure': [],
            'input': [],
            'output': [],
        }
        self._last_recent_kind: Optional[str] = None
        self._recent_menus: Dict[str, Optional[QMenu]] = {
            'structure': None,
            'input': None,
            'output': None,
        }
        self._recent_start_button: Optional[QToolButton] = None
        self._recent_start_menu: Optional[QMenu] = None

        self._left_stack: Optional[QStackedWidget] = None
        self._left_content_widget: Optional[QWidget] = None

        self._build_ui()
        self._load_recent_files()
        self._refresh_recent_menus()
        self._update_structure_view()
        self._refresh_result_panel()

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

    def _update_potential_path_label(self) -> None:
        if self._potential_path_label is None:
            return
        value = self._potential_path or "—"
        self._potential_path_label.setText(value)
        self._potential_path_label.setToolTip(self._potential_path or "")

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
        def normalize_recent_list(value: Any) -> list[str]:
            if not isinstance(value, list):
                return []
            return [str(item) for item in value]

        try:
            if not path.exists():
                return
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                self._recent_files['structure'] = normalize_recent_list(data)
                return
            if not isinstance(data, dict):
                return
            recent_files = data.get('recent_files')
            if isinstance(recent_files, dict):
                for key in ('structure', 'input', 'output'):
                    self._recent_files[key] = normalize_recent_list(recent_files.get(key, []))
            last_kind = data.get('last_recent_kind')
            if last_kind in {'structure', 'output'}:
                self._last_recent_kind = last_kind
        except Exception:
            if not self._recent_files[self._last_kind]:
                    self._last_kind = None

    def _save_recent_files(self) -> None:
        path = self._recent_files_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                'recent_files': self._recent_files,
                'last_recent_kind': self._last_recent_kind,
            }
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            # Non-fatal (e.g. read-only home); keep UI working.
            pass

    def _remember_recent(self, kind: str, file_path: str) -> None:
        file_path = str(Path(file_path))
        recent = self._recent_files[kind]
        try:
            recent.remove(file_path)
        except ValueError:
            recent[:] = recent[:9]
        recent.insert(0, file_path)
        if kind in {'structure', 'output'}:
            self._last_recent_kind = kind
        self._save_recent_files()
        self._refresh_recent_menus()

    def _refresh_recent_menu(self, what: str) -> None:
        handlers = {
            'structure': lambda path: self._open_recent_file('structure', path),
            'input': lambda path: self._open_recent_file('input', path),
            'output': lambda path: self._open_recent_file('output', path),
        }
        menu = self._recent_menus[what]
        if menu is None:
            return
        menu.clear()
        recent_files = self._recent_files[what]
        if not recent_files:
            empty_action = QAction("(No recent files)", self)
            empty_action.setEnabled(False)
            menu.addAction(empty_action)
            return
        handler = handlers[what]
        for file_path in recent_files:
            action = QAction(file_path, self)
            action.triggered.connect(lambda _checked=False, p=file_path, h=handler: h(p))
            menu.addAction(action)

    def _refresh_recent_menus(self) -> None:
        for what in ('structure', 'input', 'output'):
            self._refresh_recent_menu(what)
        self._refresh_recent_start_button()

    def _open_recent_file(self, kind: str, file_path: str) -> None:
        path = Path(file_path)
        if not path.exists():
            QMessageBox.warning(self, "Missing File", f"File not found:\n{file_path}")
            self._recent_files[kind] = [p for p in self._recent_files[kind] if p != file_path]
            self._save_recent_files()
            self._refresh_recent_menus()
            return
        loaders = {
            'structure': self._load_structure_from_path,
            'input': self._load_sprkkr_input_from_path,
            'output': self._load_sprkkr_output_from_path,
        }
        loaders[kind](file_path)

    def _refresh_recent_start_button(self) -> None:
        btn = self._recent_start_button
        if btn is None:
            return

        has_recent = bool(self._recent_files['structure'] or self._recent_files['output'])
        btn.setVisible(has_recent)
        if not has_recent:
            return

        default_kind = self._last_recent_kind
        if default_kind == 'structure' and not self._recent_files['structure']:
            default_kind = None
        if default_kind == 'output' and not self._recent_files['output']:
            default_kind = None
        if default_kind not in {'structure', 'output'}:
            if self._recent_files['output']:
                default_kind = 'output'
            else:
                default_kind = 'structure'
        default_path = self._recent_files[default_kind][0]

        btn.setText(f"Continue: {Path(default_path).name}")
        btn.setToolTip(default_path)

        menu = self._recent_start_menu
        if menu is None:
            menu = QMenu(btn)
            self._recent_start_menu = menu
            btn.setMenu(menu)

        menu.clear()
        structures_menu = menu.addMenu("Structures")
        if self._recent_files['structure']:
            for file_path in self._recent_files['structure']:
                action = QAction(file_path, self)
                action.triggered.connect(lambda _checked=False, p=file_path: self._open_recent_file('structure', p))
                structures_menu.addAction(action)
        else:
            empty_action = QAction("(No recent files)", self)
            empty_action.setEnabled(False)
            structures_menu.addAction(empty_action)

        outputs_menu = menu.addMenu("Outputs")
        if self._recent_files['output']:
            for file_path in self._recent_files['output']:
                action = QAction(file_path, self)
                action.triggered.connect(lambda _checked=False, p=file_path: self._open_recent_file('output', p))
                outputs_menu.addAction(action)
        else:
            empty_action = QAction("(No recent files)", self)
            empty_action.setEnabled(False)
            outputs_menu.addAction(empty_action)

        # Primary click action loads most recent
        try:
            btn.clicked.disconnect()
        except TypeError:
            pass
        if default_kind == 'output':
            btn.clicked.connect(lambda _checked=False, p=default_path: self._open_recent_file('output', p))
        else:
            btn.clicked.connect(lambda _checked=False, p=default_path: self._open_recent_file('structure', p))

    def _load_structure_from_path(self, file_path: str) -> None:
        try:
            atoms = ase_read(file_path)
            resolved = Path(file_path).resolve()
            is_potential = resolved.suffix.lower() in {'.pot', '.pot_new'}
            self.directory = str(resolved.parent)
            self.set_structure(atoms, potential_path=str(resolved) if is_potential else None)
            self._update_directory_label()
            self._remember_recent('structure', file_path)
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

        create_database_action = QAction(
            "Create from &Prototype Database...", self
        )
        create_database_action.triggered.connect(
            self._on_create_structure_from_database
        )
        structure_menu.addAction(create_database_action)

        download_action = QAction(
            "&Download from Online Database...", self
        )
        download_action.triggered.connect(self._on_download_structure)
        structure_menu.addAction(download_action)

        load_action = QAction("&Load from File...", self)
        load_action.setShortcut("Ctrl+O")
        load_action.triggered.connect(self._on_load_structure)
        structure_menu.addAction(load_action)

        self._recent_menus['structure'] = structure_menu.addMenu("Open &Recent")

        input_menu = menubar.addMenu("&Input")
        load_input_action = QAction("&Load Input File...", self)
        load_input_action.triggered.connect(self._on_load_sprkkr_input)
        input_menu.addAction(load_input_action)
        save_input_action = QAction("&Save Input File...", self)
        save_input_action.triggered.connect(self._on_save_sprkkr_input)
        input_menu.addAction(save_input_action)
        self._recent_menus['input'] = input_menu.addMenu("Open &Recent")

        output_menu = menubar.addMenu("&Output")
        load_output_action = QAction("&Load Output File...", self)
        load_output_action.triggered.connect(self._on_load_sprkkr_output)
        output_menu.addAction(load_output_action)
        self._recent_menus['output'] = output_menu.addMenu("Open &Recent")

        assign_elements_action = QAction("&Edit the structure...", self)
        assign_elements_action.setShortcut("Ctrl+E")
        assign_elements_action.triggered.connect(self._on_assign_elements)
        structure_menu.addAction(assign_elements_action)

        structure_menu.addSeparator()

        scale_action = QAction("&Scale...", self)
        scale_action.triggered.connect(self._on_scale_structure)
        structure_menu.addAction(scale_action)

        repeat_action = QAction("&Repeat...", self)
        repeat_action.triggered.connect(self._on_repeat_structure)
        structure_menu.addAction(repeat_action)

        rotate_action = QAction("R&otate...", self)
        rotate_action.triggered.connect(self._on_rotate_structure)
        structure_menu.addAction(rotate_action)

        build_2d_action = QAction("Build &2D Structure...", self)
        build_2d_action.triggered.connect(self._on_build_2d_structure)
        structure_menu.addAction(build_2d_action)

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
        btn_width = 300

        create_btn = QPushButton("Create New Structure")
        create_btn.setMinimumWidth(btn_width)
        create_btn.setMinimumHeight(45)
        create_btn.setStyleSheet("font-size: 11pt; padding: 8px;")
        create_btn.clicked.connect(self._on_create_structure)
        welcome_layout.addWidget(create_btn, 0, Qt.AlignmentFlag.AlignCenter)

        welcome_layout.addSpacing(15)

        create_database_btn = QPushButton(
            "Create Structure from Prototype Database"
        )
        create_database_btn.setMinimumWidth(btn_width)
        create_database_btn.setMinimumHeight(45)
        create_database_btn.setStyleSheet("font-size: 11pt; padding: 8px;")
        create_database_btn.clicked.connect(
            self._on_create_structure_from_database
        )
        welcome_layout.addWidget(
            create_database_btn, 0, Qt.AlignmentFlag.AlignCenter
        )

        welcome_layout.addSpacing(15)

        download_btn = QPushButton("Download Structure from Online Database")
        download_btn.setMinimumWidth(btn_width)
        download_btn.setMinimumHeight(45)
        download_btn.setStyleSheet("font-size: 11pt; padding: 8px;")
        download_btn.clicked.connect(self._on_download_structure)
        welcome_layout.addWidget(download_btn, 0, Qt.AlignmentFlag.AlignCenter)

        welcome_layout.addSpacing(15)

        load_btn = QPushButton("Load from File...")
        load_btn.setMinimumWidth(btn_width)
        load_btn.setMinimumHeight(45)
        load_btn.setStyleSheet("font-size: 11pt; padding: 8px;")
        load_btn.clicked.connect(self._on_load_structure)
        welcome_layout.addWidget(load_btn, 0, Qt.AlignmentFlag.AlignCenter)

        welcome_layout.addSpacing(15)

        load_output_btn = QPushButton("Load SPRKKR Output File...")
        load_output_btn.setMinimumWidth(btn_width)
        load_output_btn.setMinimumHeight(45)
        load_output_btn.setStyleSheet("font-size: 11pt; padding: 8px;")
        load_output_btn.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView)
        )
        load_output_btn.clicked.connect(self._on_load_sprkkr_output)
        welcome_layout.addWidget(load_output_btn, 0, Qt.AlignmentFlag.AlignCenter)

        # Recent start button (shown only when there are recent files)
        self._recent_start_button = QToolButton(self.welcome_widget)
        self._recent_start_button.setMinimumWidth(btn_width)
        self._recent_start_button.setMinimumHeight(45)
        self._recent_start_button.setStyleSheet("font-size: 11pt; padding: 8px;")
        self._recent_start_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self._recent_start_button.hide()
        welcome_layout.addWidget(self._recent_start_button, 0, Qt.AlignmentFlag.AlignCenter)

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
        self.create_input_btn.clicked.connect(self._on_edit_sprkkr_input)
        actions_group_layout.addWidget(self.create_input_btn)

        self.load_input_btn = QPushButton("Load SPRKKR Input File...")
        self.load_input_btn.clicked.connect(self._on_load_sprkkr_input)
        actions_group_layout.addWidget(self.load_input_btn)

        self.save_input_btn = QPushButton("Save SPRKKR Input File...")
        self.save_input_btn.setEnabled(False)
        self.save_input_btn.clicked.connect(self._on_save_sprkkr_input)
        actions_group_layout.addWidget(self.save_input_btn)

        self.input_params_preview = QPlainTextEdit()
        self.input_params_preview.setReadOnly(True)
        self.input_params_preview.mouseDoubleClickEvent = self._on_input_preview_double_click
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

        potential_row = QWidget()
        potential_row_l = QHBoxLayout(potential_row)
        potential_row_l.setContentsMargins(0, 0, 0, 0)
        potential_row_l.setSpacing(6)
        potential_row_l.addWidget(QLabel("Potential:"))
        self._potential_path_label = QLabel("—")
        self._potential_path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        potential_row_l.addWidget(self._potential_path_label, 1)
        actions_group_layout.addWidget(potential_row)

        self._update_directory_label()

        self.run_calc_btn = QPushButton("Run SPRKKR Calculation...")
        self.run_calc_btn.setEnabled(False)
        self.run_calc_btn.clicked.connect(self._on_run_sprkkr_calculation)
        actions_group_layout.addWidget(self.run_calc_btn)

        self.load_output_btn = QPushButton("Load SPRKKR Output File...")
        self.load_output_btn.clicked.connect(self._on_load_sprkkr_output)
        actions_group_layout.addWidget(self.load_output_btn)

        actions_layout.addWidget(actions_group)

        self._result_group = QGroupBox("Calculation Result")
        result_layout = QVBoxLayout(self._result_group)
        self._result_actions_widget = ResultActionsWidget(
            self._execute_output_value_action,
            show_values_without_actions=True,
            parent=self._result_group,
        )
        result_layout.addWidget(self._result_actions_widget, 1)

        actions_layout.addWidget(self._result_group, 1)

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

    def _on_create_structure_from_database(self) -> None:
        """Create a structure from a database prototype using shared editors."""
        result = chain_dialogs(
            select_structure_prototype,
            select_spacegroup_from_prototype,
            select_site_elements,
            back=True,
            kwargs={"parent": self},
        )
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
        """Download a structure from a configured online provider."""
        result = select_online_structure(parent=self)
        if result is not None:
            self.set_structure(result)

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
                self._remember_recent('structure', file_path)
            except Exception as e:
                QMessageBox.critical(self, "Save Error", f"Failed to save structure:\n{str(e)}")

    def _on_create_sprkkr_input(self, task: str = "scf") -> None:
        # QPushButton.clicked passes a bool; retain SCF as the expert-mode default.
        if not isinstance(task, str):
            task = "scf"
        params = select_input_parameters(self.atoms, parent=self, task=task)
        if params is None:
            return
        self.set_input_parameters(params)

    def _on_create_guided_input(self, task: str) -> None:
        if self.atoms is None:
            QMessageBox.information(self, "No Structure", "Load or create a structure first.")
            return
        selection = select_guided_input_parameters(
            task,
            parent=self,
            directory=self.directory,
            atoms=self.atoms,
        )
        if selection is not None:
            params, directory = selection
            self.directory = directory
            self._update_directory_label()
            self.set_input_parameters(params)
            self._on_run_sprkkr_calculation()

    def _on_input_preview_double_click(self, event) -> None:
        self._on_edit_sprkkr_input()
        if event is not None:
            event.accept()

    def _on_edit_sprkkr_input(self, _checked=False) -> None:
        """Edit current input without changing task; create SCF only if none exists."""
        if self._input_parameters is None:
            self._on_create_sprkkr_input()
            return
        result = edit_input_parameters(self._input_parameters, parent=self, atoms=self.atoms)
        if result is not None:
            self.set_input_parameters(result)

    def _on_load_sprkkr_input(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Input File",
            "",
            "SPRKKR Input Files (*.inp *.in *.txt);;All Files (*)"
        )
        if file_path:
            if self._load_sprkkr_input_from_path(file_path) and self._input_parameters is not None:
                candidate = self._input_parameters.copy(copy_values=True)
                edited = edit_input_parameters(candidate, parent=self, show_changed_only=True, atoms=self.atoms)
                if edited is not None:
                    self.set_input_parameters(edited)

    def _load_sprkkr_input_from_path(self, file_path: str) -> bool:
        try:
            from ase2sprkkr.input_parameters.input_parameters import (
                InputParameters,  # type: ignore
            )
            params = InputParameters.from_file(file_path)
        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Failed to load input parameters:\n{str(e)}")
            return False
        self.set_input_parameters(params)
        self._remember_recent('input', file_path)
        return True

    def _on_load_sprkkr_output(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load SPRKKR Output File",
            "",
            "SPRKKR Output Files (*.out *.log *.txt);;All Files (*)"
        )
        if not file_path:
            return

        self._load_sprkkr_output_from_path(file_path)

    def _load_sprkkr_output_from_path(self, file_path: str) -> None:
        try:
            result = TaskResult.from_file(file_path)
            self._last_sprkkr_result = result
            self._remember_recent('output', file_path)
            self._refresh_result_panel()
        except Exception as e:
            breakpoint()  # For debugging purposes; can be removed in production
            QMessageBox.critical(self, "Load Error", f"Failed to load SPRKKR output:\n{str(e)}")
            return

        potential_key = 'converged' if 'converged' in result.files else 'potential'
        potential_path = result.path_to(potential_key) if potential_key in result.files else None
        potential_available = bool(potential_path and Path(potential_path).is_file())

        if potential_available:
            try:
                from ase2sprkkr.potentials.potentials import Potential  # type: ignore
                atoms = Potential.from_file(potential_path).atoms
                self.set_structure(atoms, potential_path=str(Path(potential_path).resolve()))
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
            self._input_parameters.to_file(file_path)
            self._remember_recent('input', file_path)
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

        from guy4ase.gui.dialogs.run_calculation import SprkkrRunWindow

        self._sprkkr_run_window = SprkkrRunWindow(
            atoms=self.atoms,
            input_parameters=self._input_parameters,
            directory=self.directory,
            parent=self,
        )
        self._sprkkr_run_window.show()

    def _execute_output_value_action(
        self,
        value: Any,
        action: str,
        *,
        parent: Optional[QWidget] = None,
    ) -> None:
        parent = parent or self
        try:
            if action in {'edit', 'data'}:
                payload = value.data() if action == 'data' else value()
                title = getattr(value, "display_name", value.name)
                dialog = show_readonly_object_dialog(payload, title=f'View {title}', parent=parent)
                self._open_result_dialogs.append(dialog)
                dialog.destroyed.connect(lambda _obj=None, dlg=dialog: self._forget_result_dialog(dlg))
                return

            method = getattr(value, action, None)
            method()
        except Exception as e:
            QMessageBox.critical(parent, "Action Error", f"Failed to execute action '{action}':\n{str(e)}")

    def _forget_result_dialog(self, dialog: QDialog) -> None:
        self._open_result_dialogs = [item for item in self._open_result_dialogs if item is not dialog]

    def _refresh_result_panel(self) -> None:
        self._result_actions_widget.set_result(self._last_sprkkr_result)

    def handle_sprkkr_finished_result(self, result: Any) -> None:
        self._last_sprkkr_result = result
        output_file = None
        try:
            if hasattr(result, 'files') and 'output' in result.files:
                output_file = result.path_to('output')
        except Exception:
            output_file = None
        if not output_file:
            output_file = getattr(result, 'output_file', None)
            if output_file and getattr(result, 'directory', None) and not Path(output_file).is_absolute():
                output_file = str(Path(result.directory) / output_file)
        if output_file:
            self._remember_recent('output', output_file)
            self.directory = str(Path(output_file).resolve().parent)
            self._update_directory_label()

        converged_path = None
        try:
            if hasattr(result, 'files') and 'converged' in result.files:
                converged_path = result.path_to('converged')
        except Exception:
            converged_path = None
        if not converged_path:
            try:
                converged_path = result.potential_filename
            except Exception:
                converged_path = None
        if converged_path:
            potential_file = Path(converged_path)
            if not potential_file.is_absolute():
                result_directory = getattr(result, 'directory', None) or self.directory
                if result_directory:
                    potential_file = Path(result_directory) / potential_file
        else:
            potential_file = None
        if potential_file is not None and potential_file.is_file():
            try:
                from ase2sprkkr.potentials.potentials import Potential  # type: ignore
                resolved_potential = str(potential_file.resolve())
                atoms = Potential.from_file(resolved_potential).atoms
                self.set_structure(atoms, potential_path=resolved_potential)
            except Exception as exc:
                QMessageBox.warning(
                    self,
                    "Potential Load Warning",
                    f"Calculation finished, but the generated potential could not be loaded:\n{exc}",
                )
        self._refresh_result_panel()
        self.calculationResultChanged.emit(result)

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

    def set_structure(self, atoms: Any, *, potential_path: Optional[str] = None) -> None:  # atoms is ASE Atoms object
        """Set the current structure and update all views."""
        self.atoms = atoms
        self._potential_path = potential_path
        self._update_potential_path_label()
        self._update_structure_view()
        self._enable_actions(True)
        self._update_input_params_preview()
        self.structureChanged.emit(atoms)

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

    def _on_scale_structure(self) -> None:
        if self.atoms is None:
            QMessageBox.information(self, "No Structure", "Load or create a structure first.")
            return

        try:
            atoms = scale_atoms(self.atoms, parent=self)
            if atoms is None:
                return
            self.set_structure(atoms)
        except Exception as e:
            QMessageBox.critical(self, "Scale Error", f"Failed to scale structure:\n{str(e)}")

    def _on_repeat_structure(self) -> None:
        if self.atoms is None:
            QMessageBox.information(self, "No Structure", "Load or create a structure first.")
            return

        try:
            atoms = repeat_atoms(self.atoms, parent=self)
            if atoms is None:
                return
            self.set_structure(atoms)
        except Exception as e:
            QMessageBox.critical(self, "Repeat Error", f"Failed to repeat structure:\n{str(e)}")

    def _on_rotate_structure(self) -> None:
        if self.atoms is None:
            QMessageBox.information(self, "No Structure", "Load or create a structure first.")
            return

        try:
            atoms = rotate_atoms(self.atoms, parent=self)
            if atoms is None:
                return
            self.set_structure(atoms)
        except Exception as e:
            QMessageBox.critical(self, "Rotate Error", f"Failed to rotate structure:\n{str(e)}")

    def _on_build_2d_structure(self, _checked: bool = False, *, surface_mode: bool = False) -> None:
        if self.atoms is None:
            QMessageBox.information(self, "No Structure", "Load or create a structure first.")
            return

        try:
            result = select_build_2d_structure(self.atoms, parent=self, surface_mode=surface_mode)
            if result is None:
                return
            self.set_structure(result)
        except Exception as e:
            QMessageBox.critical(self, "Build 2D Structure Error", f"Failed to build 2D structure:\n{str(e)}")

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
        self._site_colors = plot_atoms_preview(
            self.ax,
            self.atoms,
            canvas=self.canvas,
            hovered_atom_indices=self._hovered_atom_index,
        )

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
