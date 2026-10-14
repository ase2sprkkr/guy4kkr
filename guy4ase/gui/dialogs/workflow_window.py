from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import QSize, Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QIcon, QPalette
from PyQt6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from guy4ase.gui.application.calculation_policy import guided_task_is_recommended
from guy4ase.gui.application.recent_files import RecentFiles, RecentKind
from guy4ase.gui.application.settings import ApplicationSettings
from guy4ase.gui.application.window_geometry import manage_window_geometry
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.dialogs.object_view import execute_value_action
from guy4ase.gui.dialogs.settings import edit_settings
from guy4ase.gui.flows import calculation as calculation_flow
from guy4ase.gui.flows import files as file_flows
from guy4ase.gui.flows import structures as structure_flows
from guy4ase.gui.flows import visualization as visualization_flow
from guy4ase.gui.input_parameters.tasks import (
    WorkflowStage,
    guided_task_definition,
    guided_task_definitions,
)
from guy4ase.gui.misc.resources import icon_path
from guy4ase.gui.misc.structure_wait import document_change_applied
from guy4ase.gui.style import (
    SPACE_LG,
    SPACE_SM,
    SPACE_XL,
    SPACE_XS,
    SPACE_XXL,
    button_stylesheet,
    group_panel_stylesheet,
    heading_font,
    secondary_text_stylesheet,
)
from guy4ase.gui.widgets.action_card import ActionCategory, configure_action_card
from guy4ase.gui.widgets.browser_panel import BrowserPanel
from guy4ase.gui.widgets.recent_launcher import (
    build_recent_launch_menu,
    recent_launch,
)
from guy4ase.gui.widgets.result_actions import ResultActionsWidget


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
        *,
        open_expert: Callable[[], None],
        settings: ApplicationSettings,
        persistent_job_changed: Callable[[str], None],
    ) -> None:
        super().__init__()
        self.setWindowTitle("Guy4ASE - Workflow")
        manage_window_geometry(
            self, "workflow", default_size=(1120, 700)
        )
        self.controller = controller
        self.recent_history = recent_files
        self.settings = settings
        self._open_expert = open_expert
        self._persistent_job_changed = persistent_job_changed
        self.controller.structureChanged.connect(self._on_structure_changed)
        self.controller.directoryChanged.connect(
            lambda _directory: self._refresh_working_directory()
        )
        self.controller.resultChanged.connect(lambda _result: self._refresh())
        self.recent_history.changed.connect(self._refresh)
        self._build_ui()
        self._refresh_working_directory()
        self._refresh()

    @property
    def result_actions_widget(self) -> ResultActionsWidget:
        """Return the result browser owned by this window."""
        return self._result_actions_widget

    @property
    def browser_panel(self) -> BrowserPanel:
        """Return the session-independent browser entry points."""
        return self._browser_panel

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
        change_directory.clicked.connect(
            lambda _checked=False: calculation_flow.choose_working_directory(
                self.controller,
                self,
            )
        )
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

        self._browser_panel = BrowserPanel(side)
        self._browser_panel.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        side_layout.addWidget(self._browser_panel)

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
            show_history_button=False,
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
            and self.controller.atoms is not None
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
        directory = self.controller.directory
        self._working_directory_label.setText(directory or "(not defined)")
        self._working_directory_label.setToolTip(directory or "")
        self._browse_working_directory_button.setEnabled(bool(directory))

    def _browse_working_directory(self) -> None:
        directory = self.controller.directory
        if not directory:
            return
        path = Path(directory).expanduser().resolve()
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            QMessageBox.warning(
                self,
                "Cannot Open Directory",
                f"Could not open the working directory in the system file manager:\n{path}",
            )

    def _add_action(
        self,
        title: str,
        description: str,
        callback: Callable[[], None],
        *,
        group: str = "Create structure",
        category: ActionCategory = "structure",
        icon: QStyle.StandardPixmap | QIcon | str = QStyle.StandardPixmap.SP_FileIcon,
    ) -> None:
        button = QPushButton(self._actions)
        if isinstance(icon, QIcon):
            action_icon = icon
        elif isinstance(icon, str):
            action_icon = QIcon(str(icon_path(icon)))
        else:
            action_icon = self.style().standardIcon(icon)
        configure_action_card(
            button,
            title,
            description,
            action_icon,
            category=category,
            subtle=category == "neutral",
        )
        button.clicked.connect(callback)
        self._action_group(group).addWidget(button)

    def _add_recent_load_action(self) -> None:
        launch = recent_launch(self.recent_history)
        if launch is None:
            return

        button = QToolButton(self._actions)
        button.setToolTip(launch.path)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        configure_action_card(
            button,
            launch.title,
            "",
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowForward),
            category="load",
            icon_size=QSize(24, 24),
            minimum_height=52,
            menu_button=True,
        )
        button.clicked.connect(
            lambda _checked=False, item=launch: self._continue_recent(
                item.kind, item.path
            )
        )
        button.setMenu(
            build_recent_launch_menu(
                button,
                self.recent_history,
                self._continue_recent,
            )
        )
        self._action_group(self._GROUP_LOAD).addWidget(button)

    def _refresh(self) -> None:
        self._clear_actions()
        atoms = self.controller.atoms
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
                "Add a completed calculation to the result history",
                self._load_output,
                group=self._GROUP_LOAD,
                category='load',
                icon=QStyle.StandardPixmap.SP_FileDialogContentsView,
            )
            self._add_recent_load_action()
            return

        formula = atoms.get_chemical_formula()
        structure_kind = self.controller.structure_kind()
        status = self.controller.scf_status()
        converged = self.controller.is_scf_converged()
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

        scf_definition = guided_task_definition("scf")
        if guided_task_is_recommended(
            scf_definition,
            has_structure=True,
            scf_converged=converged,
        ):
            empty_spheres_action = (
                None
                if self.controller.structure_change_requires_scf_restart()
                else self.controller.empty_spheres_action()
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
                scf_label = scf_definition.workflow.label
                scf_description = (
                    "Converge bulk region(s), then the interaction zone"
                    if structure_kind == "2d"
                    else scf_definition.workflow.description
                )
            self._add_action(
                scf_label,
                scf_description,
                lambda: self._prepare_task(scf_definition.task),
                group=self._GROUP_CALCULATE,
                category='calculation',
                icon='system-run.svg',
            )

        for definition in guided_task_definitions():
            if definition.workflow.stage is WorkflowStage.SCF:
                continue
            if not guided_task_is_recommended(
                definition,
                has_structure=True,
                scf_converged=converged,
            ):
                continue
            self._add_action(
                definition.workflow.label,
                definition.workflow.description,
                lambda _checked=False, name=definition.task: self._prepare_task(name),
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

        if self.controller.can_build_2d():
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

    def _continue_recent(self, kind: RecentKind, file_path: str) -> None:
        file_flows.continue_recent(
            self.controller,
            self.recent_history,
            kind,
            file_path,
            self,
        )
        if self.controller.atoms is None:
            self._refresh()

    def _build_2d(self, _checked: bool = False, *, surface_mode: bool = False) -> None:
        structure_flows.build_2d_structure(
            self.controller,
            self.recent_history,
            self,
            surface_mode=surface_mode,
        )

    def _prepare_task(self, task: str) -> None:
        calculation_flow.configure_and_run_task(
            self.controller,
            self.recent_history,
            self,
            task,
            dataset_default_mode=self.settings.dataset_default_mode,
            persistent_job_changed=self._persistent_job_changed,
        )

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
        change = self.controller.use_for_new_calculation(
            expected_generation=generation,
        )
        document_change_applied(self, change)

    def _start_over(self) -> None:
        answer = QMessageBox.question(
            self,
            "Start Over?",
            "Really start over? The current structure and calculation settings "
            "will be cleared. Existing calculation results will be kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.controller.reset()

    def _visualize_structure(self) -> None:
        visualization_flow.visualize_structure(self.controller, self.settings, self)

    def _open_settings(self) -> None:
        edit_settings(self.settings, self)

    def _open_expert_mode(self) -> None:
        self._open_expert()
