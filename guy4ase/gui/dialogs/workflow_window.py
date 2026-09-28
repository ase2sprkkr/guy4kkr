from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QAction, QColor, QIcon, QPalette
from PyQt6.QtWidgets import (
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

from guy4ase.gui.dialogs.main_window import MainWindow
from guy4ase.gui.workspace import WorkspaceState
from guy4ase.gui.misc.resources import icon_path
from guy4ase.gui.widgets.result_actions import ResultActionsWidget


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
    layout.setContentsMargins(16, 8, 34 if menu_button else 16, 8)
    layout.setSpacing(16)

    icon_label = QLabel(button)
    icon_label.setFixedSize(icon_size)
    icon_label.setPixmap(icon.pixmap(icon_size))
    icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    icon_label.setAttribute(
        Qt.WidgetAttribute.WA_TransparentForMouseEvents
    )
    layout.addWidget(icon_label)

    text = title if not description else f"{title}\n{description}"
    text_label = QLabel(text, button)
    text_label.setForegroundRole(QPalette.ColorRole.ButtonText)
    text_label.setSizePolicy(
        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
    )
    text_label.setAttribute(
        Qt.WidgetAttribute.WA_TransparentForMouseEvents
    )
    layout.addWidget(text_label, 1)


class WorkflowWindow(QMainWindow):
    """Task-oriented entry point that keeps the full UI available as expert mode."""

    _GROUP_CALCULATE = "Calculate"
    _GROUP_CREATE = "Create structure"
    _GROUP_LOAD = "Load structure"
    _GROUP_DIFFERENT = "And now something completely different..."
    _ACTION_GROUPS = (
        _GROUP_CALCULATE,
        _GROUP_CREATE,
        _GROUP_LOAD,
        _GROUP_DIFFERENT,
    )

    def __init__(self, workspace: WorkspaceState | None = None):
        super().__init__()
        self.setWindowTitle("Guy4ASE - Workflow")
        self.resize(980, 680)
        self.workspace = workspace or WorkspaceState()
        self._expert = MainWindow(self.workspace)
        self._structure_kind: Optional[str] = None

        self._expert.structureChanged.connect(self._on_structure_changed)
        self._expert.calculationResultChanged.connect(lambda _result: self._refresh())
        self._build_ui()
        self._refresh()

    @property
    def expert_window(self) -> MainWindow:
        return self._expert

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(32, 28, 24, 28)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal, central)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)
        root.addWidget(splitter)

        content = QWidget(splitter)
        content.setMinimumWidth(480)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 24, 0)
        title = QLabel("What would you like to do?")
        title.setStyleSheet("font-size: 24pt; font-weight: 600;")
        content_layout.addWidget(title)
        self._subtitle = QLabel()
        self._subtitle.setWordWrap(True)
        self._subtitle.setStyleSheet("font-size: 11pt; color: #666;")
        content_layout.addWidget(self._subtitle)
        content_layout.addSpacing(22)

        self._actions = QWidget(content)
        self._actions_layout = QVBoxLayout(self._actions)
        self._actions_layout.setContentsMargins(0, 0, 0, 0)
        self._actions_layout.setSpacing(16)
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
        side_layout.setSpacing(8)

        self._result_actions = QWidget(side)
        result_actions_layout = QVBoxLayout(self._result_actions)
        result_actions_layout.setContentsMargins(0, 0, 0, 0)
        result_actions_layout.setSpacing(4)
        result_actions_title = QLabel("Results...", self._result_actions)
        result_actions_title.setStyleSheet("font-weight: 600;")
        result_actions_layout.addWidget(result_actions_title)
        self._result_actions_widget = ResultActionsWidget(
            lambda value, action: self._expert.execute_output_value_action(
                value, action, parent=self
            ),
            show_values_without_actions=False,
            parent=self._result_actions,
        )
        result_actions_layout.addWidget(self._result_actions_widget, 1)
        side_layout.addWidget(self._result_actions, 1)

        expert_box = QGroupBox("", side)
        expert_layout = QVBoxLayout(expert_box)
        side_text = QLabel("Access every setting directly.", expert_box)
        side_text.setWordWrap(True)
        side_text.setStyleSheet("color: palette(mid);")
        expert_layout.addWidget(side_text)
        expert_btn = QPushButton("Open Expert Mode", expert_box)
        expert_btn.setMinimumHeight(40)
        expert_btn.clicked.connect(self._open_expert_mode)
        expert_layout.addWidget(expert_btn)
        side_layout.addWidget(expert_box)
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
        layout.setSpacing(8)
        display_title = (
            "Create derived structure"
            if title == self._GROUP_CREATE
            and self.workspace.atoms is not None
            else title
        )
        label = QLabel(display_title, group)
        label.setObjectName("workflowActionGroupLabel")
        label.setForegroundRole(QPalette.ColorRole.WindowText)
        label.setStyleSheet(
            "font-size: 9pt; font-weight: 600;"
        )
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

    def _refresh_result_actions(self) -> None:
        result = self.workspace.result
        self._result_actions_widget.set_result(result)
        self._result_actions.setVisible(self._result_actions_widget.has_rows)

    @staticmethod
    def _blend_color(base: QColor, tint: QColor, amount: float) -> QColor:
        keep = 1.0 - amount
        return QColor(
            round(base.red() * keep + tint.red() * amount),
            round(base.green() * keep + tint.green() * amount),
            round(base.blue() * keep + tint.blue() * amount),
        )

    def _action_style(self, category: str, widget: str) -> str:
        palette = self.palette()
        base = palette.color(QPalette.ColorRole.Button)
        text = palette.color(QPalette.ColorRole.ButtonText)
        accents = {
            'structure': QColor('#3979b8'),
            'load': QColor('#527f9f'),
            'calculation': QColor('#398552'),
            'destructive': QColor('#b34444'),
            'neutral': palette.color(QPalette.ColorRole.Mid),
        }
        accent = accents[category]
        tint_amount = 0.22 if category != 'neutral' else 0.08
        background = self._blend_color(base, accent, tint_amount)
        hover = self._blend_color(base, accent, min(tint_amount + 0.12, 1.0))
        return (
            f"{widget} {{ text-align: left; padding: 0; font-size: 11pt; "
            f"color: {text.name()}; background-color: {background.name()}; "
            f"border: 1px solid {accent.name()}; border-left: 6px solid {accent.name()}; "
            f"border-radius: 4px; }} "
            f"{widget}:hover {{ color: {text.name()}; background-color: {hover.name()}; }}"
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
        recent_files = self._expert.recent_files
        recent_structures = recent_files['structure']
        recent_outputs = recent_files['output']
        if not recent_structures and not recent_outputs:
            return

        default_kind = self._expert.last_recent_kind
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
        status = self._scf_status(atoms)
        stage_names = {
            "ITR-L-BULK": "converging left bulk",
            "ITR-R-BULK": "converging right bulk",
            "ITR-I-ZONE": "converging interaction zone",
        }
        status_text = stage_names.get(status, status if status is not None else "not converged")
        self._subtitle.setText(f"Current structure: {formula}  •  SCF status: {status_text}")

        if not self._is_converged(status):
            intermediate_2d = status in {"ITR-L-BULK", "ITR-R-BULK", "ITR-I-ZONE"}
            if intermediate_2d:
                scf_label = "Continue SCF"
                scf_description = f"Resume from {stage_names[status]} using the current potential"
            else:
                scf_label = "Converge SCF"
                scf_description = (
                    "Converge bulk region(s), then the interaction zone"
                    if self._structure_kind == "2d"
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

        if self._is_converged(status):
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

        if status is not None and status != "START":
            self._add_action(
                "Recalculate SCF",
                "Discard SCF progress and calculate again from the initial state",
                self._recalculate_scf,
                group=self._GROUP_DIFFERENT,
                category='destructive',
                icon='run-build-clean.svg',
            )

        if self._structure_kind == "3d":
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

    def _on_structure_changed(self, atoms: Any) -> None:
        if self._structure_kind is None:
            self._structure_kind = self._detect_structure_kind(atoms)
        self._refresh()

    @staticmethod
    def _detect_structure_kind(atoms: Any) -> str:
        try:
            return "3d" if all(bool(periodic) for periodic in atoms.get_pbc()) else "2d"
        except Exception:
            return "3d"

    def _create_3d(self) -> None:
        self._structure_kind = "3d"
        self._expert.create_structure()

    def _create_from_database(self) -> None:
        self._structure_kind = "3d"
        self._expert.create_structure_from_database()

    def _download_structure(self) -> None:
        self._structure_kind = None
        self._expert.download_structure()

    def _create_surface(self) -> None:
        self._structure_kind = "3d"
        self._expert.create_structure()
        if self.workspace.atoms is not None:
            self._build_2d(surface_mode=True)

    def _create_transition(self) -> None:
        self._structure_kind = "3d"
        self._expert.create_structure()
        if self.workspace.atoms is not None:
            self._build_2d(surface_mode=False)

    def _load_structure(self) -> None:
        self._structure_kind = None
        self._expert.load_structure()

    def _load_output(self) -> None:
        self._structure_kind = None
        self._expert.load_sprkkr_output()
        self._refresh()

    def _load_recent(self, kind: str, file_path: str) -> None:
        self._structure_kind = None
        self._expert.open_recent_file(kind, file_path)
        if self.workspace.atoms is None:
            self._refresh()

    def _build_2d(self, _checked: bool = False, *, surface_mode: bool = False) -> None:
        original_atoms = self.workspace.atoms
        self._expert.build_2d_structure(surface_mode=surface_mode)
        if self.workspace.atoms is not None and self.workspace.atoms is not original_atoms:
            self._structure_kind = "2d"
        else:
            self._structure_kind = "3d"
        self._refresh()

    def _prepare_task(self, task: str) -> None:
        try:
            self._expert.prepare_guided_task(task)
        except (ImportError, ModuleNotFoundError) as exc:
            QMessageBox.critical(self, "Task Unavailable", f"The {task.upper()} task is not available:\n{exc}")
            return

    def _recalculate_scf(self) -> None:
        answer = QMessageBox.question(
            self,
            "Recalculate SCF?",
            "Really discard the current SCF convergence state and start again?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._expert.restart_scf()
        except Exception as exc:
            QMessageBox.critical(self, "Cannot Reset SCF", str(exc))
            return
        self._refresh()
        self._prepare_task("scf")

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
        self._structure_kind = None
        self._expert.reset_workspace()
        self._refresh()

    def _open_expert_mode(self) -> None:
        self._expert.show()
        self._expert.raise_()
        self._expert.activateWindow()

    @staticmethod
    def _scf_status(atoms: Any) -> Optional[str]:
        try:
            if hasattr(atoms, "has_potential") and atoms.has_potential():
                return str(atoms.potential.SCF_INFO.SCFSTATUS()).strip().upper()
        except Exception:
            pass
        return None

    @staticmethod
    def _is_converged(status: Optional[str]) -> bool:
        return status in {"CONVERGED", "SCF-CONVERGED", "DONE", "FINISHED"}

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._expert.close()
        super().closeEvent(event)
