from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Any, Dict, Optional

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QAction, QColor
from PyQt6.QtWidgets import (
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
from ase2sprkkr import SPRKKRAtoms

from guy4ase.ase.element_assignment import ElementAssignmentDraft
from guy4ase.gui.application.calculation_runs import ActiveRunRegistry
from guy4ase.gui.application.recent_files import RecentFiles, RecentKind
from guy4ase.gui.application.workspace_controller import Busy, WorkspaceController
from guy4ase.gui.dialogs.expert_input import (
    edit_input_parameters,
    select_input_parameters,
)
from guy4ase.gui.dialogs.object_view import execute_value_action
from guy4ase.gui.dialogs.structures.element_assignment import select_site_elements
from guy4ase.gui.dialogs.structures.transforms import (
    repeat_atoms,
    rotate_atoms,
    scale_atoms,
)
from guy4ase.gui.flows import calculation as calculation_flow
from guy4ase.gui.flows import files as file_flows
from guy4ase.gui.flows import structures as structure_flows
from guy4ase.gui.misc.qt_structure_access import QtStructureAccess
from guy4ase.gui.misc.structure_wait import (
    document_change_applied,
    wait_for_structure,
)
from guy4ase.gui.plots.lattice import plot_atoms_preview
from guy4ase.gui.widgets.result_actions import ResultActionsWidget
from guy4ase.physics.composition import site_composition, structure_formula


def _copy_optional_atoms(atoms: Any) -> Any:
    return None if atoms is None else atoms.copy()


class MainWindow(QMainWindow):
    """Main application window for structure creation, loading, and manipulation."""

    def __init__(
        self,
        controller: WorkspaceController,
        recent_files: RecentFiles,
        active_runs: ActiveRunRegistry,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Guy4ASE - Structure Manager")
        self.resize(1400, 800)

        self.controller = controller
        self.workspace = self.controller.workspace
        self._structure_access = QtStructureAccess(
            self.controller.structure_gate, self
        )
        self.recent_history = recent_files
        self.active_runs = active_runs
        self._site_colors: Dict[str, str] = {}
        self._hovered_atom_index: Optional[int] = None
        self.input_params_preview: Optional[QPlainTextEdit] = None
        self.save_input_btn: Optional[QPushButton] = None
        self._directory_label: Optional[QLabel] = None
        self._potential_path_label: Optional[QLabel] = None
        self._directory_choose_btn: Optional[QToolButton] = None
        self._result_group: Optional[QGroupBox] = None
        self._result_actions_widget: Optional[ResultActionsWidget] = None

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
        self._connect_workspace()
        self.recent_history.changed.connect(self._refresh_recent_menus)
        self._refresh_recent_menus()
        self._workspace_structure_changed(self.workspace.atoms)
        self._workspace_input_parameters_changed(
            self.workspace.input_parameters
        )
        self._workspace_directory_changed()
        self._refresh_result_panel()

    def _connect_workspace(self) -> None:
        """Render controller changes without moving view logic into the model."""
        self.controller.structureChanged.connect(
            self._workspace_structure_changed
        )
        self.controller.inputParametersChanged.connect(
            self._workspace_input_parameters_changed
        )
        self.controller.directoryChanged.connect(
            lambda _directory: self._workspace_directory_changed()
        )
        self.controller.resultChanged.connect(
            lambda _result: self._refresh_result_panel()
        )

    def _workspace_structure_changed(self, _atoms: Any) -> None:
        self._structure_access.retry(
            self._workspace_structure_changed_locked,
            reason="refreshing the structure view",
        )

    def _workspace_structure_changed_locked(self) -> None:
        atoms = self.workspace.atoms
        self._update_potential_path_label()
        self._update_structure_view()
        self._enable_actions(atoms is not None)
        self._update_input_params_preview()

    def _workspace_input_parameters_changed(self, _parameters: Any) -> None:
        self._refresh_input_parameters()

    def _refresh_input_parameters(self) -> None:
        parameters = self.workspace.input_parameters
        self._update_input_params_preview()
        self.enable_run_calculation()
        self.create_input_btn.setText(
            "Edit SPRKKR Input File..."
            if parameters is not None
            else "Create SPRKKR Input File..."
        )

    def _workspace_directory_changed(self) -> None:
        self._refresh_directory()

    def _refresh_directory(self) -> None:
        self._update_directory_label()
        self.enable_run_calculation()

    def _update_input_params_preview(self) -> None:
        if self.input_params_preview is None:
            return
        if self.workspace.input_parameters is None:
            self.input_params_preview.setPlainText("")
            if self.save_input_btn is not None:
                self.save_input_btn.setEnabled(False)
            return
        try:
            txt = self.workspace.input_parameters.to_string(validate=False)
        except Exception:
            txt = str(self.workspace.input_parameters)
        self.input_params_preview.setPlainText(txt)
        if self.save_input_btn is not None:
            self.save_input_btn.setEnabled(True)

    def _update_directory_label(self) -> None:
        if self._directory_label is None:
            return
        if not self.workspace.directory:
            self._directory_label.setText("—")
            self._directory_label.setToolTip("")
            return
        self._directory_label.setText(self.workspace.directory)
        self._directory_label.setToolTip(self.workspace.directory)

    def _update_potential_path_label(self) -> None:
        if self._potential_path_label is None:
            return
        value = self.workspace.potential_path or "—"
        self._potential_path_label.setText(value)
        self._potential_path_label.setToolTip(self.workspace.potential_path or "")

    def _choose_directory(self) -> None:
        start_dir = self.workspace.directory or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Select Directory", start_dir)
        if not chosen:
            return
        self.controller.change_working_directory(str(chosen))

    def _refresh_recent_menu(self, what: RecentKind) -> None:
        handlers = {
            'structure': lambda path: self.open_recent_file('structure', path),
            'input': lambda path: self.open_recent_file('input', path),
            'output': lambda path: self.open_recent_file('output', path),
        }
        menu = self._recent_menus[what]
        if menu is None:
            return
        menu.clear()
        recent_files = self.recent_history.paths(what)
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

    def open_recent_file(self, kind: RecentKind, file_path: str) -> None:
        """Open a persisted recent file through the shared GUI workflow."""
        file_flows.open_recent(
            self.controller,
            self.recent_history,
            kind,
            file_path,
            self,
        )

    def _refresh_recent_start_button(self) -> None:
        btn = self._recent_start_button
        if btn is None:
            return

        structures = self.recent_history.paths("structure")
        outputs = self.recent_history.paths("output")
        has_recent = bool(structures or outputs)
        btn.setVisible(has_recent)
        if not has_recent:
            return

        default_kind = self.recent_history.last_kind
        if default_kind == 'structure' and not structures:
            default_kind = None
        if default_kind == 'output' and not outputs:
            default_kind = None
        if default_kind not in {'structure', 'output'}:
            if outputs:
                default_kind = 'output'
            else:
                default_kind = 'structure'
        default_path = self.recent_history.paths(default_kind)[0]

        btn.setText(f"Continue: {Path(default_path).name}")
        btn.setToolTip(default_path)

        menu = self._recent_start_menu
        if menu is None:
            menu = QMenu(btn)
            self._recent_start_menu = menu
            btn.setMenu(menu)

        menu.clear()
        structures_menu = menu.addMenu("Structures")
        if structures:
            for file_path in structures:
                action = QAction(file_path, self)
                action.triggered.connect(lambda _checked=False, p=file_path: self.open_recent_file('structure', p))
                structures_menu.addAction(action)
        else:
            empty_action = QAction("(No recent files)", self)
            empty_action.setEnabled(False)
            structures_menu.addAction(empty_action)

        outputs_menu = menu.addMenu("Outputs")
        if outputs:
            for file_path in outputs:
                action = QAction(file_path, self)
                action.triggered.connect(lambda _checked=False, p=file_path: self.open_recent_file('output', p))
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
            btn.clicked.connect(lambda _checked=False, p=default_path: self.open_recent_file('output', p))
        else:
            btn.clicked.connect(lambda _checked=False, p=default_path: self.open_recent_file('structure', p))

    def _build_ui(self) -> None:
        """Build the main UI layout from its visual sections."""
        self._build_menu_bar()

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        splitter.addWidget(self._build_structure_view())
        splitter.addWidget(self._build_actions_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        try:
            splitter.setSizes([1000, 350])
        except Exception:
            pass

    def _build_menu_bar(self) -> None:
        # Menu bar
        menubar = self.menuBar()

        # Structure menu
        structure_menu = menubar.addMenu("&Structure")

        create_action = QAction("&Create New...", self)
        create_action.setShortcut("Ctrl+N")
        create_action.triggered.connect(self.create_structure)
        structure_menu.addAction(create_action)

        create_database_action = QAction(
            "Create from &Prototype Database...", self
        )
        create_database_action.triggered.connect(
            self.create_structure_from_database
        )
        structure_menu.addAction(create_database_action)

        download_action = QAction(
            "&Download from Online Database...", self
        )
        download_action.triggered.connect(self.download_structure)
        structure_menu.addAction(download_action)

        load_action = QAction("&Load from File...", self)
        load_action.setShortcut("Ctrl+O")
        load_action.triggered.connect(self.load_structure)
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
        load_output_action.triggered.connect(self.load_sprkkr_output)
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
        build_2d_action.triggered.connect(self.build_2d_structure)
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

    def _build_structure_view(self) -> QWidget:
        viewer_widget = QWidget()
        viewer_layout = QVBoxLayout(viewer_widget)
        self._left_stack = QStackedWidget(viewer_widget)
        viewer_layout.addWidget(self._left_stack, 1)
        self._build_welcome_page()
        self._build_structure_info_panel()
        self._left_stack.setCurrentWidget(self.welcome_widget)
        return viewer_widget

    def _build_welcome_page(self) -> None:
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
        create_btn.clicked.connect(self.create_structure)
        welcome_layout.addWidget(create_btn, 0, Qt.AlignmentFlag.AlignCenter)

        welcome_layout.addSpacing(15)

        create_database_btn = QPushButton(
            "Create Structure from Prototype Database"
        )
        create_database_btn.setMinimumWidth(btn_width)
        create_database_btn.setMinimumHeight(45)
        create_database_btn.setStyleSheet("font-size: 11pt; padding: 8px;")
        create_database_btn.clicked.connect(
            self.create_structure_from_database
        )
        welcome_layout.addWidget(
            create_database_btn, 0, Qt.AlignmentFlag.AlignCenter
        )

        welcome_layout.addSpacing(15)

        download_btn = QPushButton("Download Structure from Online Database")
        download_btn.setMinimumWidth(btn_width)
        download_btn.setMinimumHeight(45)
        download_btn.setStyleSheet("font-size: 11pt; padding: 8px;")
        download_btn.clicked.connect(self.download_structure)
        welcome_layout.addWidget(download_btn, 0, Qt.AlignmentFlag.AlignCenter)

        welcome_layout.addSpacing(15)

        load_btn = QPushButton("Load from File...")
        load_btn.setMinimumWidth(btn_width)
        load_btn.setMinimumHeight(45)
        load_btn.setStyleSheet("font-size: 11pt; padding: 8px;")
        load_btn.clicked.connect(self.load_structure)
        welcome_layout.addWidget(load_btn, 0, Qt.AlignmentFlag.AlignCenter)

        welcome_layout.addSpacing(15)

        load_output_btn = QPushButton("Load SPRKKR Output File...")
        load_output_btn.setMinimumWidth(btn_width)
        load_output_btn.setMinimumHeight(45)
        load_output_btn.setStyleSheet("font-size: 11pt; padding: 8px;")
        load_output_btn.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView)
        )
        load_output_btn.clicked.connect(self.load_sprkkr_output)
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

    def _build_structure_info_panel(self) -> None:
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

    def _build_actions_panel(self) -> QWidget:
        actions_widget = QWidget()
        actions_layout = QVBoxLayout(actions_widget)
        actions_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        actions_group = QWidget()
        actions_group_layout = QVBoxLayout(actions_group)
        self._build_input_panel(actions_group_layout)
        self._build_calculation_panel(actions_group_layout)
        actions_layout.addWidget(actions_group)
        actions_layout.addWidget(self._build_results_panel(), 1)
        actions_widget.setMaximumWidth(350)
        return actions_widget

    def _build_input_panel(self, layout: QVBoxLayout) -> None:
        layout.addSpacing(5)

        sprkkr_label = QLabel("SPRKKR Tools:")
        sprkkr_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(sprkkr_label)

        self.create_input_btn = QPushButton("Create SPRKKR Input File...")
        self.create_input_btn.clicked.connect(self._on_edit_sprkkr_input)
        layout.addWidget(self.create_input_btn)

        self.load_input_btn = QPushButton("Load SPRKKR Input File...")
        self.load_input_btn.clicked.connect(self._on_load_sprkkr_input)
        layout.addWidget(self.load_input_btn)

        self.save_input_btn = QPushButton("Save SPRKKR Input File...")
        self.save_input_btn.setEnabled(False)
        self.save_input_btn.clicked.connect(self._on_save_sprkkr_input)
        layout.addWidget(self.save_input_btn)

        self.input_params_preview = QPlainTextEdit()
        self.input_params_preview.setReadOnly(True)
        self.input_params_preview.mouseDoubleClickEvent = self._on_input_preview_double_click
        self.input_params_preview.setPlaceholderText("SPRKKR input parameters preview")
        self.input_params_preview.setMinimumHeight(120)
        layout.addWidget(self.input_params_preview)

    def _build_calculation_panel(self, layout: QVBoxLayout) -> None:
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
        layout.addWidget(dir_row)

        potential_row = QWidget()
        potential_row_l = QHBoxLayout(potential_row)
        potential_row_l.setContentsMargins(0, 0, 0, 0)
        potential_row_l.setSpacing(6)
        potential_row_l.addWidget(QLabel("Potential:"))
        self._potential_path_label = QLabel("—")
        self._potential_path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        potential_row_l.addWidget(self._potential_path_label, 1)
        layout.addWidget(potential_row)

        self._update_directory_label()

        self.run_calc_btn = QPushButton("Run SPRKKR Calculation...")
        self.run_calc_btn.setEnabled(False)
        self.run_calc_btn.clicked.connect(self._on_run_sprkkr_calculation)
        layout.addWidget(self.run_calc_btn)

        self.load_output_btn = QPushButton("Load SPRKKR Output File...")
        self.load_output_btn.clicked.connect(self.load_sprkkr_output)
        layout.addWidget(self.load_output_btn)

    def _build_results_panel(self) -> QGroupBox:
        self._result_group = QGroupBox("Calculation Result")
        result_layout = QVBoxLayout(self._result_group)
        self._result_actions_widget = ResultActionsWidget(
            lambda value, action: execute_value_action(value, action, self),
            show_values_without_actions=True,
            parent=self._result_group,
        )
        result_layout.addWidget(self._result_actions_widget, 1)
        return self._result_group

    def create_structure(self) -> None:
        """Start the shared structure-creation workflow."""
        structure_flows.create_structure(self.controller, self)

    def create_structure_from_database(self) -> None:
        """Create a structure from a database prototype using shared editors."""
        structure_flows.create_structure_from_database(self.controller, self)

    def load_structure(self) -> None:
        """Start the shared structure-loading workflow."""
        file_flows.choose_and_load_structure(
            self.controller, self.recent_history, self
        )

    def download_structure(self) -> None:
        """Download a structure from a configured online provider."""
        structure_flows.download_structure(self.controller, self)

    def _on_save_structure(self) -> None:
        """Save current structure to file."""
        file_flows.save_structure(
            self.controller, self.recent_history, self
        )

    def _on_create_sprkkr_input(self, task: str = "scf") -> None:
        # QPushButton.clicked passes a bool; retain SCF as the expert-mode default.
        if not isinstance(task, str):
            task = "scf"
        snapshot = wait_for_structure(
            self,
            partial(
                self.controller.read_structure,
                _copy_optional_atoms,
                reason="reading the structure for the parameter editor",
            ),
        )
        if isinstance(snapshot, Busy):
            return
        generation, atoms = snapshot
        params = select_input_parameters(atoms, parent=self, task=task)
        if params is None:
            return
        document_change_applied(
            self,
            self.controller.replace_input_parameters(
                params, expected_generation=generation
            ),
        )

    def _on_input_preview_double_click(self, event) -> None:
        self._on_edit_sprkkr_input()
        if event is not None:
            event.accept()

    def _on_edit_sprkkr_input(self, _checked=False) -> None:
        """Edit current input without changing task; create SCF only if none exists."""
        if self.workspace.input_parameters is None:
            self._on_create_sprkkr_input()
            return
        snapshot = wait_for_structure(
            self,
            partial(
                self.controller.read_structure,
                _copy_optional_atoms,
                reason="reading the structure for the parameter editor",
            ),
        )
        if isinstance(snapshot, Busy):
            return
        generation, atoms = snapshot
        parameters = self.workspace.input_parameters
        if parameters is None:
            return
        parameters = parameters.copy(copy_values=True)
        result = edit_input_parameters(
            parameters, parent=self, atoms=atoms
        )
        if result is not None:
            document_change_applied(
                self,
                self.controller.replace_input_parameters(
                    result, expected_generation=generation
                ),
            )

    def _on_load_sprkkr_input(self) -> None:
        loaded = file_flows.choose_and_load_input_parameters(
            self.controller, self.recent_history, self
        )
        if not loaded or self.workspace.input_parameters is None:
            return
        snapshot = wait_for_structure(
            self,
            partial(
                self.controller.read_structure,
                _copy_optional_atoms,
                reason="reading the structure for the imported parameter editor",
            ),
        )
        if isinstance(snapshot, Busy):
            return
        generation, atoms = snapshot
        candidate = self.workspace.input_parameters
        if candidate is None:
            return
        candidate = candidate.copy(copy_values=True)
        edited = edit_input_parameters(
            candidate,
            parent=self,
            show_changed_only=True,
            atoms=atoms,
        )
        if edited is not None:
            document_change_applied(
                self,
                self.controller.replace_input_parameters(
                    edited, expected_generation=generation
                ),
            )

    def load_sprkkr_output(self) -> None:
        """Start the shared output-loading workflow."""
        file_flows.choose_and_load_output(
            self.controller, self.recent_history, self
        )

    def _on_save_sprkkr_input(self) -> None:
        file_flows.save_input_parameters(
            self.controller, self.recent_history, self
        )

    def _on_run_sprkkr_calculation(self) -> None:
        """Start the shared calculation workflow."""
        calculation_flow.run_calculation(
            self.controller, self.recent_history, self.active_runs, self
        )

    def _refresh_result_panel(self) -> None:
        self._result_actions_widget.set_result(self.workspace.result)

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

    def _enable_actions(self, enabled: bool) -> None:
        """Enable or disable action buttons based on structure availability."""
        self.save_btn.setEnabled(enabled)
        self.assign_elements_btn.setEnabled(enabled)
        self.enable_run_calculation()

    def enable_run_calculation(self) -> None:
        enabled = bool(self.workspace.atoms is not None and self.workspace.input_parameters and self.workspace.directory)
        self.run_calc_btn.setEnabled(enabled)

    def _update_structure_view(self) -> None:
        """Update all structure visualization and information panels."""
        if self.workspace.atoms is None:
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
        self.converged_label.setText("")

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
        def update() -> None:
            if self.workspace.atoms is None:
                return
            if row < 0 or row >= len(self.workspace.atoms):
                return
            if self._hovered_atom_index == row:
                return
            self._hovered_atom_index = row
            self._update_visualization()

        self._structure_access.retry(
            update, reason="highlighting an atom"
        )

    def _on_assign_elements(self) -> None:
        if self.workspace.atoms is None:
            return
        draft_result = wait_for_structure(
            self,
            partial(
                self.controller.read_structure,
                ElementAssignmentDraft,
                reason="reading the structure for element assignment",
            ),
        )
        if isinstance(draft_result, Busy):
            return
        generation, draft = draft_result
        result = select_site_elements(
            draft, parent=self, back=False, apply=False
        )
        if isinstance(result, str):
            return
        if result is None:
            return
        def apply_draft(_atoms: Any) -> Any:
            return result.apply()

        change = wait_for_structure(
            self,
            partial(
                self.controller.apply_structure_edit,
                apply_draft,
                expected_generation=generation,
            ),
        )
        if not isinstance(change, Busy):
            document_change_applied(self, change)

    def _on_scale_structure(self) -> None:
        self._apply_structure_edit(scale_atoms, error_title="Scale Error")

    def _on_repeat_structure(self) -> None:
        self._apply_structure_edit(repeat_atoms, error_title="Repeat Error")

    def _on_rotate_structure(self) -> None:
        self._apply_structure_edit(rotate_atoms, error_title="Rotate Error")

    def _apply_structure_edit(self, editor, *, error_title: str) -> None:
        """Apply one expert-window modal structure transformation."""
        snapshot = wait_for_structure(
            self,
            partial(
                self.controller.read_structure,
                _copy_optional_atoms,
                reason="reading the structure for an editor",
            ),
        )
        if isinstance(snapshot, Busy):
            return
        generation, source = snapshot
        if source is None:
            QMessageBox.information(self, "No Structure", "Load or create a structure first.")
            return

        try:
            atoms = editor(source, parent=self)
            if atoms is None:
                return
            change = wait_for_structure(
                self,
                partial(
                    self.controller.replace_structure,
                    atoms,
                    expected_generation=generation,
                ),
            )
            if not isinstance(change, Busy):
                document_change_applied(self, change)
        except Exception as e:
            QMessageBox.critical(
                self,
                error_title,
                f"Failed to edit structure:\n{e!s}",
            )

    def build_2d_structure(self, _checked: bool = False, *, surface_mode: bool = False) -> None:
        structure_flows.build_2d_structure(
            self.controller, self, surface_mode=surface_mode
        )

    def eventFilter(self, obj, event):  # type: ignore[override]
        if obj is getattr(self, 'positions_table', None).viewport():
            if event.type() == QEvent.Type.Leave:
                if self._hovered_atom_index is not None:
                    self._hovered_atom_index = None
                    self._update_visualization_nonblocking()
        return super().eventFilter(obj, event)

    def _update_visualization_nonblocking(self) -> None:
        self._structure_access.retry(
            self._update_visualization,
            reason="refreshing the structure visualization",
        )

    def _update_visualization(self) -> None:
        """Update 3D visualization of the structure."""
        if self.workspace.atoms is None:
            return
        self._site_colors = plot_atoms_preview(
            self.ax,
            self.workspace.atoms,
            canvas=self.canvas,
            hovered_atom_indices=self._hovered_atom_index,
        )

    def _update_lattice_params(self) -> None:
        """Update lattice parameters display."""
        if self.workspace.atoms is None:
            return

        try:
            cell = self.workspace.atoms.get_cell()
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
        if self.workspace.atoms is None:
            self.positions_table.setRowCount(0)
            return

        positions = self.workspace.atoms.get_positions()
        symbols = self.workspace.atoms.get_chemical_symbols()
        arrays = getattr(self.workspace.atoms, 'arrays', {})
        empty = [None] * len(symbols)
        kinds = arrays.get('spacegroup_kinds', empty)
        labels = arrays.get('labels', empty)
        color_lookup = self._site_colors
        self.positions_table.setRowCount(len(positions))
        scaled_positions = self.workspace.atoms.get_scaled_positions()
        counter = {}

        for i, (sym, pos, scaled_pos, kind, label) in enumerate(zip(symbols, positions, scaled_positions, kinds, labels)):
            if not label:
                if sym in counter:
                    counter[sym] += 1
                else:
                    counter[sym] = 1
                label = f"{sym}.{counter[sym]}"

            comp_text = site_composition(self.workspace.atoms, i)

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

            for j in range(3):
                item = QTableWidgetItem(f"{pos[j]:.4f}")
                item.setTextAlignment(align_num)
                self.positions_table.setItem(i, 3 + j, item)

                item_scaled = QTableWidgetItem(f"{scaled_pos[j]:.4f}")
                item_scaled.setTextAlignment(align_num)
                self.positions_table.setItem(i, 6 + j, item_scaled)


    def _update_info_label(self) -> None:
        """Update structure information label."""
        atoms = self.workspace.atoms
        if atoms is None:
            return
        status_text = ""
        if isinstance(atoms, SPRKKRAtoms):
            status = atoms.potential.SCF_INFO.SCFSTATUS()
            if status and status != 'START':
                status_text = f"SCF Status: {status}"
        self.converged_label.setText(status_text)

        n_atoms = len(atoms)
        info_text = f"Formula: {structure_formula(atoms)}\n"
        info_text += f"Number of atoms: {n_atoms}\n"

        self.info_label.setText(info_text)
