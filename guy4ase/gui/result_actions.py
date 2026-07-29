from pathlib import Path
from collections.abc import Callable, Mapping
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QResizeEvent
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


_PLOT_ICON = (
    Path(__file__).resolve().parent.parent
    / "assets"
    / "icons"
    / "labplot-xy-interpolation-curve.svg"
)

_STANDARD_ICONS = {
    "save": QStyle.StandardPixmap.SP_DialogSaveButton,
    "open": QStyle.StandardPixmap.SP_FileDialogContentsView,
    "open_directory": QStyle.StandardPixmap.SP_DirOpenIcon,
    "edit": QStyle.StandardPixmap.SP_FileDialogDetailedView,
    "data": QStyle.StandardPixmap.SP_FileDialogDetailedView,
}

_ACTION_LABELS = {
    "data": "View data",
    "open_directory": "Open containing directory",
}


def result_action_icon(style: QStyle, action: str) -> QIcon:
    """Return the shared icon for an output-value action."""
    if action == "plot":
        return QIcon(str(_PLOT_ICON))
    return style.standardIcon(
        _STANDARD_ICONS.get(action, QStyle.StandardPixmap.SP_FileIcon)
    )


def result_action_tooltip(value, action: str) -> str:
    """Describe a result action using the value's short help text."""
    label = _ACTION_LABELS.get(action, action.replace("_", " ").capitalize())
    info = getattr(value, "info", "")
    return f"{label} — {info}" if info else label


class ElidedValueLabel(QLabel):
    """A single-line value label that elides text while retaining its full tooltip."""

    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._full_text = text
        self.setToolTip(text)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        self._update_text()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_text()

    def _update_text(self) -> None:
        width = max(0, self.contentsRect().width())
        self.setText(self.fontMetrics().elidedText(
            self._full_text,
            Qt.TextElideMode.ElideRight,
            width,
        ))


class ResultActionsWidget(QWidget):
    """Shared presentation of result values and their available actions."""

    def __init__(
        self,
        action_handler: Callable[[Any, str], None],
        *,
        show_values_without_actions: bool,
        empty_text: str = "No result loaded.",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._action_handler = action_handler
        self._show_values_without_actions = show_values_without_actions
        self._empty_text = empty_text
        self._row_count = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._empty_label = QLabel(empty_text, self)
        self._empty_label.setWordWrap(True)
        layout.addWidget(self._empty_label)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._container = QWidget(self._scroll)
        self._grid = QGridLayout(self._container)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(8)
        self._grid.setVerticalSpacing(6)
        self._grid.setColumnStretch(2, 1)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._container)
        layout.addWidget(self._scroll, 1)

    @property
    def has_rows(self) -> bool:
        return self._row_count > 0

    def set_result(self, result: Any | None) -> None:
        self._clear()
        if result is None:
            self._show_empty(self._empty_text)
            return

        try:
            values = result.output_values
        except Exception:
            self._show_empty("Result values are unavailable.")
            return

        items = values.items()
        if isinstance(items, Mapping):
            items = items.items()

        for _key, value in items:
            actions = tuple(value.actions())
            if not actions and not self._show_values_without_actions:
                continue
            self._add_row(value, actions)

        if self._row_count:
            self._empty_label.hide()
            self._scroll.show()
        else:
            self._show_empty("No actions available.")

    def _add_row(self, value: Any, actions: tuple[str, ...]) -> None:
        row = self._row_count

        name = QLabel(getattr(value, "display_name", value.name), self._container)
        name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        name.setWordWrap(True)
        info = getattr(value, "info", "")
        if info:
            name.setToolTip(info)
        self._grid.addWidget(name, row, 0)

        buttons = QWidget(self._container)
        button_layout = QHBoxLayout(buttons)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(4)
        for action in actions:
            button = QToolButton(buttons)
            button.setAutoRaise(True)
            button.setIcon(result_action_icon(self.style(), action))
            button.setToolTip(result_action_tooltip(value, action))
            button.clicked.connect(
                lambda _checked=False, v=value, a=action: self._action_handler(v, a)
            )
            button_layout.addWidget(button)
        button_layout.addStretch(1)
        self._grid.addWidget(buttons, row, 1)

        summary = ElidedValueLabel(str(value.value_label()), self._container)
        self._grid.addWidget(summary, row, 2)
        self._row_count += 1

    def _show_empty(self, text: str) -> None:
        self._empty_label.setText(text)
        self._empty_label.show()
        self._scroll.hide()

    def _clear(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._row_count = 0
