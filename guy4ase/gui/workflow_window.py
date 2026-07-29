from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QAction, QColor, QIcon, QPalette
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .main_window import MainWindow


class WorkflowWindow(QMainWindow):
    """Task-oriented entry point that keeps the full UI available as expert mode."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Guy4ASE - Workflow")
        self.resize(980, 680)
        self._expert = MainWindow()
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
        root.setSpacing(28)

        content = QWidget(central)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
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
        self._actions_layout.setSpacing(12)
        content_layout.addWidget(self._actions)

        content_layout.addStretch(1)
        root.addWidget(content, 1)

        side = QFrame(central)
        side.setFrameShape(QFrame.Shape.StyledPanel)
        side.setFixedWidth(340)
        side_layout = QVBoxLayout(side)

        self._result_actions = QGroupBox("Available result actions", side)
        self._result_actions_layout = QGridLayout(self._result_actions)
        self._result_actions_layout.setColumnStretch(1, 1)
        side_layout.addWidget(self._result_actions)
        side_layout.addStretch(1)

        expert_box = QGroupBox("Expert mode", side)
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
        root.addWidget(side)

    def _clear_actions(self) -> None:
        while self._actions_layout.count():
            item = self._actions_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

    @staticmethod
    def _clear_grid(layout: QGridLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

    def _result_action_icon(self, action: str) -> QIcon:
        if action == "plot":
            for name in ("office-chart-line", "view-statistics", "x-office-spreadsheet"):
                icon = QIcon.fromTheme(name)
                if not icon.isNull():
                    return icon
        icons = {
            "plot": QStyle.StandardPixmap.SP_FileDialogContentsView,
            "save": QStyle.StandardPixmap.SP_DialogSaveButton,
            "open": QStyle.StandardPixmap.SP_DialogOpenButton,
            "open_directory": QStyle.StandardPixmap.SP_DirOpenIcon,
            "edit": QStyle.StandardPixmap.SP_FileDialogDetailedView,
            "data": QStyle.StandardPixmap.SP_FileDialogDetailedView,
        }
        return self.style().standardIcon(icons.get(action, QStyle.StandardPixmap.SP_FileIcon))

    def _refresh_result_actions(self) -> None:
        self._clear_grid(self._result_actions_layout)
        result = self._expert._last_sprkkr_result
        if result is None:
            self._result_actions.hide()
            return

        try:
            values = result.output_values
        except Exception:
            self._result_actions.hide()
            return

        row = 0
        iterable = values.values() if isinstance(values, dict) else values
        for value in iterable:
            actions = tuple(value.actions())
            if not actions:
                continue
            name = QLabel(value.name, self._result_actions)
            name.setWordWrap(True)
            self._result_actions_layout.addWidget(name, row, 0)

            summary = QLabel(str(value.value_label()), self._result_actions)
            summary.setWordWrap(True)
            summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._result_actions_layout.addWidget(summary, row, 1)

            buttons = QWidget(self._result_actions)
            button_layout = QHBoxLayout(buttons)
            button_layout.setContentsMargins(0, 0, 0, 0)
            button_layout.setSpacing(4)
            for action in actions:
                button = QToolButton(buttons)
                button.setIcon(self._result_action_icon(action))
                labels = {"data": "View data", "open_directory": "Open containing directory"}
                button.setToolTip(labels.get(action, action.capitalize()))
                button.clicked.connect(
                    lambda _checked=False, v=value, a=action: self._expert._execute_output_value_action(
                        v, a, parent=self
                    )
                )
                button_layout.addWidget(button)
            self._result_actions_layout.addWidget(buttons, row, 2)
            row += 1

        self._result_actions.setVisible(row > 0)

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
            'calculation': QColor('#398552'),
            'destructive': QColor('#b34444'),
            'neutral': palette.color(QPalette.ColorRole.Mid),
        }
        accent = accents[category]
        tint_amount = 0.22 if category != 'neutral' else 0.08
        background = self._blend_color(base, accent, tint_amount)
        hover = self._blend_color(base, accent, min(tint_amount + 0.12, 1.0))
        return (
            f"{widget} {{ text-align: left; padding: 10px 16px; font-size: 11pt; "
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
        category: str = 'structure',
        icon: QStyle.StandardPixmap | QIcon | str = QStyle.StandardPixmap.SP_FileIcon,
    ) -> None:
        button = QPushButton(f"{title}\n{description}")
        button.setMinimumHeight(68)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        if isinstance(icon, QIcon):
            button.setIcon(icon)
        elif isinstance(icon, str):
            button.setIcon(QIcon(str(Path(__file__).resolve().parent.parent / "assets" / "icons" / icon)))
        else:
            button.setIcon(self.style().standardIcon(icon))
        button.setIconSize(QSize(26, 26))
        button.setStyleSheet(self._action_style(category, 'QPushButton'))
        button.clicked.connect(callback)
        self._actions_layout.addWidget(button)

    def _add_recent_load_action(self) -> None:
        recent_structures = self._expert._recent_files['structure']
        recent_outputs = self._expert._recent_files['output']
        if not recent_structures and not recent_outputs:
            return

        default_kind = self._expert._last_recent_kind
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
        button.setText(f"Continue: {Path(default_path).name}")
        button.setToolTip(default_path)
        button.setMinimumHeight(52)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowForward))
        button.setIconSize(QSize(24, 24))
        button.setStyleSheet(self._action_style('structure', 'QToolButton'))
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
        self._actions_layout.addWidget(button)

    def _refresh(self) -> None:
        self._clear_actions()
        self._refresh_result_actions()
        atoms = self._expert.atoms
        if atoms is None:
            self._subtitle.setText("Start by creating a new atomic structure or loading an existing one.")
            self._add_action("Create a 3D Structure", "Build a periodic bulk crystal", self._create_3d)
            self._add_action("Create a 2D Surface", "Build a surface with vacuum on one side", self._create_surface)
            self._add_action("Create a 2D Structure", "Build an interface or transitional layer", self._create_transition)
            self._add_action(
                "Load a Structure",
                "Open a structure or SPR-KKR output file",
                self._load_structure,
                icon=QStyle.StandardPixmap.SP_DialogOpenButton,
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
                category='calculation',
                icon='system-run.svg',
            )

        if self._is_converged(status):
            for task, label, description in (
                ("xas", "Calculate XAS", "X-ray absorption spectroscopy"),
                ("arpes", "Calculate ARPES", "Angle-resolved photoemission spectroscopy"),
                ("dos", "Calculate DOS", "Electronic density of states"),
                ("bsf", "Calculate BSF", "Bloch spectral function along a selected K-path"),
                ("jxc", "Calculate JXC", "Exchange coupling and Dzyaloshinskii–Moriya interactions"),
            ):
                self._add_action(
                    label,
                    description,
                    lambda _checked=False, name=task: self._prepare_task(name),
                    category='calculation',
                    icon='system-run.svg',
                )

        if status is not None and status != "START":
            self._add_action(
                "Recalculate SCF",
                "Discard SCF progress and calculate again from the initial state",
                self._recalculate_scf,
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
            category='neutral',
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
        self._expert._on_create_structure()

    def _create_surface(self) -> None:
        self._structure_kind = "3d"
        self._expert._on_create_structure()
        if self._expert.atoms is not None:
            self._build_2d(surface_mode=True)

    def _create_transition(self) -> None:
        self._structure_kind = "3d"
        self._expert._on_create_structure()
        if self._expert.atoms is not None:
            self._build_2d(surface_mode=False)

    def _load_structure(self) -> None:
        self._structure_kind = None
        self._expert._on_load_structure()

    def _load_recent(self, kind: str, file_path: str) -> None:
        self._structure_kind = None
        self._expert._open_recent_file(kind, file_path)
        if self._expert.atoms is None:
            self._refresh()

    def _build_2d(self, _checked: bool = False, *, surface_mode: bool = False) -> None:
        original_atoms = self._expert.atoms
        self._expert._on_build_2d_structure(surface_mode=surface_mode)
        if self._expert.atoms is not None and self._expert.atoms is not original_atoms:
            self._structure_kind = "2d"
        else:
            self._structure_kind = "3d"
        self._refresh()

    def _prepare_task(self, task: str) -> None:
        try:
            if task == "scf":
                self._expert._on_create_guided_scf_input()
            else:
                self._expert._on_create_guided_task_input(task)
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
            self._expert.atoms.potential.SCF_INFO.SCFSTATUS = "START"
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
        self._expert.atoms = None
        self._expert._input_parameters = None
        self._expert._last_sprkkr_result = None
        self._expert.directory = None
        self._expert._potential_path = None
        self._structure_kind = None
        self._expert._update_directory_label()
        self._expert._update_potential_path_label()
        self._expert._update_structure_view()
        self._expert._enable_actions(False)
        self._expert._refresh_result_panel()
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
