"""Project-oriented browser for persistent ASE2SPRKKR calculations."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHeaderView, QSplitter, QTreeWidget, QTreeWidgetItem, QWidget

from guy4ase.gui.application.persistent_jobs import PersistentJob, PersistentJobSource
from guy4ase.gui.application.projects import (
    ProjectRecord,
    ProjectSource,
    ProjectStore,
    ProjectStoreError,
    root_projects,
)
from guy4ase.gui.dialogs.calculation_history import CalculationHistoryDialog

_PROJECT_KEY_ROLE = int(Qt.ItemDataRole.UserRole)
_UNASSIGNED_PROJECT_KEY = "unassigned:"
_PROJECT_KEY_PREFIX = "project:"


def _project_key(project_id: str) -> str:
    return f"{_PROJECT_KEY_PREFIX}{project_id}"


class ProjectBrowserDialog(CalculationHistoryDialog):
    """Browse persistent projects, their owned jobs, and selected job results.

    Projects own job ids. Persistent ASE2SPRKKR run records remain independent
    and intentionally carry no reverse project reference.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        source: PersistentJobSource | None = None,
        project_source: ProjectSource | None = None,
    ) -> None:
        self._project_source = (
            project_source if project_source is not None else ProjectStore()
        )
        self._project_records: tuple[ProjectRecord, ...] = ()
        self._projects_by_id: dict[str, ProjectRecord] = {}
        self._all_jobs: tuple[PersistentJob, ...] = ()
        self._selected_project_key: str | None = None
        self._project_error: str | None = None
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
        self._reload_projects()
        self._populate_projects()
        self._apply_project_filter()

    def _set_jobs(self, jobs: tuple[PersistentJob, ...]) -> None:
        self._all_jobs = tuple(sorted(jobs, key=lambda job: job.started_at, reverse=True))
        super()._set_jobs(jobs)
        if self._project_browser_ready:
            self._reload_projects()
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

    def _reload_projects(self) -> None:
        try:
            records = self._project_source.projects()
        except (ProjectStoreError, OSError) as exc:
            self._project_records = ()
            self._projects_by_id = {}
            self._project_error = str(exc)
            self.backend_notice.setText(f"Project index unavailable: {exc}")
            self.backend_notice.show()
            return
        self._project_records = tuple(records)
        self._projects_by_id = {project.id: project for project in records}
        self._project_error = None

    @property
    def _claimed_job_ids(self) -> set[str]:
        return {
            job_id
            for project in self._project_records
            for job_id in project.job_ids
        }

    def _available_job_count(self, project: ProjectRecord) -> int:
        available = {job.id for job in self._all_jobs}
        return sum(job_id in available for job_id in project.job_ids)

    def _populate_projects(self) -> None:
        selected_key = self._selected_project_key
        self.project_tree.blockSignals(True)
        try:
            self.project_tree.clear()
            selected_item: QTreeWidgetItem | None = None

            def add_project(
                project: ProjectRecord,
                parent: QTreeWidgetItem | None,
            ) -> None:
                nonlocal selected_item
                item = QTreeWidgetItem(
                    [project.name, str(self._available_job_count(project))]
                )
                key = _project_key(project.id)
                item.setData(0, _PROJECT_KEY_ROLE, key)
                item.setToolTip(0, project.id)
                if parent is None:
                    self.project_tree.addTopLevelItem(item)
                else:
                    parent.addChild(item)
                if key == selected_key:
                    selected_item = item
                for child_id in project.child_project_ids:
                    add_project(self._projects_by_id[child_id], item)

            if self._project_error is None:
                for project in root_projects(self._project_records):
                    add_project(project, None)

                claimed_job_ids = self._claimed_job_ids
                unassigned_count = sum(
                    job.id not in claimed_job_ids for job in self._all_jobs
                )
                if unassigned_count:
                    item = QTreeWidgetItem(["Unassigned", str(unassigned_count)])
                    item.setData(0, _PROJECT_KEY_ROLE, _UNASSIGNED_PROJECT_KEY)
                    self.project_tree.addTopLevelItem(item)
                    if selected_key == _UNASSIGNED_PROJECT_KEY:
                        selected_item = item

            self.project_tree.expandAll()
            if selected_item is None and self.project_tree.topLevelItemCount():
                selected_item = self.project_tree.topLevelItem(0)
            if selected_item is None:
                self._selected_project_key = None
            else:
                self.project_tree.setCurrentItem(selected_item)
                self._selected_project_key = str(
                    selected_item.data(0, _PROJECT_KEY_ROLE)
                )
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

    def _project_job_ids(self) -> set[str]:
        key = self._selected_project_key
        if key is None or self._project_error is not None:
            return set()
        if key == _UNASSIGNED_PROJECT_KEY:
            return {job.id for job in self._all_jobs} - self._claimed_job_ids
        if not key.startswith(_PROJECT_KEY_PREFIX):
            raise RuntimeError(f"Invalid project selection key {key!r}")
        project_id = key[len(_PROJECT_KEY_PREFIX) :]
        project = self._projects_by_id[project_id]
        return set(project.job_ids)

    def _apply_project_filter(self) -> None:
        visible_ids = self._project_job_ids()
        self._jobs = tuple(job for job in self._all_jobs if job.id in visible_ids)
        if self._selected_job_id not in visible_ids:
            self._selected_job_id = None
        super()._populate_tree()
