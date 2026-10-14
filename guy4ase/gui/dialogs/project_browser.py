"""Three-pane browser for projects, persistent runs, and results."""
from __future__ import annotations

from collections import defaultdict

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
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

from guy4ase.gui.application.persistent_jobs import PersistentJobSource
from guy4ase.gui.application.projects import (
    Project,
    ProjectRepository,
    ProjectRepositoryError,
)
from guy4ase.gui.application.window_geometry import manage_window_geometry
from guy4ase.gui.dialogs.calculation_history import PersistentJobsWidget

_PROJECT_ID_ROLE = int(Qt.ItemDataRole.UserRole)
_UNASSIGNED = "__unassigned__"


class ProjectBrowserDialog(QDialog):
    """Browse a project forest and the persistent runs referenced by each node."""

    def __init__(
        self,
        repository: ProjectRepository,
        job_source: PersistentJobSource,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Project Browser")
        manage_window_geometry(
            self,
            "project-browser",
            default_size=(1400, 760),
        )
        self._repository = repository
        self._job_source = job_source
        self._projects: tuple[Project, ...] = ()
        self._projects_by_id: dict[str, Project] = {}
        self._selected_project_id: str | None = None

        root = QVBoxLayout(self)

        self.repository_notice = QLabel(self)
        self.repository_notice.setWordWrap(True)
        self.repository_notice.hide()
        root.addWidget(self.repository_notice)

        self.selection_notice = QLabel(self)
        self.selection_notice.setWordWrap(True)
        self.selection_notice.hide()
        root.addWidget(self.selection_notice)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        project_panel = QWidget(splitter)
        project_layout = QVBoxLayout(project_panel)
        project_layout.setContentsMargins(0, 0, 0, 0)

        self.refresh_projects_button = QPushButton("Refresh projects", project_panel)
        self.refresh_projects_button.clicked.connect(self._refresh_projects)
        project_layout.addWidget(self.refresh_projects_button)

        self.project_tree = QTreeWidget(project_panel)
        self.project_tree.setColumnCount(2)
        self.project_tree.setHeaderLabels(("Project", "Runs"))
        self.project_tree.setRootIsDecorated(True)
        self.project_tree.setAlternatingRowColors(True)
        header = self.project_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.project_tree.currentItemChanged.connect(
            self._project_selection_changed
        )
        project_layout.addWidget(self.project_tree)

        self.jobs = PersistentJobsWidget(job_source, splitter)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 1120])

        self._repository.changed.connect(self._project_changed)
        self._repository.reloaded.connect(self.reload_projects)
        self._job_source.changed.connect(self._job_changed)
        self._job_source.reloaded.connect(self._jobs_reloaded)

        self.reload_projects()

    def reload_projects(self) -> None:
        try:
            projects = self._repository.projects()
        except (ProjectRepositoryError, OSError, ValueError) as exc:
            self._projects = ()
            self._projects_by_id = {}
            self.project_tree.clear()
            self.repository_notice.setText(
                f"Project repository unavailable: {exc}"
            )
            self.repository_notice.show()
            self.jobs.set_visible_refs(())
            return

        self._projects = projects
        self._projects_by_id = {project.id: project for project in projects}
        self.repository_notice.hide()
        self._populate_project_tree()

    def _refresh_projects(self) -> None:
        try:
            self._repository.refresh()
        except (ProjectRepositoryError, OSError, ValueError) as exc:
            QMessageBox.warning(self, "Project Refresh Failed", str(exc))

    def _project_changed(self, _project_id: str) -> None:
        self.reload_projects()

    def _job_changed(self, _job_id: str) -> None:
        self._populate_project_tree()

    def _jobs_reloaded(self) -> None:
        self._populate_project_tree()

    def _populate_project_tree(self) -> None:
        previous = self._selected_project_id
        available_refs = {job.id for job in self._job_source.jobs()}
        children: dict[str | None, list[Project]] = defaultdict(list)
        for project in self._projects:
            children[project.parent_id].append(project)
        for siblings in children.values():
            siblings.sort(key=lambda project: project.name.casefold())

        claimed_refs = {
            ref
            for project in self._projects
            for ref in project.persistent_refs
        }
        unassigned_refs = available_refs - claimed_refs

        self.project_tree.blockSignals(True)
        try:
            self.project_tree.clear()
            selected_item: QTreeWidgetItem | None = None

            def add_project(
                project: Project,
                parent: QTreeWidgetItem | None,
            ) -> None:
                nonlocal selected_item
                total = len(project.persistent_refs)
                available = sum(
                    ref in available_refs for ref in project.persistent_refs
                )
                count = (
                    str(total) if available == total
                    else f"{available}/{total}"
                )
                item = QTreeWidgetItem([project.name, count])
                item.setData(0, _PROJECT_ID_ROLE, project.id)
                item.setToolTip(0, project.id)
                if available != total:
                    item.setToolTip(
                        1,
                        f"{total - available} persistent run reference(s) "
                        "are currently unavailable.",
                    )
                if parent is None:
                    self.project_tree.addTopLevelItem(item)
                else:
                    parent.addChild(item)
                if project.id == previous:
                    selected_item = item
                for child in children.get(project.id, ()):
                    add_project(child, item)

            for project in children.get(None, ()):
                add_project(project, None)

            if unassigned_refs:
                item = QTreeWidgetItem(
                    ["Unassigned", str(len(unassigned_refs))]
                )
                item.setData(0, _PROJECT_ID_ROLE, _UNASSIGNED)
                self.project_tree.addTopLevelItem(item)
                if previous == _UNASSIGNED:
                    selected_item = item

            self.project_tree.expandAll()
            if selected_item is None and self.project_tree.topLevelItemCount():
                selected_item = self.project_tree.topLevelItem(0)
            if selected_item is None:
                self._selected_project_id = None
            else:
                self.project_tree.setCurrentItem(selected_item)
                self._selected_project_id = str(
                    selected_item.data(0, _PROJECT_ID_ROLE)
                )
        finally:
            self.project_tree.blockSignals(False)

        self._apply_project_selection()

    def _project_selection_changed(
        self,
        current: QTreeWidgetItem | None,
        _previous: QTreeWidgetItem | None,
    ) -> None:
        value = None if current is None else current.data(0, _PROJECT_ID_ROLE)
        self._selected_project_id = None if value is None else str(value)
        self._apply_project_selection()

    def _apply_project_selection(self) -> None:
        project_id = self._selected_project_id
        available_refs = {job.id for job in self._job_source.jobs()}
        if project_id is None:
            self.jobs.set_visible_refs(())
            self.selection_notice.hide()
            return

        if project_id == _UNASSIGNED:
            claimed = {
                ref
                for project in self._projects
                for ref in project.persistent_refs
            }
            self.jobs.set_visible_refs(available_refs - claimed)
            self.selection_notice.hide()
            return

        project = self._projects_by_id.get(project_id)
        if project is None:
            self.jobs.set_visible_refs(())
            self.selection_notice.hide()
            return

        self.jobs.set_visible_refs(project.persistent_refs)
        missing = [
            ref
            for ref in project.persistent_refs
            if ref not in available_refs
        ]
        if missing:
            self.selection_notice.setText(
                f"{len(missing)} persistent run reference(s) in "
                f"{project.name!r} are not currently available in the "
                "ASE2SPRKKR run history."
            )
            self.selection_notice.show()
        else:
            self.selection_notice.hide()
