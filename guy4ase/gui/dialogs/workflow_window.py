from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import QSize, Qt, QUrl
from PyQt6.QtGui import QAction, QColor, QDesktopServices, QIcon, QPalette
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from guy4ase.gui.application.calculation_runs import ActiveRunRegistry
from guy4ase.gui.application.recent_files import RecentFiles, RecentKind
from guy4ase.gui.application.settings import ApplicationSettings
from guy4ase.gui.application.window_geometry import manage_window_geometry
from guy4ase.gui.application.workspace_controller import Busy, WorkspaceController
from guy4ase.gui.dialogs.guided_input import select_guided_input_parameters
from guy4ase.gui.dialogs.object_view import execute_value_action
from guy4ase.gui.dialogs.settings import edit_settings
from guy4ase.gui.flows import calculation as calculation_flow
from guy4ase.gui.flows import files as file_flows
from guy4ase.gui.flows import structures as structure_flows
from guy4ase.gui.flows import visualization as visualization_flow
from guy4ase.gui.misc.qt_structure_access import QtStructureAccess
from guy4ase.gui.misc.resources import icon_path
from guy4ase.gui.misc.structure_wait import (
    document_change_applied,
    wait_for_structure,
)
from guy4ase.gui.style import (
    SPACE_LG,
    SPACE_SM,
    SPACE_XL,
    SPACE_XS,
    SPACE_XXL,
    action_card_stylesheet,
    button_stylesheet,
    group_panel_stylesheet,
    heading_font,
    secondary_text_stylesheet,
)
from guy4ase.gui.widgets.result_actions import ResultActionsWidget


def _copy_optional_atoms(atoms: Any) -> Any:
    return None if atoms is None else atoms.copy()


def _set_action_button_content(
    button: QPushButton | QToolButton,
    title: str,
    description: str,
    icon: QIcon,
    icon_size: QSize,
    *,
    menu_button: bool = False,
) -> None:
    """Lay out an action icon and text with explicit, theme-safe spacing."""
    button.setText("")
    button.setProperty("workflowActionTitle", title)
    button.setAccessibleName(title)
    button.setAccessibleDescription(description)

    layout = QHBoxLayout(button)
    layout.setContentsMargins(
        SPACE_LG, SPACE_SM, 34 if menu_button else SPACE_LG, SPACE_SM
    )
    layout.setSpacing(SPACE_LG)

    icon_label = QLabel(button)
    icon_label.setFixedSize(icon_size)
    icon_label.setPixmap(icon.pixmap(icon_size))
    icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    icon_label.setAttribute(
        Qt.WidgetAttribute.WA_TransparentForMouseEvents
    )
    layout.addWidget(icon_label)

    text_widget = QWidget(button)
    text_layout = QVBoxLayout(text_widget)
    text_layout.setContentsMargins(0, 0, 0, 0)
    text_layout.setSpacing(2)
    title_label = QLabel(title, text_widget)
    title_label.setForegroundRole(QPalette.ColorRole.ButtonText)
    title_label.setFont(heading_font(title_label.font(), "section"))
    title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    text_layout.addWidget(title_label)
    if description:
        description_label = QLabel(description, text_widget)
        description_label.setForegroundRole(QPalette.ColorRole.ButtonText)
        description_label.setWordWrap(True)
        description_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        text_layout.addWidget(description_label)
    text_widget.setSizePolicy(
        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
    )
    text_widget.setAttribute(
        Qt.WidgetAttribute.WA_TransparentForMouseEvents
    )
    layout.addWidget(text_widget, 1)


