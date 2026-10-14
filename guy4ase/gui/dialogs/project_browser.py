"""Three-pane browser for projects, persistent runs, and results."""
from __future__ import annotations

from collections import defaultdict

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
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
    ProjectConflictError,
    ProjectRepository,
    ProjectRepositoryError,
)
from guy4ase.gui.application.window_geometry import manage_window_geometry
from guy4ase.gui.dialogs.calculation_history import PersistentJobsWidget

_PROJECT_ID_ROLE = int(Qt.ItemDataRole.UserRole)
_UNASSIGNED = "__unassigned__"


class ProjectBrowserDialog(QDialog):
    """Browse and edit project-owned persistent-run references."""

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
        self._projects: tuple[Project, ...] = ()
        self._projects_by_id: dict[str, Project] = {}
        self._selected_project_id: str | None = None

        root = QVBoxLayout(self)
        self.project_notice = QLabel(self)
        self.project_notice.setWordWrap(True)
        self.project_notice.hide()
        root.addWidget(self.project_notice)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        project_panel = QWidget(splitter)
        project_layout = QVBoxLayout(project_panel)
        project_layout.setContentsMargins(0, 0, 0, 0)

        project_buttons = QHBoxLayout()
        self.new_project_button = QPushButton("New", project_panel)
        self.new_project_button.clicked.connect(self._create_project)
        project_buttons.addWidget(self.new_project_button)
        self.rename_project_button = QPushButton("Rename", project_panel)
        self.rename_project_button.clicked.connect(self._rename_project)
        project_buttons.addWidget(self.rename_project_button)
        self.move_project_button = QPushButton("Move", project_panel)
        self.move_project_button.clicked.connect(self._move_project)
        project_buttons.addWidget(self.move_project_button)
        self.delete_project_button = QPushButton("Delete", project_panel)
        self.delete_project_button.clicked.connect(self._delete_project)
        project_buttons.addWidget(self.delete_project_button)
        project_layout.addLayout(project_buttons)

        self.project_tree = QTreeWidget(project_panel)
        self.project_tree.setColumnCount(2)
        self.project_tree.setHeaderLabels(("Project", "Runs"))
        self.project_tree.setRootIsDecorated(True)
        self.project_tree.setAlternatingRowColors(True)
        header = self.project_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.project_tree.currentItemChanged.connect(self._project_selection_changed)
        project_layout.addWidget(self.project_tree, 1)

        membership_buttons = QHBoxLayout()
        self.add_run_button = QPushButton("Add selected run…", project_panel)
        self.add_run_button.clicked.connect(self._add_selected_run)
        membership_buttons.addWidget(self.add_run_button)
        self.remove_run_button = QPushButton("Remove run", project_panel)
        self.remove_run_button.clicked.connect(self._remove_selected_run)
        membership_buttons.addWidget(self.remove_run_button)
        project_layout.addLayout(membership_buttons)

        self.refresh_projects_button = QPushButton("Refresh projects", project_panel)
        self.refresh_projects_button.clicked.connect(self.reload_projects)
        project_layout.addWidget(self.refresh_projects_button)

        self.jobs = PersistentJobsWidget(job_source, splitter)
        self.jobs.jobsChanged.connect(self._refresh_project_projection)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 1100])

        self.reload_projects()

    def reload_projects(self) -> None:
        """Reload project JSONs, preserving selection when possible."""
        try:
            projects = tuple(self._repository.projects())
        except (ProjectRepositoryError, OSError, ValueError) as exc:
            self._projects = ()
            self._projects_by_id = {}
            self.project_tree.clear()
            self.project_notice.setText(f"Project repository unavailable: {exc}")
            self.project_notice.show()
            self.jobs.set_visible_refs(())
            self._refresh_action_availability()
            return

        self._projects = projects
        self._projects_by_id = {project.id: project for project in projects}
        self._refresh_project_projection()

    def _refresh_project_projection(self) -> None:
        self._populate_project_tree()
        self._apply_project_selection()

    def _populate_project_tree(self) -> None:
        previous = self._selected_project_id
        available_refs = {job.id for job in self.jobs.all_jobs}
        children: dict[str | None, list[Project]] = defaultdict(list)
        for project in self._projects:
            children[project.parent_id].append(project)
        for siblings in children.values():
            siblings.sort(key=lambda project: project.name.casefold())

        claimed_refs = {
            ref for project in self._projects for ref in project.persistent_refs
        }
        unassigned_refs = available_refs - claimed_refs

        self.project_tree.blockSignals(True)
        try:
            self.project_tree.clear()
            selected_item: QTreeWidgetItem | None = None

            def add_project(project: Project, parent: QTreeWidgetItem | None) -> None:
                nonlocal selected_item
                total = len(project.persistent_refs)
                available = sum(ref in available_refs for ref in project.persistent_refs)
                count = str(total) if available == total else f"{available}/{total}"
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
                item = QTreeWidgetItem(["Unassigned", str(len(unassigned_refs))])
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
        self._refresh_action_availability()

    def _project_selection_changed(
        self,
        current: QTreeWidgetItem | None,
        _previous: QTreeWidgetItem | None,
    ) -> None:
        value = None if current is None else current.data(0, _PROJECT_ID_ROLE)
        self._selected_project_id = None if value is None else str(value)
        self._apply_project_selection()
        self._refresh_action_availability()

    def _apply_project_selection(self) -> None:
        project_id = self._selected_project_id
        available_refs = {job.id for job in self.jobs.all_jobs}
        if project_id is None:
            self.jobs.set_visible_refs(())
            self.project_notice.hide()
            return

        if project_id == _UNASSIGNED:
            claimed = {
                ref for project in self._projects for ref in project.persistent_refs
            }
            self.jobs.set_visible_refs(available_refs - claimed)
            self.project_notice.hide()
            return

        project = self._projects_by_id.get(project_id)
        if project is None:
            self.jobs.set_visible_refs(())
            return
        self.jobs.set_visible_refs(project.persistent_refs)
        missing = [ref for ref in project.persistent_refs if ref not in available_refs]
        if missing:
            self.project_notice.setText(
                f"{len(missing)} persistent run reference(s) in {project.name!r} "
                "are not currently available in the ASE2SPRKKR run history."
            )
            self.project_notice.show()
        else:
            self.project_notice.hide()

    def _selected_project(self) -> Project | None:
        project_id = self._selected_project_id
        if project_id in (None, _UNASSIGNED):
            return None
        return self._projects_by_id.get(project_id)

    def _refresh_action_availability(self) -> None:
        project = self._selected_project()
        self.rename_project_button.setEnabled(project is not None)
        self.move_project_button.setEnabled(project is not None)
        self.delete_project_button.setEnabled(project is not None)
        selected_run = self.jobs.selected_persistent_ref
        self.add_run_button.setEnabled(selected_run is not None and bool(self._projects))
        self.remove_run_button.setEnabled(project is not None and selected_run is not None)

    def _create_project(self) -> None:
        name, accepted = QInputDialog.getText(self, "New Project", "Project name:")
        if not accepted:
            return
        parent = self._selected_project()
        try:
            created = self._repository.create(
                name,
                parent_id=None if parent is None else parent.id,
            )
        except (ProjectRepositoryError, KeyError, ValueError) as exc:
            QMessageBox.warning(self, "Create Project Failed", str(exc))
            return
        self._selected_project_id = created.id
        self.reload_projects()

    def _rename_project(self) -> None:
        project = self._selected_project()
        if project is None:
            return
        name, accepted = QInputDialog.getText(
            self,
            "Rename Project",
            "Project name:",
            text=project.name,
        )
        if not accepted:
            return
        try:
            edited = project.rename(name)
        except ValueError as exc:
            QMessageBox.warning(self, "Rename Project Failed", str(exc))
            return
        self._save_project(project, edited, "Rename Project")

    def _move_project(self) -> None:
        project = self._selected_project()
        if project is None:
            return
        candidates = [item for item in self._projects if item.id != project.id]
        labels = ["(root)"] + [
            f"{item.name} [{item.id[:8]}]" for item in candidates
        ]
        label, accepted = QInputDialog.getItem(
            self,
            "Move Project",
            "New parent:",
            labels,
            editable=False,
        )
        if not accepted:
            return
        parent_id = None
        if label != "(root)":
            parent_id = candidates[labels.index(label) - 1].id
        try:
            edited = project.move_to(parent_id)
        except ValueError as exc:
            QMessageBox.warning(self, "Move Project Failed", str(exc))
            return
        self._save_project(project, edited, "Move Project")

    def _delete_project(self) -> None:
        project = self._selected_project()
        if project is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete Project?",
            f"Delete project {project.name!r}? Persistent calculation runs are not deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._repository.delete(
                project.id,
                expected_generation=project.generation,
            )
        except (ProjectRepositoryError, KeyError) as exc:
            QMessageBox.warning(self, "Delete Project Failed", str(exc))
            return
        self._selected_project_id = project.parent_id
        self.reload_projects()

    def _add_selected_run(self) -> None:
        persistent_ref = self.jobs.selected_persistent_ref
        if persistent_ref is None or not self._projects:
            return
        candidates = sorted(self._projects, key=lambda item: item.name.casefold())
        labels = [f"{item.name} [{item.id[:8]}]" for item in candidates]
        label, accepted = QInputDialog.getItem(
            self,
            "Add Run to Project",
            "Project:",
            labels,
            editable=False,
        )
        if not accepted:
            return
        project = candidates[labels.index(label)]
        self._save_project(
            project,
            project.add_run(persistent_ref),
            "Add Run to Project",
        )

    def _remove_selected_run(self) -> None:
        project = self._selected_project()
        persistent_ref = self.jobs.selected_persistent_ref
        if project is None or persistent_ref is None:
            return
        self._save_project(
            project,
            project.remove_run(persistent_ref),
            "Remove Run from Project",
        )

    def _save_project(
        self,
        original: Project,
        edited: Project,
        title: str,
    ) -> Project | None:
        try:
            saved = self._repository.save(
                edited,
                expected_generation=original.generation,
            )
        except ProjectConflictError as conflict:
            answer = QMessageBox.question(
                self,
                "Project Changed",
                "This project was modified by another Guy4ASE instance. "
                "Overwrite the newer version with your edited snapshot?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.reload_projects()
                return None
            try:
                saved = self._repository.save(
                    edited,
                    expected_generation=conflict.current.generation,
                    overwrite=True,
                )
            except (ProjectRepositoryError, KeyError, ValueError) as exc:
                QMessageBox.warning(self, f"{title} Failed", str(exc))
                return None
        except (ProjectRepositoryError, KeyError, ValueError) as exc:
            QMessageBox.warning(self, f"{title} Failed", str(exc))
            return None

        self._selected_project_id = saved.id
        self.reload_projects()
        return saved
