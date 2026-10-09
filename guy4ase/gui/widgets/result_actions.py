from collections.abc import Callable
import logging
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

from guy4ase.gui.misc.resources import icon_path


logger = logging.getLogger(__name__)

_PLOT_ICON = (
    icon_path("labplot-xy-interpolation-curve.svg")
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
    return _action_tooltip(action, getattr(value, "info", ""))


def _action_tooltip(action: str, info: str) -> str:
    label = _ACTION_LABELS.get(action, action.replace("_", " ").capitalize())
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
            items = list(values.items())
        except Exception as exc:
            logger.exception("Failed to load result output values")
            self._add_error_row("Output values could not be loaded", exc)
            items = ()

        for key, value in items:
            try:
                name = str(key)
            except Exception:
                logger.exception("Failed to read an output value name")
                name = "<unknown output>"
            self._add_value(name, value)

        if self._row_count:
            self._empty_label.hide()
            self._scroll.show()
        else:
            self._show_empty("No actions available.")

    def _add_value(self, key: str, value: Any) -> None:
        try:
            fallback_name = getattr(value, "name", key)
            name = str(getattr(value, "display_name", fallback_name))
            raw_info = getattr(value, "info", "")
            info = str(raw_info) if raw_info else ""
            summary = str(value.value_label())
            show_in_summary = bool(getattr(value, "show_in_summary", False))
        except Exception as exc:
            logger.exception("Failed to display output value %r", key)
            self._add_error_row(f"{key}: unavailable", exc)
            return

        try:
            actions = tuple(str(action) for action in value.actions())
        except Exception as exc:
            logger.exception("Failed to load actions for output value %r", key)
            self._add_row(
                value,
                (),
                name=name,
                info=info,
                summary=summary,
                warning=f"Actions could not be loaded: {exc}",
            )
            return

        if (
            not actions
            and not self._show_values_without_actions
            and not show_in_summary
        ):
            return
        self._add_row(
            value,
            actions,
            name=name,
            info=info,
            summary=summary,
        )

    def _add_error_row(
        self,
        name: str,
        error: Exception | None = None,
    ) -> None:
        detail = f": {error}" if error else ""
        self._add_row(
            None,
            (),
            name=f"{name} ⚠",
            info="",
            summary="Unavailable",
            warning=f"Could not display this output{detail}",
        )

    def _add_row(
        self,
        value: Any | None,
        actions: tuple[str, ...],
        *,
        name: str,
        info: str,
        summary: str,
        warning: str | None = None,
    ) -> None:
        row = self._row_count

        name_label = QLabel(name, self._container)
        name_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        name_label.setWordWrap(True)
        tooltip = "\n\n".join(part for part in (info, warning) if part)
        if tooltip:
            name_label.setToolTip(tooltip)
        self._grid.addWidget(name_label, row, 0)

        buttons = QWidget(self._container)
        button_layout = QHBoxLayout(buttons)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(4)
        for action in actions:
            assert value is not None
            button = QToolButton(buttons)
            button.setAutoRaise(True)
            button.setIcon(result_action_icon(self.style(), action))
            button.setToolTip(_action_tooltip(action, info))
            button.clicked.connect(
                lambda _checked=False, v=value, a=action: self._action_handler(v, a)
            )
            button_layout.addWidget(button)
        button_layout.addStretch(1)
        self._grid.addWidget(buttons, row, 1)

        summary_text = f"{summary} ⚠" if warning else summary
        summary_label = ElidedValueLabel(summary_text, self._container)
        if warning:
            summary_label.setToolTip(
                "\n\n".join(part for part in (summary, warning) if part)
            )
        self._grid.addWidget(summary_label, row, 2)
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