class WorkflowWindow(QMainWindow):
    """Task-oriented entry point that keeps the full UI available as expert mode."""

    _GROUP_CALCULATE = "Calculate"
    _GROUP_VIEW = "View"
    _GROUP_CREATE = "Create structure"
    _GROUP_LOAD = "Load structure"
    _GROUP_DIFFERENT = "And now something completely different..."
    _ACTION_GROUPS = (
        _GROUP_CALCULATE,
        _GROUP_VIEW,
        _GROUP_CREATE,
        _GROUP_LOAD,
        _GROUP_DIFFERENT,
    )

    def __init__(
        self,
        controller: WorkspaceController,
        recent_files: RecentFiles,
        active_runs: ActiveRunRegistry,
        *,
        open_expert: Callable[[], None],
        settings: ApplicationSettings | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Guy4ASE - Workflow")
        manage_window_geometry(
            self, "workflow", default_size=(1120, 700)
        )
        self.controller = controller
        self.workspace = self.controller.workspace
        self._structure_access = QtStructureAccess(
            self.controller.structure_gate, self
        )
        self.recent_history = recent_files
        self.active_runs = active_runs
        self.settings = settings or ApplicationSettings()
        self._open_expert = open_expert
        self.controller.structureChanged.connect(self._on_structure_changed)
        self.controller.directoryChanged.connect(
            lambda _directory: self._refresh_working_directory()
        )
        self.controller.resultChanged.connect(lambda _result: self._refresh())
        self.recent_history.changed.connect(self._refresh)
        self._build_ui()
        self._refresh_working_directory()
        self._refresh()

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(SPACE_XXL, SPACE_XL, SPACE_XL, SPACE_XL)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal, central)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)
        root.addWidget(splitter)

        content = QWidget(splitter)
        content.setMinimumWidth(480)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, SPACE_XL, 0)
        title = QLabel("What would you like to do?")
        title.setObjectName("workflowTitle")
        title.setFont(heading_font(title.font(), "window"))
        content_layout.addWidget(title)
        self._subtitle = QLabel()
        self._subtitle.setWordWrap(True)
        self._subtitle.setStyleSheet(secondary_text_stylesheet(self.palette()))
        content_layout.addWidget(self._subtitle)
        content_layout.addSpacing(SPACE_XL)

        self._actions = QWidget(content)
        self._actions_layout = QVBoxLayout(self._actions)
        self._actions_layout.setContentsMargins(0, 0, 0, 0)
        self._actions_layout.setSpacing(SPACE_LG)
        self._action_group_layouts: dict[str, QVBoxLayout] = {}
        content_layout.addWidget(self._actions)

        content_layout.addStretch(1)
        splitter.addWidget(content)

        side = QFrame(splitter)
        side.setFrameShape(QFrame.Shape.StyledPanel)
        side.setMinimumWidth(300)
        side.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(SPACE_SM)

        working_directory = QWidget(side)
        working_directory.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        working_directory_layout = QVBoxLayout(working_directory)
        working_directory_layout.setContentsMargins(0, 0, 0, 0)
        working_directory_layout.setSpacing(SPACE_XS)
        working_directory_title = QLabel("Working directory", working_directory)
        working_directory_title.setFont(
            heading_font(working_directory_title.font(), "section")
        )
        working_directory_layout.addWidget(working_directory_title)

        directory_row = QHBoxLayout()
        directory_row.setContentsMargins(0, 0, 0, 0)
        directory_row.setSpacing(SPACE_XS)
        self._working_directory_label = QLabel(working_directory)
        self._working_directory_label.setWordWrap(False)
        self._working_directory_label.setMinimumWidth(0)
        self._working_directory_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self._working_directory_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        directory_row.addWidget(self._working_directory_label, 1)

        change_directory = QToolButton(working_directory)
        change_directory.setIcon(
            QIcon.fromTheme(
                "document-open",
                self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton),
            )
        )
        change_directory.setToolTip("Change working directory")
        change_directory.setAccessibleName("Change working directory")
        change_directory.clicked.connect(self._choose_working_directory)
        directory_row.addWidget(change_directory)

        self._browse_working_directory_button = QToolButton(working_directory)
        self._browse_working_directory_button.setIcon(
            QIcon.fromTheme(
                "system-file-manager",
                self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon),
            )
        )
        self._browse_working_directory_button.setToolTip(
            "Open working directory in file manager"
        )
        self._browse_working_directory_button.setAccessibleName(
            "Open working directory in file manager"
        )
        self._browse_working_directory_button.clicked.connect(
            self._browse_working_directory
        )
        directory_row.addWidget(self._browse_working_directory_button)
        working_directory_layout.addLayout(directory_row)
        side_layout.addWidget(working_directory)

        self._result_actions = QWidget(side)
        result_actions_layout = QVBoxLayout(self._result_actions)
        result_actions_layout.setContentsMargins(0, 0, 0, 0)
        result_actions_layout.setSpacing(SPACE_XS)
        result_actions_title = QLabel("Results...", self._result_actions)
        result_actions_title.setFont(
            heading_font(result_actions_title.font(), "section")
        )
        result_actions_layout.addWidget(result_actions_title)
        self._result_actions_widget = ResultActionsWidget(
            lambda value, action: execute_value_action(value, action, self),
            show_values_without_actions=False,
            parent=self._result_actions,
        )
        result_actions_layout.addWidget(self._result_actions_widget, 1)
        side_layout.addWidget(self._result_actions, 1)

        expert_box = QGroupBox("", side)
        expert_box.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        expert_layout = QVBoxLayout(expert_box)
        side_text = QLabel("Access the full expert interface.", expert_box)
        side_text.setWordWrap(True)
        side_text.setStyleSheet(secondary_text_stylesheet(self.palette()))
        expert_layout.addWidget(side_text)

        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(SPACE_XS)
        expert_btn = QPushButton("Open Expert Mode", expert_box)
        expert_btn.setMinimumHeight(40)
        expert_btn.setStyleSheet(button_stylesheet(self.palette()))
        expert_btn.clicked.connect(self._open_expert_mode)
        bottom_row.addWidget(expert_btn, 1)

        settings_btn = QToolButton(expert_box)
        settings_btn.setAutoRaise(True)
        settings_btn.setFixedSize(40, 40)
        settings_btn.setIcon(
            QIcon.fromTheme(
                "preferences-system",
                self.style().standardIcon(
                    QStyle.StandardPixmap.SP_FileDialogDetailedView
                ),
            )
        )
        settings_btn.setToolTip("Settings")
        settings_btn.setAccessibleName("Settings")
        settings_btn.clicked.connect(self._open_settings)
        bottom_row.addWidget(settings_btn)
        expert_layout.addLayout(bottom_row)
        expert_box.setStyleSheet(
            group_panel_stylesheet(
                self.palette(), self.palette().color(QPalette.ColorRole.Highlight)
            )
        )
        side_layout.addWidget(
            expert_box, alignment=Qt.AlignmentFlag.AlignBottom
        )
        splitter.addWidget(side)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([560, 360])

    def _clear_actions(self) -> None:
        while self._actions_layout.count():
            item = self._actions_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        self._action_group_layouts.clear()

    def _action_group(self, title: str) -> QVBoxLayout:
        layout = self._action_group_layouts.get(title)
        if layout is not None:
            return layout
        if title not in self._ACTION_GROUPS:
            raise ValueError(f"Unknown workflow action group {title!r}.")

        group = QWidget(self._actions)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_SM)
        display_title = (
            "Create derived structure"
            if title == self._GROUP_CREATE
            and self.workspace.atoms is not None
            else title
        )
        label = QLabel(display_title, group)
        label.setObjectName("workflowActionGroupLabel")
        label.setForegroundRole(QPalette.ColorRole.WindowText)
        label.setFont(heading_font(label.font(), "section"))
        layout.addWidget(label)

        position = sum(
            group_title in self._action_group_layouts
            for group_title in self._ACTION_GROUPS[
                :self._ACTION_GROUPS.index(title)
            ]
        )
        self._actions_layout.insertWidget(position, group)
        self._action_group_layouts[title] = layout
        return layout

    def _refresh_working_directory(self) -> None:
        directory = self.workspace.directory
        self._working_directory_label.setText(directory or "(not defined)")
        self._working_directory_label.setToolTip(directory or "")
        self._browse_working_directory_button.setEnabled(bool(directory))

    def _choose_working_directory(
        self,
        _checked: bool = False,
        *,
        title: str = "Select Calculation Directory",
    ) -> bool:
        start_directory = self.workspace.directory or str(Path.home())
        directory = QFileDialog.getExistingDirectory(
            self,
            title,
            start_directory,
        )
        if not directory:
            return False
        self.controller.change_directory(str(directory))
        return True

    def _browse_working_directory(self) -> None:
        directory = self.workspace.directory
        if not directory:
            return
        path = Path(directory).expanduser().resolve()
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            QMessageBox.warning(
                self,
                "Cannot Open Directory",
                f"Could not open the working directory in the system file manager:\n{path}",
            )

    def _refresh_result_actions(self) -> None:
        results = self.workspace.result_history
        self._result_actions_widget.set_results(results)
        self._result_actions.setVisible(bool(results))

    def _action_style(self, category: str, widget: str) -> str:
        palette = self.palette()
        accents = {
            'structure': QColor('#3979b8'),
            'load': QColor('#527f9f'),
            'calculation': QColor('#398552'),
            'destructive': QColor('#b34444'),
            'neutral': palette.color(QPalette.ColorRole.Mid),
        }
        accent = accents[category]
        return action_card_stylesheet(
            palette,
            accent,
            widget,
            subtle=category == 'neutral',
        )

    def _add_action(
        self,
        title: str,
        description: str,
        callback: Callable[[], None],
        *,
        group: str = "Create structure",
        category: str = 'structure',
        icon: QStyle.StandardPixmap | QIcon | str = QStyle.StandardPixmap.SP_FileIcon,
    ) -> None:
        button = QPushButton(self._actions)
        button.setMinimumHeight(68)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        if isinstance(icon, QIcon):
            action_icon = icon
        elif isinstance(icon, str):
            action_icon = QIcon(
                str(
                    icon_path(icon)
                )
            )
        else:
            action_icon = self.style().standardIcon(icon)
        _set_action_button_content(
            button, title, description, action_icon, QSize(26, 26)
        )
        button.setStyleSheet(self._action_style(category, 'QPushButton'))
        button.clicked.connect(callback)
        self._action_group(group).addWidget(button)

    def _add_recent_load_action(self) -> None:
        recent_files = self.recent_history.snapshot
        recent_structures = recent_files['structure']
        recent_outputs = recent_files['output']
        if not recent_structures and not recent_outputs:
            return

        default_kind = self.recent_history.last_kind
        if default_kind == 'structure' and not recent_structures:
            default_kind = None
        if default_kind == 'output' and not recent_outputs:
            default_kind = None
        if default_kind not in {'structure', 'output'}:
            default_kind = 'output' if recent_outputs else 'structure'

        recent_by_kind = {
            'structure': recent_structures,
            'output': recent_outputs,
        }
        default_path = recent_by_kind[default_kind][0]

        button = QToolButton(self._actions)
        title = f"Continue: {Path(default_path).name}"
        button.setToolTip(default_path)
        button.setMinimumHeight(52)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        _set_action_button_content(
            button,
            title,
            "",
            self.style().standardIcon(
                QStyle.StandardPixmap.SP_ArrowForward
            ),
            QSize(24, 24),
            menu_button=True,
        )
        button.setStyleSheet(self._action_style('load', 'QToolButton'))
        button.clicked.connect(
            lambda _checked=False, kind=default_kind, path=default_path: self._load_recent(kind, path)
        )

        menu = QMenu(button)
        for title, kind, paths in (
            ('Structures', 'structure', recent_structures),
            ('Outputs', 'output', recent_outputs),
        ):
            submenu = menu.addMenu(title)
            if not paths:
                empty_action = QAction("(No recent files)", submenu)
                empty_action.setEnabled(False)
                submenu.addAction(empty_action)
                continue
            for path in paths:
                action = QAction(path, submenu)
                action.triggered.connect(
                    lambda _checked=False, item_kind=kind, item_path=path: self._load_recent(item_kind, item_path)
                )
                submenu.addAction(action)
        button.setMenu(menu)
        self._action_group(self._GROUP_LOAD).addWidget(button)

    def _refresh(self) -> None:
        self._structure_access.retry(
            self._refresh_locked,
            reason="refreshing the workflow overview",
        )

    def _refresh_locked(self) -> None:
        self._clear_actions()
        self._refresh_result_actions()
        atoms = self.workspace.atoms
        if atoms is None:
            self._subtitle.setText("Start by creating a new atomic structure or loading an existing one.")
            self._add_action("Create a 3D Structure", "Build a periodic bulk crystal", self._create_3d)
            self._add_action(
                "Create Structure from Prototype Database",
                "Start from a crystallographic structure prototype",
                self._create_from_database,
            )
            self._add_action(
                "Download Structure from Online Database",
                "Search an online crystallographic database",
                self._download_structure,
                group=self._GROUP_LOAD,
                category='load',
                icon=QStyle.StandardPixmap.SP_ArrowDown,
            )
            self._add_action("Create a 2D Surface", "Build a surface with vacuum on one side", self._create_surface)
            self._add_action("Create a 2D Structure", "Build an interface or transitional layer", self._create_transition)
            self._add_action(
                "Load a Structure",
                "Open a supported atomic structure file",
                self._load_structure,
                group=self._GROUP_LOAD,
                category='load',
                icon=QStyle.StandardPixmap.SP_DialogOpenButton,
            )
            self._add_action(
                "Load SPR-KKR Output",
                "Open a completed calculation and its structure",
                self._load_output,
                group=self._GROUP_LOAD,
                category='load',
                icon=QStyle.StandardPixmap.SP_FileDialogContentsView,
            )
            self._add_recent_load_action()
            return

        formula = atoms.get_chemical_formula()
        structure_kind = self.workspace.structure_kind()
        status = self.workspace.scf_status()
        converged = self.workspace.is_scf_converged()
        stage_names = {
            "ITR": "iterating SCF",
            "ITR-BULK": "converging bulk",
            "ITR-L-BULK": "converging left bulk",
            "ITR-R-BULK": "converging right bulk",
            "ITR-I-ZONE": "converging interaction zone",
        }
        status_text = (
            "CONVERGED"
            if converged
            else stage_names.get(
                status, status if status is not None else "not converged"
            )
        )
        self._subtitle.setText(f"Current structure: {formula}  •  SCF status: {status_text}")

        self._add_action(
            "Visualize Structure",
            "Open the current structure in the configured ASE viewer",
            self._visualize_structure,
            group=self._GROUP_VIEW,
            category="neutral",
            icon=QStyle.StandardPixmap.SP_FileDialogContentsView,
        )

        if not converged:
            empty_spheres_action = (
                None if status in stage_names else self.workspace.empty_spheres_action()
            )
            if empty_spheres_action is not None:
                self._add_action(
                    (
                        "Recalculate Empty Spheres"
                        if empty_spheres_action == "recalculate"
                        else "Add Empty Spheres"
                    ),
                    "Find empty spheres explicitly before the SCF calculation",
                    self._update_empty_spheres,
                    group=self._GROUP_CALCULATE,
                    category='structure',
                    icon='run-build-clean.svg',
                )

            if status in stage_names:
                scf_label = "Continue SCF"
                scf_description = f"Resume from {stage_names[status]} using the current potential"
            else:
                scf_label = "Converge SCF"
                scf_description = (
                    "Converge bulk region(s), then the interaction zone"
                    if structure_kind == "2d"
                    else "Prepare and run a self-consistent calculation"
                )
            self._add_action(
                scf_label,
                scf_description,
                lambda: self._prepare_task("scf"),
                group=self._GROUP_CALCULATE,
                category='calculation',
                icon='system-run.svg',
            )

        if converged:
            for task, label, description in (
                ("xas", "Calculate XAS", "X-ray absorption spectroscopy"),
                ("arpes", "Calculate ARPES", "Angle-resolved photoemission spectroscopy"),
                ("dos", "Calculate DOS", "Electronic density of states"),
                ("bsf", "Calculate BSF", "Bloch spectral function along an E–k path or on a k–k plane"),
                ("jxc", "Calculate JXC", "Exchange coupling and Dzyaloshinskii–Moriya interactions"),
            ):
                self._add_action(
                    label,
                    description,
                    lambda _checked=False, name=task: self._prepare_task(name),
                    group=self._GROUP_CALCULATE,
                    category='calculation',
                    icon='system-run.svg',
                )

        if converged or (status is not None and status != "START"):
            self._add_action(
                "Use for New Calculation",
                "Keep the current potential as starting density for a new SCF sequence",
                self._use_for_new_calculation,
                group=self._GROUP_DIFFERENT,
                category='destructive',
                icon='run-build-clean.svg',
            )

        if structure_kind == "3d":
            self._add_action(
                "Create a 2D Surface",
                "Derive a surface from the current 3D structure",
                lambda: self._build_2d(surface_mode=True),
            )
            self._add_action(
                "Create a 2D Structure",
                "Derive an interface or transitional layer",
                lambda: self._build_2d(surface_mode=False),
            )

        self._add_action(
            "Start Over",
            "Choose or load a different structure",
            self._start_over,
            group=self._GROUP_DIFFERENT,
            category='destructive',
            icon=QStyle.StandardPixmap.SP_BrowserReload,
        )

    def _on_structure_changed(self, _atoms: Any) -> None:
        self._refresh()

    def _create_3d(self) -> None:
        structure_flows.create_structure(self.controller, self)

    def _create_from_database(self) -> None:
        structure_flows.create_structure_from_database(self.controller, self)

    def _download_structure(self) -> None:
        structure_flows.download_structure(self.controller, self)

    def _create_surface(self) -> None:
        atoms = structure_flows.create_structure(self.controller, self)
        if atoms is not None:
            self._build_2d(surface_mode=True)

    def _create_transition(self) -> None:
        atoms = structure_flows.create_structure(self.controller, self)
        if atoms is not None:
            self._build_2d(surface_mode=False)

    def _load_structure(self) -> None:
        file_flows.choose_and_load_structure(
            self.controller, self.recent_history, self
        )

    def _load_output(self) -> None:
        file_flows.choose_and_load_output(
            self.controller, self.recent_history, self
        )

    def _load_recent(self, kind: RecentKind, file_path: str) -> None:
        file_flows.open_recent(
            self.controller,
            self.recent_history,
            kind,
            file_path,
            self,
        )
        if self.workspace.atoms is None:
            self._refresh()

    def _build_2d(self, _checked: bool = False, *, surface_mode: bool = False) -> None:
        structure_flows.build_2d_structure(
            self.controller, self, surface_mode=surface_mode
        )

    def _prepare_task(self, task: str) -> None:
        try:
            if not self.workspace.directory and not self._choose_working_directory(
                title="Choose the directory for this calculation"
            ):
                return
            snapshot = wait_for_structure(
                self,
                partial(
                    self.controller.read_structure,
                    _copy_optional_atoms,
                    reason="reading the structure for the task editor",
                ),
            )
            if isinstance(snapshot, Busy):
                return
            generation, atoms = snapshot
            if atoms is None:
                QMessageBox.information(
                    self,
                    "No Structure",
                    "Load or create a structure first.",
                )
                return
            parameters = select_guided_input_parameters(
                task,
                parent=self,
                atoms=atoms,
            )
            if parameters is None:
                return
            completed = document_change_applied(
                self,
                self.controller.replace_input_parameters(
                    parameters,
                    expected_generation=generation,
                ),
            )
            if not completed:
                return
            calculation_flow.run_calculation(
                self.controller, self.recent_history, self.active_runs, self
            )
        except (ImportError, ModuleNotFoundError) as exc:
            QMessageBox.critical(self, "Task Unavailable", f"The {task.upper()} task is not available:\n{exc}")
            return

    def _update_empty_spheres(self) -> None:
        structure_flows.update_empty_spheres(self.controller, self)

    def _use_for_new_calculation(self) -> None:
        generation = self.controller.generation
        answer = QMessageBox.question(
            self,
            "Use for New Calculation?",
            "Keep the current potential as starting density, reset the SCF stage, "
            "and use this structure for a new calculation?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            change = wait_for_structure(
                self,
                partial(
                    self.controller.use_for_new_calculation,
                    expected_generation=generation,
                ),
            )
            if isinstance(change, Busy) or not document_change_applied(
                self, change
            ):
                return
        except Exception as exc:
            QMessageBox.critical(self, "Cannot Start New Calculation", str(exc))

    def _start_over(self) -> None:
        answer = QMessageBox.question(
            self,
            "Start Over?",
            "Really start over? The current structure, calculation settings, and results will be cleared.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        wait_for_structure(self, self.controller.reset)

    def _visualize_structure(self) -> None:
        visualization_flow.visualize_structure(self.controller, self.settings, self)

    def _open_settings(self) -> None:
        edit_settings(self.settings, self)

    def _open_expert_mode(self) -> None:
        self._open_expert()
