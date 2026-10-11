from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QAction, QColor
from PyQt6.QtWidgets import (
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
from guy4ase.gui.application.calculation_runs import ActiveRunRegistry
from guy4ase.gui.application.recent_files import RecentFiles, RecentKind
from guy4ase.gui.application.settings import ApplicationSettings
from guy4ase.gui.application.window_geometry import manage_window_geometry
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.dialogs.object_view import execute_value_action
from guy4ase.gui.dialogs.settings import edit_settings
from guy4ase.gui.dialogs.structures.transforms import (
    repeat_atoms,
    rotate_atoms,
    scale_atoms,
)
from guy4ase.gui.flows import calculation as calculation_flow
from guy4ase.gui.flows import files as file_flows
from guy4ase.gui.flows import input_editing as input_editing_flow
from guy4ase.gui.flows import structures as structure_flows
from guy4ase.gui.flows import visualization as visualization_flow
from guy4ase.gui.plots.lattice import plot_atoms_preview
from guy4ase.gui.widgets.result_actions import ResultActionsWidget
from guy4ase.physics.composition import site_composition, structure_formula


class MainWindow(QMainWindow):
    """Main application window for structure creation, loading, and manipulation."""

    def __init__(
        self,
        controller: WorkspaceController,
        recent_files: RecentFiles,
        active_runs: ActiveRunRegistry,
        settings: ApplicationSettings | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Guy4ASE - Structure Manager")
        manage_window_geometry(
            self,
            "structure-manager",
            default_size=(1400, 800),
            default_maximized=True,
        )

        self.controller = controller
        self.workspace = self.controller.workspace
        self.recent_history = recent_files
        self.active_runs = active_runs
        self.settings = settings or ApplicationSettings()
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
        self._update_potential_path_label()
        self._update_structure_view()
        self._refresh_action_availability()
        self._update_input_params_preview()

    def _workspace_input_parameters_changed(self, _parameters: Any) -> None:
        self._refresh_input_parameters()

    def _refresh_input_parameters(self) -> None:
        parameters = self.workspace.input_parameters
        self._update_input_params_preview()
        self._refresh_action_availability()
        self.create_input_btn.setText(
            "Edit SPRKKR Input File..."
            if parameters is not None
            else "Create SPRKKR Input File..."
        )

    def _workspace_directory_changed(self) -> None:
        self._refresh_directory()

    def _refresh_directory(self) -> None:
        self._update_directory_label()
        self._refresh_action_availability()

    def _refresh_action_availability(self) -> None:
        """Keep shared expert actions synchronized with workspace state."""
        has_structure = self.workspace.atoms is not None
        for action in (
            self.save_structure_action,
            self.edit_structure_action,
            self.scale_structure_action,
            self.repeat_structure_action,
            self.rotate_structure_action,
            self.build_2d_structure_action,
            self.visualize_structure_action,
        ):
            action.setEnabled(has_structure)

        self.run_calculation_action.setEnabled(self.workspace.can_calculate())

        empty_spheres = self.workspace.empty_spheres_action()
        self.empty_spheres_action.setVisible(empty_spheres is not None)
        if empty_spheres is not None:
            self.empty_spheres_action.setText(
                "Recalculate Empty Spheres"
                if empty_spheres == "recalculate"
                else "Add Empty Spheres"
            )

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

        self.save_structure_action = QAction("&Save Structure...", self)
        self.save_structure_action.triggered.connect(self._on_save_structure)
        structure_menu.addAction(self.save_structure_action)

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

        run_menu = menubar.addMenu("&Run")
        self.empty_spheres_action = QAction("Add Empty Spheres", self)
        self.empty_spheres_action.triggered.connect(
            lambda: structure_flows.update_empty_spheres(self.controller, self)
        )
        run_menu.addAction(self.empty_spheres_action)
        run_menu.addSeparator()
        self.run_calculation_action = QAction("Run SPRKKR Calculation...", self)
        self.run_calculation_action.triggered.connect(
            self._on_run_sprkkr_calculation
        )
        run_menu.addAction(self.run_calculation_action)

        view_menu = menubar.addMenu("&View")
        self.visualize_structure_action = QAction("&Visualize Structure", self)
        self.visualize_structure_action.triggered.connect(self._visualize_structure)
        view_menu.addAction(self.visualize_structure_action)

        tools_menu = menubar.addMenu("&Tools")
        settings_action = QAction("&Settings...", self)
        settings_action.setMenuRole(QAction.MenuRole.PreferencesRole)
        settings_action.triggered.connect(self._open_settings)
        tools_menu.addAction(settings_action)

        self.edit_structure_action = QAction("&Edit the structure...", self)
        self.edit_structure_action.setShortcut("Ctrl+E")
        self.edit_structure_action.triggered.connect(self._on_assign_elements)
        structure_menu.addAction(self.edit_structure_action)

        structure_menu.addSeparator()

        self.scale_structure_action = QAction("&Scale...", self)
        self.scale_structure_action.triggered.connect(self._on_scale_structure)
        structure_menu.addAction(self.scale_structure_action)

        self.repeat_structure_action = QAction("&Repeat...", self)
        self.repeat_structure_action.triggered.connect(self._on_repeat_structure)
        structure_menu.addAction(self.repeat_structure_action)

        self.rotate_structure_action = QAction("R&otate...", self)
        self.rotate_structure_action.triggered.connect(self._on_rotate_structure)
        structure_menu.addAction(self.rotate_structure_action)

        self.build_2d_structure_action = QAction("Build &2D Structure...", self)
        self.build_2d_structure_action.triggered.connect(self.build_2d_structure)
        structure_menu.addAction(self.build_2d_structure_action)

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

        self._refresh_action_availability()

    def _visualize_structure(self) -> None:
        visualization_flow.visualize_structure(self.controller, self.settings, self)

    def _open_settings(self) -> None:
        edit_settings(self.settings, self)

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

        self.save_btn = QToolButton(quick_actions)
        self.save_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.save_btn.setDefaultAction(self.save_structure_action)
        self.save_btn.setMinimumWidth(150)
        quick_actions_l.addWidget(self.save_btn)

        self.assign_elements_btn = QToolButton(quick_actions)
        self.assign_elements_btn.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        self.assign_elements_btn.setDefaultAction(self.edit_structure_action)
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
        self._directory_choose_btn.clicked.connect(
            lambda _checked=False: calculation_flow.choose_working_directory(
                self.controller,
                self,
                title="Select Directory",
            )
        )
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

        self.run_calc_btn = QToolButton()
        self.run_calc_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.run_calc_btn.setDefaultAction(self.run_calculation_action)
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
        input_editing_flow.create_input_parameters(
            self.controller,
            self,
            task=task,
        )

    def _on_input_preview_double_click(self, event) -> None:
        self._on_edit_sprkkr_input()
        if event is not None:
            event.accept()

    def _on_edit_sprkkr_input(self, _checked=False) -> None:
        """Edit current input without changing task; create SCF only if none exists."""
        input_editing_flow.edit_current_input_parameters(
            self.controller,
            self,
        )

    def _on_load_sprkkr_input(self) -> None:
        input_editing_flow.load_and_edit_input_parameters(
            self.controller,
            self.recent_history,
            self,
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
        self._result_actions_widget.set_results(self.workspace.result_history)

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
        if self.workspace.atoms is None:
            return
        if row < 0 or row >= len(self.workspace.atoms):
            return
        if self._hovered_atom_index == row:
            return
        self._hovered_atom_index = row
        self._update_visualization()

    def _on_assign_elements(self) -> None:
        structure_flows.edit_site_elements(self.controller, self)

    def _on_scale_structure(self) -> None:
        structure_flows.edit_current_structure(
            self.controller,
            self,
            scale_atoms,
            error_title="Scale Error",
        )

    def _on_repeat_structure(self) -> None:
        structure_flows.edit_current_structure(
            self.controller,
            self,
            repeat_atoms,
            error_title="Repeat Error",
        )

    def _on_rotate_structure(self) -> None:
        structure_flows.edit_current_structure(
            self.controller,
            self,
            rotate_atoms,
            error_title="Rotate Error",
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
        self._update_visualization()

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
        status = self.workspace.scf_status()
        status_text = ""
        if self.workspace.is_scf_converged():
            status_text = "SCF Status: CONVERGED"
        elif status and status != "START":
            status_text = f"SCF Status: {status}"
        self.converged_label.setText(status_text)

        n_atoms = len(atoms)
        info_text = f"Formula: {structure_formula(atoms)}\n"
        info_text += f"Number of atoms: {n_atoms}\n"

        self.info_label.setText(info_text)
