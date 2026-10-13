from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QResizeEvent
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from guy4ase.gui.application.file_version import FileState
from guy4ase.gui.application.potential_version import PotentialFileVersion
from guy4ase.gui.application.result_store import ResultRecord, ResultStore
from guy4ase.gui.misc.resources import icon_path


logger = logging.getLogger(__name__)

_PLOT_ICON = icon_path("labplot-xy-interpolation-curve.svg")
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
_TASK_LABELS = {
    "empty_spheres": "Empty spheres",
}
_RESULT_ID_ROLE = int(Qt.ItemDataRole.UserRole)


def result_action_icon(style: QStyle, action: str) -> QIcon:
    if action == "plot":
        return QIcon(str(_PLOT_ICON))
    return style.standardIcon(
        _STANDARD_ICONS.get(action, QStyle.StandardPixmap.SP_FileIcon)
    )


def result_action_tooltip(value, action: str) -> str:
    return _action_tooltip(action, getattr(value, "info", ""))


def _action_tooltip(action: str, info: str) -> str:
    label = _ACTION_LABELS.get(action, action.replace("_", " ").capitalize())
    return f"{label} — {info}" if info else label


class ElidedValueLabel(QLabel):
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
        self.setText(
            self.fontMetrics().elidedText(
                self._full_text,
                Qt.TextElideMode.ElideRight,
                width,
            )
        )


