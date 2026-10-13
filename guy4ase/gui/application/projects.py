"""Persistent project ownership of calculation jobs."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import RLock
from typing import Protocol
from uuid import uuid4

from guy4ase.gui.application.atomic_io import atomic_write_json
from guy4ase.gui.application.config import config_home

_PROJECT_SCHEMA_VERSION = 1


class ProjectStoreError(RuntimeError):
    """The persistent project index is malformed or internally inconsistent."""


@dataclass(frozen=True)
class ProjectRecord:
    """Persistent project identity and the durable objects owned by it.

    Calculation runs intentionally do not carry a project id.  Membership is
    owned here by ``job_ids``.  Project hierarchy follows the same direction:
    a project explicitly owns its direct child-project ids.
    """

    id: str
    name: str
    job_ids: tuple[str, ...] = ()
    child_project_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        project_id = str(self.id).strip()
        name = str(self.name).strip()
        if not project_id:
            raise ValueError("Project id must not be empty")
        if not name:
            raise ValueError("Project name must not be empty")
        job_ids = tuple(str(value).strip() for value in self.job_ids)
        child_ids = tuple(str(value).strip() for value in self.child_project_ids)
        if any(not value for value in job_ids):
            raise ValueError("Project job ids must not be empty")
        if any(not value for value in child_ids):
            raise ValueError("Child project ids must not be empty")
        if len(set(job_ids)) != len(job_ids):
            raise ValueError(f"Project {project_id!r} contains duplicate job ids")
        if len(set(child_ids)) != len(child_ids):
            raise ValueError(f"Project {project_id!r} contains duplicate child projects")
        if project_id in child_ids:
            raise ValueError(f"Project {project_id!r} cannot contain itself")
        object.__setattr__(self, "id", project_id)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "job_ids", job_ids)
        object.__setattr__(self, "child_project_ids", child_ids)


class ProjectSource(Protocol):
    """Read-only project source used by presentation code."""

    def projects(self) -> tuple[ProjectRecord, ...]: ...


def default_projects_path() -> Path:
    """Return the per-user persistent project index path."""
    return config_home() / "projects.json"


def validate_projects(projects: tuple[ProjectRecord, ...]) -> None:
    """Validate ownership and tree invariants for a complete project snapshot."""
    by_id: dict[str, ProjectRecord] = {}
    for project in projects:
        if project.id in by_id:
            raise ProjectStoreError(f"Duplicate project id {project.id!r}")
        by_id[project.id] = project

    job_owner: dict[str, str] = {}
    parent: dict[str, str] = {}
    for project in projects:
        for job_id in project.job_ids:
            previous = job_owner.get(job_id)
            if previous is not None:
                raise ProjectStoreError(
                    f"Job {job_id!r} belongs to both {previous!r} and {project.id!r}"
                )
            job_owner[job_id] = project.id
        for child_id in project.child_project_ids:
            if child_id not in by_id:
                raise ProjectStoreError(
                    f"Project {project.id!r} references missing child {child_id!r}"
                )
            previous = parent.get(child_id)
            if previous is not None:
                raise ProjectStoreError(
                    f"Project {child_id!r} has two parents: {previous!r} and {project.id!r}"
                )
            parent[child_id] = project.id

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(project_id: str) -> None:
        if project_id in visited:
            return
        if project_id in visiting:
            raise ProjectStoreError("Project hierarchy contains a cycle")
        visiting.add(project_id)
        for child_id in by_id[project_id].child_project_ids:
            visit(child_id)
        visiting.remove(project_id)
        visited.add(project_id)

    for project_id in by_id:
        visit(project_id)


def root_projects(projects: tuple[ProjectRecord, ...]) -> tuple[ProjectRecord, ...]:
    """Return projects which are not owned as children by another project."""
    children = {
        child_id
        for project in projects
        for child_id in project.child_project_ids
    }
    return tuple(project for project in projects if project.id not in children)


class ProjectStore:
    """Atomic persistent store whose projects own run ids and child projects."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_projects_path()
        self._lock = RLock()

    @staticmethod
    def _decode(data: object) -> tuple[ProjectRecord, ...]:
        if not isinstance(data, dict):
            raise ProjectStoreError("Project index root must be an object")
        schema_version = data.get("schema_version", _PROJECT_SCHEMA_VERSION)
        if schema_version != _PROJECT_SCHEMA_VERSION:
            raise ProjectStoreError(
                f"Unsupported project schema version {schema_version!r}"
            )
        raw_projects = data.get("projects", [])
        if not isinstance(raw_projects, list):
            raise ProjectStoreError("Project index 'projects' must be a list")
        projects: list[ProjectRecord] = []
        try:
            for value in raw_projects:
                if not isinstance(value, dict):
                    raise TypeError("project record must be an object")
                projects.append(ProjectRecord(**value))
        except (TypeError, ValueError) as exc:
            raise ProjectStoreError(str(exc)) from exc
        result = tuple(projects)
        validate_projects(result)
        return result

    def projects(self) -> tuple[ProjectRecord, ...]:
        """Read and validate the complete persistent project snapshot."""
        with self._lock:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return ()
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProjectStoreError(f"Cannot read project index: {exc}") from exc
            return self._decode(data)

    def replace_all(self, projects: tuple[ProjectRecord, ...]) -> None:
        """Atomically replace the complete project snapshot after validation."""
        projects = tuple(projects)
        validate_projects(projects)
        with self._lock:
            atomic_write_json(
                self.path,
                {
                    "schema_version": _PROJECT_SCHEMA_VERSION,
                    "projects": [asdict(project) for project in projects],
                },
            )

    def create(self, name: str, *, parent_id: str | None = None) -> ProjectRecord:
        """Create a project and optionally attach it below an existing parent."""
        with self._lock:
            projects = list(self.projects())
            record = ProjectRecord(id=uuid4().hex, name=name)
            if parent_id is not None:
                for index, project in enumerate(projects):
                    if project.id == parent_id:
                        projects[index] = ProjectRecord(
                            id=project.id,
                            name=project.name,
                            job_ids=project.job_ids,
                            child_project_ids=(*project.child_project_ids, record.id),
                        )
                        break
                else:
                    raise KeyError(parent_id)
            projects.append(record)
            self.replace_all(tuple(projects))
            return record

    def add_job(self, project_id: str, job_id: str) -> None:
        """Assign an existing persistent job id to exactly one project."""
        project_id = str(project_id)
        job_id = str(job_id)
        with self._lock:
            projects = list(self.projects())
            for project in projects:
                if job_id in project.job_ids:
                    if project.id == project_id:
                        return
                    raise ValueError(
                        f"Job {job_id!r} already belongs to project {project.id!r}"
                    )
            for index, project in enumerate(projects):
                if project.id == project_id:
                    projects[index] = ProjectRecord(
                        id=project.id,
                        name=project.name,
                        job_ids=(*project.job_ids, job_id),
                        child_project_ids=project.child_project_ids,
                    )
                    self.replace_all(tuple(projects))
                    return
            raise KeyError(project_id)

    def remove_job(self, project_id: str, job_id: str) -> None:
        """Remove one job membership without modifying the job itself."""
        with self._lock:
            projects = list(self.projects())
            for index, project in enumerate(projects):
                if project.id != project_id:
                    continue
                retained = tuple(value for value in project.job_ids if value != job_id)
                if retained == project.job_ids:
                    return
                projects[index] = ProjectRecord(
                    id=project.id,
                    name=project.name,
                    job_ids=retained,
                    child_project_ids=project.child_project_ids,
                )
                self.replace_all(tuple(projects))
                return
            raise KeyError(project_id)
