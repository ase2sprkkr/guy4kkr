"""Persistent Guy4ASE project model and repository."""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import UUID, uuid4

from ase2sprkkr.common.file_locks import FileLock
from platformdirs import user_data_dir
from PyQt6.QtCore import QObject, pyqtSignal

from guy4ase.gui.application.atomic_io import atomic_write_json

_PROJECT_SCHEMA_VERSION = 1
_HIERARCHY_LOCK = ".hierarchy.lock"


class ProjectRepositoryError(RuntimeError):
    """Base error for persistent project metadata."""


class ProjectConflictError(ProjectRepositoryError):
    """A project was changed by another writer after it was loaded."""

    def __init__(
        self,
        project_id: str,
        *,
        expected_generation: int,
        current: "Project",
    ) -> None:
        self.project_id = project_id
        self.expected_generation = expected_generation
        self.current = current
        super().__init__(
            f"Project {project_id!r} changed from generation "
            f"{expected_generation} to {current.generation}."
        )


@dataclass(frozen=True)
class Project:
    """One immutable project snapshot.

    ``persistent_refs`` stores stable ASE2SPRKKR persistent-run identities.
    Project membership is deliberately one-way: persistent runs contain no
    reverse project reference.
    """

    id: str
    generation: int
    name: str
    parent_id: str | None = None
    persistent_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        project_id = _project_id(self.id)
        if not isinstance(self.generation, int) or self.generation < 1:
            raise ValueError("Project generation must be a positive integer")
        name = str(self.name).strip()
        if not name:
            raise ValueError("Project name must not be empty")
        parent_id = None if self.parent_id is None else _project_id(self.parent_id)
        if parent_id == project_id:
            raise ValueError("Project cannot be its own parent")
        refs = tuple(str(value).strip() for value in self.persistent_refs)
        if any(not value for value in refs):
            raise ValueError("Persistent run references must not be empty")
        if len(set(refs)) != len(refs):
            raise ValueError("Project contains duplicate persistent run references")
        object.__setattr__(self, "id", project_id)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "parent_id", parent_id)
        object.__setattr__(self, "persistent_refs", refs)

    def rename(self, name: str) -> "Project":
        """Return a snapshot with a different project name."""
        return replace(self, name=str(name).strip())

    def move_to(self, parent_id: str | None) -> "Project":
        """Return a snapshot with a different parent."""
        return replace(
            self,
            parent_id=None if parent_id is None else _project_id(parent_id),
        )

    def add_run(self, persistent_ref: str) -> "Project":
        """Return a snapshot containing ``persistent_ref`` exactly once."""
        ref = str(persistent_ref).strip()
        if not ref:
            raise ValueError("Persistent run reference must not be empty")
        if ref in self.persistent_refs:
            return self
        return replace(self, persistent_refs=(*self.persistent_refs, ref))

    def remove_run(self, persistent_ref: str) -> "Project":
        """Return a snapshot without ``persistent_ref``."""
        ref = str(persistent_ref).strip()
        if ref not in self.persistent_refs:
            return self
        return replace(
            self,
            persistent_refs=tuple(
                value for value in self.persistent_refs if value != ref
            ),
        )


def default_projects_directory() -> Path:
    """Return the per-user directory containing project JSON documents."""
    return Path(user_data_dir("guy4ase", appauthor="ase2sprkkr")) / "projects"


def _project_id(value: str) -> str:
    text = str(value).strip()
    try:
        return UUID(text).hex
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid project UUID {value!r}") from exc


def validate_hierarchy(projects: tuple[Project, ...]) -> None:
    """Validate parent references and reject project hierarchy cycles."""
    by_id: dict[str, Project] = {}
    for project in projects:
        if project.id in by_id:
            raise ProjectRepositoryError(f"Duplicate project id {project.id!r}")
        by_id[project.id] = project

    for project in projects:
        if project.parent_id is not None and project.parent_id not in by_id:
            raise ProjectRepositoryError(
                f"Project {project.id!r} references missing parent "
                f"{project.parent_id!r}"
            )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(project_id: str) -> None:
        if project_id in visited:
            return
        if project_id in visiting:
            raise ProjectRepositoryError("Project hierarchy contains a cycle")
        visiting.add(project_id)
        parent_id = by_id[project_id].parent_id
        if parent_id is not None:
            visit(parent_id)
        visiting.remove(project_id)
        visited.add(project_id)

    for project_id in by_id:
        visit(project_id)


