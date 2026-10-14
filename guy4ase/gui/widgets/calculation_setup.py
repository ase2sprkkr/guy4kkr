from __future__ import annotations

from typing import Any, Callable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from guy4ase.gui.widgets.browser_panel import BrowserPanel
from guy4ase.gui.widgets.result_actions import ResultActionsWidget


class CalculationSetupPanel(QWidget):
    """Present expert input/calculation/result controls without application policy."""

    def __init__(
        self,
        *,
        edit_input: Callable[[], None],
        load_input: Callable[[], None],
        save_input: Callable[[], None],
        choose_directory: Callable[[], None],
        run_calculation_action,
        load_output: Callable[[], None],
        value_action: Callable[[Any, Any], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        actions_group = QWidget(self)
        actions_layout = QVBoxLayout(actions_group)
        self._build_input_panel(
            actions_layout,
            edit_input=edit_input,
            load_input=load_input,
            save_input=save_input,
        )
        self._build_calculation_panel(
            actions_layout,
            choose_directory=choose_directory,
            run_calculation_action=run_calculation_action,
            load_output=load_output,
        )
        layout.addWidget(actions_group)

        self.browser_panel = BrowserPanel(self)
        layout.addWidget(self.browser_panel)

        result_group = QGroupBox("Calculation Result", self)
        result_layout = QVBoxLayout(result_group)
        self.result_actions_widget = ResultActionsWidget(
            value_action,
            show_values_without_actions=True,
            show_history_button=False,
            parent=result_group,
        )
        result_layout.addWidget(self.result_actions_widget, 1)
        layout.addWidget(result_group, 1)
        self.setMaximumWidth(350)

    def set_input_parameters(self, parameters: Any) -> None:
        self.create_input_btn.setText(
            "Edit SPRKKR Input File..."
            if parameters is not None
            else "Create SPRKKR Input File..."
        )
        if parameters is None:
            self.input_params_preview.setPlainText("")
            return
        self.input_params_preview.setPlainText(
            parameters.to_string(validate=False)
        )

    def set_save_input_enabled(self, enabled: bool) -> None:
        self.save_input_btn.setEnabled(enabled)

    def set_directory(self, directory: Optional[str]) -> None:
        value = directory or "—"
        self.directory_label.setText(value)
        self.directory_label.setToolTip(directory or "")

    def set_potential_path(self, path: Optional[str]) -> None:
        value = path or "—"
        self.potential_path_label.setText(value)
        self.potential_path_label.setToolTip(path or "")

    def _build_input_panel(
        self,
        layout: QVBoxLayout,
        *,
        edit_input: Callable[[], None],
        load_input: Callable[[], None],
        save_input: Callable[[], None],
    ) -> None:
        layout.addSpacing(5)
        label = QLabel("SPRKKR Tools:")
        label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(label)

        self.create_input_btn = QPushButton("Create SPRKKR Input File...")
        self.create_input_btn.clicked.connect(edit_input)
        layout.addWidget(self.create_input_btn)

        load_button = QPushButton("Load SPRKKR Input File...")
        load_button.clicked.connect(load_input)
        layout.addWidget(load_button)

        self.save_input_btn = QPushButton("Save SPRKKR Input File...")
        self.save_input_btn.setEnabled(False)
        self.save_input_btn.clicked.connect(save_input)
        layout.addWidget(self.save_input_btn)

        self.input_params_preview = QPlainTextEdit()
        self.input_params_preview.setReadOnly(True)
        self.input_params_preview.setPlaceholderText(
            "SPRKKR input parameters preview"
        )
        self.input_params_preview.setMinimumHeight(120)
        self.input_params_preview.mouseDoubleClickEvent = self._edit_input_on_double_click
        self._edit_input = edit_input
        layout.addWidget(self.input_params_preview)

    def _build_calculation_panel(
        self,
        layout: QVBoxLayout,
        *,
        choose_directory: Callable[[], None],
        run_calculation_action,
        load_output: Callable[[], None],
    ) -> None:
        directory_row = QWidget(self)
        directory_layout = QHBoxLayout(directory_row)
        directory_layout.setContentsMargins(0, 0, 0, 0)
        directory_layout.setSpacing(6)
        directory_layout.addWidget(QLabel("Directory:"))
        self.directory_label = QLabel("—")
        self.directory_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        directory_layout.addWidget(self.directory_label, 1)
        choose_button = QToolButton()
        choose_button.setToolTip("Choose directory")
        choose_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        )
        choose_button.clicked.connect(choose_directory)
        directory_layout.addWidget(choose_button, 0)
        layout.addWidget(directory_row)

        potential_row = QWidget(self)
        potential_layout = QHBoxLayout(potential_row)
        potential_layout.setContentsMargins(0, 0, 0, 0)
        potential_layout.setSpacing(6)
        potential_layout.addWidget(QLabel("Potential:"))
        self.potential_path_label = QLabel("—")
        self.potential_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        potential_layout.addWidget(self.potential_path_label, 1)
        layout.addWidget(potential_row)

        run_button = QToolButton()
        run_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        run_button.setDefaultAction(run_calculation_action)
        layout.addWidget(run_button)

        load_output_button = QPushButton("Load SPRKKR Output File...")
        load_output_button.clicked.connect(load_output)
        layout.addWidget(load_output_button)

    def _edit_input_on_double_click(self, event) -> None:
        self._edit_input()
        if event is not None:
            event.accept()