class ResultActionsWidget(QWidget):
    """Browse a flat projection of exact result provenance."""

    useStateRequested = pyqtSignal(int, object)
    recomputeRequested = pyqtSignal(int)

    def __init__(
        self,
        action_handler: Callable[[Any, str], None],
        *,
        show_values_without_actions: bool,
        empty_text: str = "No result loaded.",
        show_history_button: bool = True,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._action_handler = action_handler
        self._show_values_without_actions = show_values_without_actions
        self._empty_text = empty_text
        self._row_count = 0
        self._store: ResultStore | None = None
        self._records: dict[int, ResultRecord] = {}
        self._current_structure_id: int | None = None
        self._current_state_id: int | None = None
        self._use_state_potential_version: PotentialFileVersion | None = None
        self._history_dialog = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if show_history_button:
            self._history_button = QPushButton("Browse calculation jobs…", self)
            self._history_button.clicked.connect(self._open_calculation_history)
            layout.addWidget(self._history_button)
        else:
            self._history_button = None

        self._selector = QTreeWidget(self)
        self._selector.setHeaderHidden(True)
        self._selector.setToolTip("Select a result")
        self._selector.currentItemChanged.connect(self._select_result)
        self._selector.hide()
        layout.addWidget(self._selector)

        self._record_actions = QWidget(self)
        record_actions_layout = QHBoxLayout(self._record_actions)
        record_actions_layout.setContentsMargins(0, 0, 0, 0)
        self._use_state_button = QPushButton("Use this potential", self._record_actions)
        self._use_state_button.clicked.connect(self._use_selected_state)
        record_actions_layout.addWidget(self._use_state_button)
        self._recompute_button = QPushButton("Recompute", self._record_actions)
        self._recompute_button.clicked.connect(self._recompute_selected)
        record_actions_layout.addWidget(self._recompute_button)
        record_actions_layout.addStretch(1)
        self._record_actions.hide()
        layout.addWidget(self._record_actions)

        self._result_file_warning = QLabel("", self)
        self._result_file_warning.setWordWrap(True)
        self._result_file_warning.hide()
        layout.addWidget(self._result_file_warning)

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

    def _open_calculation_history(self) -> None:
        if self._history_dialog is not None:
            self._history_dialog.show()
            self._history_dialog.raise_()
            self._history_dialog.activateWindow()
            return

        from guy4ase.gui.dialogs.calculation_history import CalculationHistoryDialog

        dialog = CalculationHistoryDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.destroyed.connect(lambda: setattr(self, "_history_dialog", None))
        self._history_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def set_workspace_state(
        self,
        structure_id: int | None,
        state_id: int | None,
    ) -> None:
        self._current_structure_id = structure_id
        self._current_state_id = state_id
        self._refresh_record_actions(self._record_for_item(self._selector.currentItem()))

    def set_results(self, results: Any) -> None:
        """Project exact provenance: imports by directory, native results by POT source."""
        if isinstance(results, ResultStore):
            self._store = results
        elif self._store is None:
            self._records = {}
            self._selector.clear()
            self._selector.hide()
            self.set_result(None)
            self._record_actions.hide()
            return
        store = self._store
        assert store is not None

        selected_id = self._selected_result_id()
        result_items: dict[int, QTreeWidgetItem] = {}
        records: dict[int, ResultRecord] = {}

        self._selector.blockSignals(True)
        try:
            self._selector.clear()
            directory_items: list[QTreeWidgetItem] = []

            # Imported results are grouped by their real source directory. Build
            # their items first so a later native result can attach below an
            # imported SCF whose potential it actually used.
            for directory in store.import_directories:
                imported = store.imported_results(directory)
                if not imported:
                    continue
                directory_item = QTreeWidgetItem([directory or "(unknown directory)"])
                directory_item.setFlags(
                    directory_item.flags() & ~Qt.ItemFlag.ItemIsSelectable
                )
                directory_items.append(directory_item)
                for record in imported:
                    records[record.id] = record
                    item = self._result_item(record)
                    directory_item.addChild(item)
                    result_items[record.id] = item

            formula_counts: dict[str, int] = {}
            for structure in store.structures:
                structure_records = store.structure_results(structure.id)
                if not structure_records:
                    continue

                structure_item = QTreeWidgetItem([structure.formula])
                structure_item.setFlags(
                    structure_item.flags() & ~Qt.ItemFlag.ItemIsSelectable
                )
                for record in structure_records:
                    records[record.id] = record
                    item = self._result_item(record)
                    result_items[record.id] = item

                    if record.task_name in {"scf", "empty_spheres"}:
                        structure_item.addChild(item)
                        continue

                    source = store.potential_source_result(record.input_state_id)
                    parent = result_items.get(source.id) if source is not None else None
                    (parent or structure_item).addChild(item)

                if structure_item.childCount():
                    number = formula_counts.get(structure.formula, 0) + 1
                    formula_counts[structure.formula] = number
                    if number > 1:
                        structure_item.setText(0, f"{structure.formula} ({number})")
                    self._selector.addTopLevelItem(structure_item)

            for directory_item in directory_items:
                self._selector.addTopLevelItem(directory_item)

            if store.unstructured_results:
                unknown_item = QTreeWidgetItem(["Unknown structure"])
                unknown_item.setFlags(
                    unknown_item.flags() & ~Qt.ItemFlag.ItemIsSelectable
                )
                self._selector.addTopLevelItem(unknown_item)
                for record in store.unstructured_results:
                    records[record.id] = record
                    item = self._result_item(record)
                    unknown_item.addChild(item)
                    result_items[record.id] = item

            self._records = records
            self._selector.expandAll()
            target = self._find_result_item(selected_id)
            if target is None:
                active = store.latest_result_for_state(self._current_state_id)
                if active is not None:
                    target = self._find_result_item(active.id)
            if target is None and records:
                target = self._find_result_item(max(records))
            if target is not None:
                self._selector.setCurrentItem(target)
        finally:
            self._selector.blockSignals(False)

        self._selector.setVisible(bool(records))
        selected_record = self._record_for_item(self._selector.currentItem())
        self.set_record(selected_record)
        self._refresh_record_actions(selected_record)

    def _result_item(self, record: ResultRecord) -> QTreeWidgetItem:
        item = QTreeWidgetItem([self._result_label(record)])
        item.setData(0, _RESULT_ID_ROLE, record.id)
        return item

    def _selected_result_id(self) -> int | None:
        item = self._selector.currentItem()
        if item is None:
            return None
        value = item.data(0, _RESULT_ID_ROLE)
        return int(value) if value is not None else None

    def _find_result_item(self, result_id: int | None) -> QTreeWidgetItem | None:
        if result_id is None:
            return None
        root = self._selector.invisibleRootItem()
        stack = [root.child(i) for i in range(root.childCount())]
        while stack:
            item = stack.pop()
            if item.data(0, _RESULT_ID_ROLE) == result_id:
                return item
            stack.extend(item.child(i) for i in range(item.childCount()))
        return None

    def _record_for_item(self, item: QTreeWidgetItem | None) -> ResultRecord | None:
        if item is None:
            return None
        value = item.data(0, _RESULT_ID_ROLE)
        if value is None:
            return None
        return self._records.get(int(value))

    def _select_result(
        self,
        current: QTreeWidgetItem | None,
        _previous: QTreeWidgetItem | None,
    ) -> None:
        record = self._record_for_item(current)
        self.set_record(record)
        self._refresh_record_actions(record)

    def _refresh_record_actions(self, record: ResultRecord | None) -> None:
        store = self._store
        if record is None or store is None:
            self._use_state_potential_version = None
            self._record_actions.hide()
            return

        state = store.state_for_result(record)
        active_state = (
            store.state(self._current_state_id)
            if self._current_state_id is not None
            else None
        )
        different_state = state is not None and state.id != self._current_state_id
        different_structure = (
            record.structure_id is not None
            and record.structure_id != self._current_structure_id
        )

        recorded_potential = state.potential_version if state is not None else None
        recorded_potential_was_usable = bool(
            recorded_potential is not None and recorded_potential.available
        )
        current_potential = (
            recorded_potential.current()
            if recorded_potential_was_usable
            else None
        )
        exact_potential_available = bool(
            current_potential is not None
            and current_potential.available
            and current_potential == recorded_potential
        )
        potential_changed = bool(
            current_potential is not None
            and current_potential.available
            and current_potential != recorded_potential
        )
        snapshot_available = bool(
            state is not None and state.structure_snapshot is not None
        )
        active_has_current_potential = (
            potential_changed
            and active_state is not None
            and state is not None
            and active_state.structure_id == state.structure_id
            and active_state.potential_version == current_potential
        )
        can_restore = snapshot_available or exact_potential_available or potential_changed
        can_use = (
            state is not None
            and can_restore
            and not active_has_current_potential
            and (different_state or potential_changed)
        )
        self._use_state_potential_version = (
            current_potential
            if can_use and potential_changed
            else recorded_potential
            if can_use and exact_potential_available
            else None
        )
        self._use_state_button.setVisible(can_use)
        if can_use:
            if potential_changed:
                text = "Continue with current version of this potential"
            elif exact_potential_available and not different_structure:
                text = "Use this potential"
            else:
                text = "Use this structure"
            self._use_state_button.setText(text)

        can_recompute = (
            bool(record.task_name)
            and record.task_name != "empty_spheres"
            and record.input_parameters is not None
            and self._current_structure_id is not None
        )
        self._recompute_button.setVisible(can_recompute)
        if different_structure:
            recompute_text = "Recompute on current structure"
        elif different_state:
            recompute_text = "Recompute on current potential"
        else:
            recompute_text = "Recompute"
        self._recompute_button.setText(recompute_text)
        self._record_actions.setVisible(can_use or can_recompute)

    def _use_selected_state(self) -> None:
        result_id = self._selected_result_id()
        if result_id is None:
            return
        expected = self._use_state_potential_version
        if expected is not None:
            current = expected.current()
            if not current.available or current != expected:
                self._refresh_record_actions(
                    self._record_for_item(self._selector.currentItem())
                )
                return
        self.useStateRequested.emit(result_id, expected)

    def _recompute_selected(self) -> None:
        result_id = self._selected_result_id()
        if result_id is not None:
            self.recomputeRequested.emit(result_id)

    @staticmethod
    def _result_label(record: ResultRecord) -> str:
        result = record.result
        task = _TASK_LABELS.get(record.task_name, record.task_name.upper())
        try:
            output = getattr(result, "output_file", None)
            output_name = Path(str(output)).name if output else ""
        except Exception:  # noqa: BLE001 - optional presentation metadata
            output_name = ""
        return " — ".join(part for part in (task, output_name) if part)

    def set_record(self, record: ResultRecord | None) -> None:
        self._render_result(record.result if record is not None else None, record)

    def set_result(self, result: Any | None) -> None:
        """Render a live result without historical result-file provenance."""
        self._render_result(result, None)

    def _render_result(
        self, result: Any | None, record: ResultRecord | None
    ) -> None:
        self._clear()
        self._result_file_warning.hide()
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

        has_replaced_result_file = False
        has_unavailable_result_file = False
        for key, value in items:
            try:
                name = str(key)
            except Exception:
                logger.exception("Failed to read an output value name")
                name = "<unknown output>"

            shown_value = value
            warning = None
            disable_actions = False
            result_file = record.result_files.get(name) if record is not None else None
            if result_file is not None:
                state = result_file.state()
                if state is FileState.OVERWRITTEN:
                    has_replaced_result_file = True
                    current_value = (
                        self._store.current_value_for_result_file(result_file)
                        if self._store is not None
                        else None
                    )
                    if current_value is not None:
                        shown_value = current_value
                    warning = (
                        "The historical result file was overwritten. Showing the current "
                        f"contents of {result_file.path.name}; these are not the original "
                        "data from the selected calculation."
                    )
                elif state is FileState.MISSING:
                    has_unavailable_result_file = True
                    disable_actions = True
                    warning = (
                        "The historical result file no longer exists, so its original "
                        "contents are unavailable."
                    )
                elif state is FileState.UNAVAILABLE:
                    has_unavailable_result_file = True
                    disable_actions = True
                    warning = (
                        "The historical result file cannot currently be inspected, so "
                        "its contents are unavailable."
                    )

            self._add_value(
                name,
                shown_value,
                warning=warning,
                disable_actions=disable_actions,
            )

        if has_replaced_result_file:
            self._result_file_warning.setText(
                "⚠ Historical result files were overwritten. Showing current contents "
                "where available; these are not the original data from the selected "
                "calculation."
            )
            self._result_file_warning.show()
        elif has_unavailable_result_file:
            self._result_file_warning.setText(
                "⚠ Some historical result files are no longer available."
            )
            self._result_file_warning.show()

        if self._row_count:
            self._empty_label.hide()
            self._scroll.show()
        else:
            self._show_empty("No actions available.")

    def _add_value(
        self,
        key: str,
        value: Any,
        *,
        warning: str | None = None,
        disable_actions: bool = False,
    ) -> None:
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
            actions = () if disable_actions else tuple(str(action) for action in value.actions())
        except Exception as exc:
            logger.exception("Failed to load actions for output value %r", key)
            action_warning = f"Actions could not be loaded: {exc}"
            self._add_row(
                value,
                (),
                name=name,
                info=info,
                summary=summary,
                warning="\n\n".join(
                    part for part in (warning, action_warning) if part
                ),
            )
            return

        if not actions and not self._show_values_without_actions and not show_in_summary:
            return
        if warning:
            name = f"{name} ⚠"
        self._add_row(
            value,
            actions,
            name=name,
            info=info,
            summary=summary,
            warning=warning,
        )

    def _add_error_row(self, name: str, error: Exception | None = None) -> None:
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
        name_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
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
            action_tooltip = _action_tooltip(action, info)
            if warning:
                action_tooltip = "\n\n".join((action_tooltip, warning))
            button.setToolTip(action_tooltip)
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