class ProjectRepository(QObject):
    """Persist one generation-checked JSON document per project.

    A stable sidecar file lock serializes read/check/write in ordinary local
    filesystems. The generation remains the public optimistic-concurrency
    contract, so a stale editor is detected even when the project was changed
    by another Guy4ASE instance.
    """

    changed = pyqtSignal(str)
    reloaded = pyqtSignal()

    def __init__(
        self,
        directory: str | Path | None = None,
        *,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.directory = (
            Path(directory) if directory is not None
            else default_projects_directory()
        )

    def projects(self) -> tuple[Project, ...]:
        """Load and validate the complete project forest."""
        try:
            paths = sorted(self.directory.glob("*.json"))
        except OSError as exc:
            raise ProjectRepositoryError(
                f"Cannot list project directory {self.directory}: {exc}"
            ) from exc
        projects = tuple(self._read_path(path) for path in paths)
        validate_hierarchy(projects)
        return projects

    def project(self, project_id: str) -> Project:
        """Load one project by UUID."""
        canonical = _project_id(project_id)
        return self._read_path(self._json_path(canonical))

    def refresh(self) -> tuple[Project, ...]:
        """Reload external project metadata and publish one coarse refresh event."""
        projects = self.projects()
        self.reloaded.emit()
        return projects

    def create(
        self,
        name: str,
        *,
        parent_id: str | None = None,
    ) -> Project:
        """Create a root or child project at generation one."""
        parent = None if parent_id is None else _project_id(parent_id)
        project = Project(
            id=uuid4().hex,
            generation=1,
            name=name,
            parent_id=parent,
        )
        with FileLock(self.directory / _HIERARCHY_LOCK):
            projects = self.projects()
            if parent is not None and all(item.id != parent for item in projects):
                raise KeyError(parent)
            with FileLock(self._lock_path(project.id)):
                path = self._json_path(project.id)
                if path.exists():
                    raise ProjectRepositoryError(
                        f"Generated project id already exists: {project.id}"
                    )
                self._write(project)
        self.changed.emit(project.id)
        return project

    def save(self, project: Project, *, overwrite: bool = False) -> Project:
        """Persist an edited project snapshot.

        The snapshot's ``generation`` is the generation the editor loaded.
        Unless ``overwrite`` is explicit, a newer stored generation raises
        :class:`ProjectConflictError`. Overwrite replaces the newer snapshot;
        it is deliberately not an implicit field-wise merge.
        """
        if not isinstance(project, Project):
            raise TypeError("project must be a Project")
        with FileLock(self.directory / _HIERARCHY_LOCK):
            with FileLock(self._lock_path(project.id)):
                current = self._read_path(self._json_path(project.id))
                if current.generation != project.generation and not overwrite:
                    raise ProjectConflictError(
                        project.id,
                        expected_generation=project.generation,
                        current=current,
                    )
                updated = replace(
                    project,
                    generation=current.generation + 1,
                )
                projects = self.projects()
                snapshot = tuple(
                    updated if item.id == updated.id else item
                    for item in projects
                )
                if all(item.id != updated.id for item in projects):
                    raise KeyError(updated.id)
                validate_hierarchy(snapshot)
                self._write(updated)
        self.changed.emit(updated.id)
        return updated

    def delete(self, project: Project) -> None:
        """Delete a non-root leaf project after generation validation."""
        if not isinstance(project, Project):
            raise TypeError("project must be a Project")
        with FileLock(self.directory / _HIERARCHY_LOCK):
            with FileLock(self._lock_path(project.id)):
                current = self._read_path(self._json_path(project.id))
                if current.generation != project.generation:
                    raise ProjectConflictError(
                        project.id,
                        expected_generation=project.generation,
                        current=current,
                    )
                projects = self.projects()
                if current.parent_id is None:
                    raise ProjectRepositoryError("Root projects cannot be deleted")
                if any(item.parent_id == current.id for item in projects):
                    raise ProjectRepositoryError(
                        "Projects with child projects cannot be deleted"
                    )
                try:
                    self._json_path(current.id).unlink()
                except FileNotFoundError as exc:
                    raise KeyError(current.id) from exc
        self.changed.emit(current.id)

    def _read_path(self, path: Path) -> Project:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise KeyError(path.stem) from exc
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProjectRepositoryError(
                f"Cannot read project {path}: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise ProjectRepositoryError(
                f"Project file {path} must contain a JSON object"
            )
        schema_version = data.pop("schema_version", None)
        if schema_version != _PROJECT_SCHEMA_VERSION:
            raise ProjectRepositoryError(
                f"Unsupported project schema version {schema_version!r} in {path}"
            )
        try:
            project = Project(**data)
        except (TypeError, ValueError) as exc:
            raise ProjectRepositoryError(
                f"Invalid project file {path}: {exc}"
            ) from exc
        if path.stem != project.id:
            raise ProjectRepositoryError(
                f"Project file name {path.stem!r} does not match id {project.id!r}"
            )
        return project

    def _write(self, project: Project) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            self._json_path(project.id),
            {
                "schema_version": _PROJECT_SCHEMA_VERSION,
                "id": project.id,
                "generation": project.generation,
                "name": project.name,
                "parent_id": project.parent_id,
                "persistent_refs": list(project.persistent_refs),
            },
        )

    def _json_path(self, project_id: str) -> Path:
        return self.directory / f"{project_id}.json"

    def _lock_path(self, project_id: str) -> Path:
        return self.directory / f"{project_id}.lock"
