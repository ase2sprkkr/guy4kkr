"""Persistent calculation-job browser."""
from __future__ import annotations

from datetime import datetime
from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from guy4ase.gui.application.persistent_jobs import PersistentJob, PersistentJobSource
from guy4ase.gui.application.window_geometry import manage_window_geometry
from guy4ase.gui.dialogs.object_view import execute_value_action
from guy4ase.gui.dialogs.persistent_run_monitor import PersistentRunMonitorWindow
from guy4ase.gui.misc.modal_task import run_modal_task
from guy4ase.gui.widgets.result_actions import ResultActionsWidget

_JOB_ID_ROLE = int(Qt.ItemDataRole.UserRole)


def _local_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone()
    return parsed


def _timestamp_label(value: str) -> str:
    parsed = _local_datetime(value)
    return parsed.strftime("%Y-%m-%d %H:%M:%S") if parsed is not None else value


def _started_date(job: PersistentJob) -> str:
    parsed = _local_datetime(job.started_at)
    return parsed.strftime("%Y-%m-%d") if parsed is not None else "Unknown date"


def _status_label(state: str) -> str:
    return state.replace("_", " ").title() or "Unknown"


_GROUPS: tuple[tuple[str, Callable[[PersistentJob], str]], ...] = (
    ("Started date", _started_date),
    ("Status", lambda job: _status_label(job.state)),
    ("Task", lambda job: job.task or "Unknown task"),
    ("Execution target", lambda job: job.target),
)


