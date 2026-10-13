"""Project-oriented browser for persistent ASE2SPRKKR calculations."""
from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHeaderView, QSplitter, QTreeWidget, QTreeWidgetItem, QWidget

from guy4ase.gui.application.persistent_jobs import PersistentJob, PersistentJobSource
from guy4ase.gui.dialogs.calculation_history import CalculationHistoryDialog

_PROJECT_KEY_ROLE = int(Qt.ItemDataRole.UserRole)
_UNASSIGNED_PROJECT_KEY = "unassigned:"

ProjectIdResolver = Callable[[PersistentJob], str | None]


def _unassigned_project(_job: PersistentJob) -> str | None:
    return None


def _project_key(project_id: str | None) -> str:
    if project_id is None:
        return _UNASSIGNED_PROJECT_KEY
    return f"project:{project_id}"


def _project_label(project_id: str | None) -> str:
    return project_id if project_id is not None else "Unassigned"


class ProjectBrowserDialog(CalculationHistoryDialog):
    """Browse projects, their persistent jobs, and the selected job result.

    Project identity is deliberately supplied by a resolver instead of inferred
    from a working directory. Until the persistent execution contract carries a
    project id, production jobs therefore appear under ``Unassigned``.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        source: PersistentJobSource | None = None,
        project_id_for: ProjectIdResolver | None = None,
    ) -> None:
        self._project_id_for = project_id_for or _unassigned_project
        self._all_jobs: tuple[PersistentJob, ...] = ()
        self._selected_project_key: str | None = None
        self._project_browser_ready = False
        super().__init__(parent, source=source)

        self.setWindowTitle("Project Browser")
        splitter = self.tree.parentWidget()
        if not isinstance(splitter, QSplitter):
            raise RuntimeError("Calculation history tree is not hosted by a splitter")

        self.project_tree = QTreeWidget(splitter)
        self.project_tree.setColumnCount(2)
        self.project_tree.setHeaderLabels(("Project", "Jobs"))
        self.project_tree.setRootIsDecorated(True)
        self.project_tree.setAlternatingRowColors(True)
        project_header = self.project_tree.header()
        project_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        project_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.project_tree.currentItemChanged.connect(self._project_selection_changed)
        splitter.insertWidget(0, self.project_tree)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([260, 520, 560])

        self._project_browser_ready = True
        self._populate_projects()
        self._apply_project_filter()

    def _set_jobs(self, jobs: tuple[PersistentJob, ...]) -> None:
        self._all_jobs = tuple(sorted(jobs, key=lambda job: job.started_at, reverse=True))
        super()._set_jobs(jobs)
        if self._project_browser_ready:
            self._populate_projects()
            self._apply_project_filter()

    def _replace_job(self, job: PersistentJob) -> None:
        self._jobs_by_id[job.id] = job
        self._all_jobs = tuple(
            job if current.id == job.id else current for current in self._all_jobs
        )
        self._jobs = tuple(
            job if current.id == job.id else current for current in self._jobs
        )

    def _populate_tree(self) -> None:
        if not self._project_browser_ready:
            super()._populate_tree()
            return
        self._apply_project_filter()

    def _job_project_key(self, job: PersistentJob) -> str:
        return _project_key(self._project_id_for(job))

    def _populate_projects(self) -> None:
        selected_key = self._selected_project_key
        counts: dict[str, tuple[str | None, int]] = {}
        for job in self._all_jobs:
            project_id = self._project_id_for(job)
            key = _project_key(project_id)
            current = counts.get(key)
            counts[key] = (project_id, 1 if current is None else current[1] + 1)

        assigned = sorted(
            (item for key, item in counts.items() if key != _UNASSIGNED_PROJECT_KEY),
            key=lambda item: item[0] or "",
        )
        unassigned = (
            [counts[_UNASSIGNED_PROJECT_KEY]]
            if _UNASSIGNED_PROJECT_KEY in counts
            else []
        )

        self.project_tree.blockSignals(True)
        try:
            self.project_tree.clear()
            selected_item: QTreeWidgetItem | None = None
            for project_id, count in (*assigned, *unassigned):
                key = _project_key(project_id)
                item = QTreeWidgetItem([_project_label(project_id), str(count)])
                item.setData(0, _PROJECT_KEY_ROLE, key)
                if project_id is not None:
                    item.setToolTip(0, project_id)
                self.project_tree.addTopLevelItem(item)
                if key == selected_key:
                    selected_item = item

            if selected_item is None and self.project_tree.topLevelItemCount():
                selected_item = self.project_tree.topLevelItem(0)
            if selected_item is not None:
                self.project_tree.setCurrentItem(selected_item)
                self._selected_project_key = str(
                    selected_item.data(0, _PROJECT_KEY_ROLE)
                )
            else:
                self._selected_project_key = None
        finally:
            self.project_tree.blockSignals(False)

    def _project_selection_changed(
        self,
        current: QTreeWidgetItem | None,
        _previous: QTreeWidgetItem | None,
    ) -> None:
        self._selected_project_key = (
            None if current is None else str(current.data(0, _PROJECT_KEY_ROLE))
        )
        self._selected_job_id = None
        self._apply_project_filter()

    def _apply_project_filter(self) -> None:
        key = self._selected_project_key
        self._jobs = (
            ()
            if key is None
            else tuple(job for job in self._all_jobs if self._job_project_key(job) == key)
        )
        visible_ids = {job.id for job in self._jobs}
        if self._selected_job_id not in visible_ids:
            self._selected_job_id = None
        super()._populate_tree()