class CalculationHistoryDialog(QDialog):
    """Browse persistent ASE2SPRKKR jobs independently of the current workspace."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        source: PersistentJobSource | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Calculation Jobs")
        manage_window_geometry(
            self,
            "calculation-history",
            default_size=(1100, 700),
        )
        self._source = source if source is not None else PersistentJobSource()
        self._jobs: tuple[PersistentJob, ...] = ()
        self._jobs_by_id: dict[str, PersistentJob] = {}
        self._selected_job_id: str | None = None
        self._monitors: dict[str, PersistentRunMonitorWindow] = {}

        root = QVBoxLayout(self)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Group by:"))
        self.group_by = QComboBox(self)
        for label, _group in _GROUPS:
            self.group_by.addItem(label)
        self.group_by.currentIndexChanged.connect(self._populate_tree)
        controls.addWidget(self.group_by)
        controls.addStretch(1)
        self.refresh_button = QPushButton("Refresh statuses", self)
        self.refresh_button.setEnabled(self._source.supports_refresh)
        self.refresh_button.clicked.connect(self._refresh_statuses)
        controls.addWidget(self.refresh_button)
        root.addLayout(controls)

        self.backend_notice = QLabel(self)
        self.backend_notice.setWordWrap(True)
        self.backend_notice.hide()
        root.addWidget(self.backend_notice)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        self.tree = QTreeWidget(splitter)
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(("Job", "Status", "Started", "Task", "Target"))
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.currentItemChanged.connect(self._selection_changed)
        self.tree.itemDoubleClicked.connect(self._item_double_clicked)
        splitter.addWidget(self.tree)

        details = QWidget(splitter)
        details_layout = QVBoxLayout(details)
        self.detail_title = QLabel("Select a calculation job", details)
        font = self.detail_title.font()
        font.setBold(True)
        self.detail_title.setFont(font)
        details_layout.addWidget(self.detail_title)

        self.detail_form = QFormLayout()
        self.status_value = QLabel("—", details)
        self.task_value = QLabel("—", details)
        self.target_value = QLabel("—", details)
        self.directory_value = QLabel("—", details)
        self.directory_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.dataset_value = QLabel("—", details)
        self.started_value = QLabel("—", details)
        self.updated_value = QLabel("—", details)
        self.return_code_value = QLabel("—", details)
        self.artifacts_value = QLabel("—", details)
        for label, widget in (
            ("Status", self.status_value),
            ("Task", self.task_value),
            ("Execution target", self.target_value),
            ("Directory", self.directory_value),
            ("Dataset", self.dataset_value),
            ("Started", self.started_value),
            ("Last update", self.updated_value),
            ("Return code", self.return_code_value),
            ("Artifacts", self.artifacts_value),
        ):
            self.detail_form.addRow(f"{label}:", widget)
        details_layout.addLayout(self.detail_form)

        self.message_value = QLabel(details)
        self.message_value.setWordWrap(True)
        self.message_value.hide()
        details_layout.addWidget(self.message_value)

        self.monitor_button = QPushButton("Monitor output", details)
        self.monitor_button.clicked.connect(self._monitor_selected_job)
        self.monitor_button.hide()
        details_layout.addWidget(self.monitor_button)

        self.load_result_button = QPushButton("Load result", details)
        self.load_result_button.clicked.connect(self._load_selected_result)
        self.load_result_button.hide()
        details_layout.addWidget(self.load_result_button)

        self.result_widget = ResultActionsWidget(
            lambda value, action: execute_value_action(value, action, self),
            show_values_without_actions=True,
            show_history_button=False,
            empty_text="No historical result loaded.",
            parent=details,
        )
        details_layout.addWidget(self.result_widget, 1)
        splitter.addWidget(details)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([540, 560])

        self._load_metadata()

    def _load_metadata(self) -> None:
        try:
            jobs = self._source.jobs()
        except (OSError, RuntimeError, ValueError) as exc:
            QMessageBox.warning(self, "Calculation Jobs", str(exc))
            jobs = ()
        self._set_jobs(jobs)

    def _set_jobs(self, jobs: tuple[PersistentJob, ...]) -> None:
        self._jobs = tuple(sorted(jobs, key=lambda job: job.started_at, reverse=True))
        self._jobs_by_id = {job.id: job for job in self._jobs}
        if not self._source.available:
            self.backend_notice.setText(
                self._source.unavailable_reason
                or "Persistent calculation jobs are not available in this ASE2SPRKKR version yet."
            )
            self.backend_notice.show()
        elif not self._jobs:
            self.backend_notice.setText("No persistent calculation jobs have been recorded yet.")
            self.backend_notice.show()
        else:
            self.backend_notice.hide()
        self._populate_tree()

    def _group_for(self, job: PersistentJob) -> str:
        return _GROUPS[self.group_by.currentIndex()][1](job)

    def _populate_tree(self) -> None:
        selected = self._selected_job_id
        self.tree.blockSignals(True)
        try:
            self.tree.clear()
            groups: dict[str, QTreeWidgetItem] = {}
            selected_item: QTreeWidgetItem | None = None
            for job in self._jobs:
                group_name = self._group_for(job)
                group = groups.get(group_name)
                if group is None:
                    group = QTreeWidgetItem([group_name])
                    group.setFlags(group.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                    self.tree.addTopLevelItem(group)
                    groups[group_name] = group

                title = job.dataset or job.id[:12]
                item = QTreeWidgetItem(
                    [
                        title,
                        _status_label(job.state),
                        _timestamp_label(job.started_at),
                        job.task,
                        job.target,
                    ]
                )
                item.setData(0, _JOB_ID_ROLE, job.id)
                item.setToolTip(0, job.id)
                group.addChild(item)
                if job.id == selected:
                    selected_item = item

            self.tree.expandAll()
            if selected_item is None and self._jobs:
                selected_item = self._first_job_item()
            if selected_item is not None:
                self.tree.setCurrentItem(selected_item)
        finally:
            self.tree.blockSignals(False)

        self._show_job(self._job_for_item(self.tree.currentItem()))

    def _first_job_item(self) -> QTreeWidgetItem | None:
        if self.tree.topLevelItemCount() == 0:
            return None
        group = self.tree.topLevelItem(0)
        return group.child(0) if group.childCount() else None

    def _job_for_item(self, item: QTreeWidgetItem | None) -> PersistentJob | None:
        if item is None:
            return None
        job_id = item.data(0, _JOB_ID_ROLE)
        if job_id is None:
            return None
        return self._jobs_by_id.get(str(job_id))

    def _selection_changed(
        self,
        current: QTreeWidgetItem | None,
        _previous: QTreeWidgetItem | None,
    ) -> None:
        self._show_job(self._job_for_item(current))

    def _show_job(self, job: PersistentJob | None) -> None:
        self.result_widget.set_result(None)
        if job is None:
            self._selected_job_id = None
            self.detail_title.setText("Select a calculation job")
            for widget in (
                self.status_value,
                self.task_value,
                self.target_value,
                self.directory_value,
                self.dataset_value,
                self.started_value,
                self.updated_value,
                self.return_code_value,
                self.artifacts_value,
            ):
                widget.setText("—")
            self.message_value.hide()
            self.monitor_button.hide()
            self.load_result_button.hide()
            return

        self._selected_job_id = job.id
        self.detail_title.setText(job.dataset or f"Calculation {job.id[:12]}")
        self.status_value.setText(_status_label(job.state))
        self.task_value.setText(job.task or "—")
        self.target_value.setText(job.target)
        self.directory_value.setText(job.directory or "—")
        self.directory_value.setToolTip(job.directory or "")
        self.dataset_value.setText(job.dataset or "—")
        self.started_value.setText(_timestamp_label(job.started_at))
        self.updated_value.setText(_timestamp_label(job.updated_at))
        self.return_code_value.setText(
            "—" if job.return_code is None else str(job.return_code)
        )
        self.artifacts_value.setText(
            _status_label(job.artifact_state) if job.artifact_state else "—"
        )
        self.message_value.setText(job.message or "")
        self.message_value.setVisible(bool(job.message))
        self.monitor_button.setVisible(
            job.attachable and bool(getattr(self._source, "supports_attach", False))
        )
        self.load_result_button.setVisible(job.is_final and self._source.supports_results)

    def _refresh_statuses(self) -> None:
        try:
            jobs = run_modal_task(
                self,
                self._source.refresh,
                title="Refreshing Calculations",
                label="Checking active calculation statuses…",
            )
        except Exception as exc:  # noqa: BLE001 - execution backend boundary
            QMessageBox.warning(self, "Status Refresh Failed", str(exc))
            return
        self._set_jobs(jobs)

    def _monitor_selected_job(self) -> None:
        job_id = self._selected_job_id
        if job_id is None:
            return
        job = self._jobs_by_id.get(job_id)
        if job is None or not job.attachable:
            return

        existing = self._monitors.get(job_id)
        if existing is not None:
            existing.show()
            existing.raise_()
            existing.activateWindow()
            return

        def finished(result) -> None:
            # The manager finalizes the persistent record before wait() returns.
            # Reload metadata first, then keep the completed result visible for
            # the selected job without forcing a second artifact parse.
            self._load_metadata()
            if self._selected_job_id == job_id:
                self.result_widget.set_result(result)

        window = PersistentRunMonitorWindow(
            job,
            self._source,
            parent=self,
            on_finished=finished,
        )
        self._monitors[job_id] = window

        def remove_monitor(*_args) -> None:
            self._monitors.pop(job_id, None)

        window.destroyed.connect(remove_monitor)
        window.show()

    def _load_selected_result(self) -> None:
        job_id = self._selected_job_id
        if job_id is None:
            return
        try:
            result = run_modal_task(
                self,
                lambda: self._source.load_result(job_id),
                title="Loading Calculation Result",
                label="Loading result artifacts…",
            )
        except Exception as exc:  # noqa: BLE001 - persisted/backend data boundary
            QMessageBox.warning(self, "Result Load Failed", str(exc))
            return
        if self._selected_job_id == job_id:
            self.result_widget.set_result(result)

    def _item_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        job = self._job_for_item(item)
        if job is None:
            return
        if job.is_final and self._source.supports_results:
            self._load_selected_result()
        elif job.attachable and bool(getattr(self._source, "supports_attach", False)):
            self._monitor_selected_job()
