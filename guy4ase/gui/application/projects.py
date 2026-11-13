"""Persistent Guy4ASE project model and repository."""
from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterator
from uuid import UUID, uuid4

import platformdirs

from guy4ase.gui.application.atomic_io import atomic_write_json

try:  # POSIX
    import fcntl  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - Windows
    fcntl = None

try:  # Windows
    import msvcrt  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None

_PROJECT_SCHEMA_VERSION = 1
_HIERARCHY_LOCK = ".hierarchy.lock"


class ProjectRepositoryError(RuntimeError):
    """Base error for persistent project metadata."""


class ProjectConflictError(ProjectRepositoryError):
    """A project changed after the caller loaded it."""

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


class ProjectDeleteError(ProjectRepositoryError):
    """A project cannot be deleted while its hierarchy role requires it."""


@dataclass(frozen=True)
class Project:
    """One immutable project snapshot.

    Local editing methods return another snapshot at the same generation. The
    repository advances ``generation`` only after a successful persistent save.
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
        name = _project_name(self.name)
        parent_id = None if self.parent_id is None else _project_id(self.parent_id)
        if parent_id == project_id:
            raise ValueError("Project cannot be its own parent")
        refs = tuple(_persistent_ref(value) for value in self.persistent_refs)
        if len(set(refs)) != len(refs):
            raise ValueError("Project contains duplicate persistent run references")
        object.__setattr__(self, "id", project_id)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "parent_id", parent_id)
        object.__setattr__(self, "persistent_refs", refs)

    def rename(self, name: str) -> "Project":
        """Return this project with a validated display name."""
        normalized = _project_name(name)
        return self if normalized == self.name else replace(self, name=normalized)

    def move_to(self, parent_id: str | None) -> "Project":
        """Return this project with a different direct parent."""
        parent = None if parent_id is None else _project_id(parent_id)
        if parent == self.id:
            raise ValueError("Project cannot be its own parent")
        return self if parent == self.parent_id else replace(self, parent_id=parent)

    def add_run(self, persistent_ref: str) -> "Project":
        """Return this project referencing one additional persistent run."""
        ref = _persistent_ref(persistent_ref)
        if ref in self.persistent_refs:
            return self
        return replace(self, persistent_refs=(*self.persistent_refs, ref))

    def remove_run(self, persistent_ref: str) -> "Project":
        """Return this project without one persistent-run reference."""
        ref = _persistent_ref(persistent_ref)
        if ref not in self.persistent_refs:
            return self
        return replace(
            self,
            persistent_refs=tuple(value for value in self.persistent_refs if value != ref),
        )


def default_projects_directory() -> Path:
    """Return the application-data directory containing project JSON files."""
    return Path(
        platformdirs.user_data_dir("guy4ase", appauthor="ase2sprkkr")
    ) / "projects"


def _project_id(value: str) -> str:
    text = str(value).strip()
    try:
        return UUID(text).hex
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid project UUID {value!r}") from exc


def _project_name(value: str) -> str:
    name = str(value).strip()
    if not name:
        raise ValueError("Project name must not be empty")
    return name


def _persistent_ref(value: str) -> str:
    ref = str(value).strip()
    if not ref:
        raise ValueError("Persistent run reference must not be empty")
    return ref


def validate_hierarchy(projects: tuple[Project, ...]) -> None:
    """Validate parent references and reject hierarchy cycles."""
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


class ProjectRepository:
    """Persist independent generation-checked project JSON documents."""

    def __init__(self, directory: str | Path | None = None) -> None:
        self.directory = (
            Path(directory) if directory is not None else default_projects_directory()
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

    def create(self, name: str, *, parent_id: str | None = None) -> Project:
        """Create a root or child project at generation one."""
        parent = None if parent_id is None else _project_id(parent_id)
        project = Project(
            id=uuid4().hex,
            generation=1,
            name=name,
            parent_id=parent,
        )
        with self._hierarchy_lock():
            projects = self.projects()
            if parent is not None and all(item.id != parent for item in projects):
                raise KeyError(parent)
            with self._project_lock(project.id):
                path = self._json_path(project.id)
                if path.exists():
                    raise ProjectRepositoryError(
                        f"Generated project id already exists: {project.id}"
                    )
                self._write(project)
        return project

    def save(
        self,
        project: Project,
        *,
        expected_generation: int,
        overwrite: bool = False,
    ) -> Project:
        """Persist an edited project snapshot using optimistic concurrency.

        ``overwrite`` means exactly that: the supplied snapshot replaces the
        newer persisted values after validating it against the current project
        forest. It is intentionally not an implicit merge operation.
        """
        if not isinstance(project, Project):
            raise TypeError("project must be a Project")

        canonical = _project_id(project.id)
        with self._project_lock(canonical):
            current = self.project(canonical)
            self._check_generation(
                current,
                expected_generation=expected_generation,
                overwrite=overwrite,
            )
            if project.parent_id == current.parent_id:
                return self._save_locked(project, current)

        # Parent changes affect a cross-project invariant. Re-enter with the
        # hierarchy lock first so create/delete/move all use one lock order.
        with self._hierarchy_lock(), self._project_lock(canonical):
            current = self.project(canonical)
            self._check_generation(
                current,
                expected_generation=expected_generation,
                overwrite=overwrite,
            )
            projects = self.projects()
            candidate = replace(project, generation=current.generation)
            snapshot = tuple(
                candidate if item.id == canonical else item for item in projects
            )
            validate_hierarchy(snapshot)
            return self._save_locked(project, current)

    def delete(self, project_id: str, *, expected_generation: int) -> None:
        """Delete a non-root leaf project without touching referenced runs."""
        canonical = _project_id(project_id)
        with self._hierarchy_lock(), self._project_lock(canonical):
            current = self.project(canonical)
            self._check_generation(
                current,
                expected_generation=expected_generation,
                overwrite=False,
            )
            if current.parent_id is None:
                raise ProjectDeleteError("Root projects cannot be deleted")
            projects = self.projects()
            if any(item.parent_id == canonical for item in projects):
                raise ProjectDeleteError("Projects with child projects cannot be deleted")
            try:
                self._json_path(canonical).unlink()
            except OSError as exc:
                raise ProjectRepositoryError(
                    f"Cannot delete project {canonical!r}: {exc}"
                ) from exc

    def _save_locked(self, project: Project, current: Project) -> Project:
        updated = replace(project, generation=current.generation + 1)
        self._write(updated)
        return updated

    @staticmethod
    def _check_generation(
        current: Project,
        *,
        expected_generation: int,
        overwrite: bool,
    ) -> None:
        if current.generation != expected_generation and not overwrite:
            raise ProjectConflictError(
                current.id,
                expected_generation=expected_generation,
                current=current,
            )

    def _read_path(self, path: Path) -> Project:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise KeyError(path.stem) from exc
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProjectRepositoryError(f"Cannot read project {path}: {exc}") from exc
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
            raise ProjectRepositoryError(f"Invalid project file {path}: {exc}") from exc
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

    @contextmanager
    def _project_lock(self, project_id: str) -> Iterator[None]:
        with self._file_lock(self._lock_path(project_id)):
            yield

    @contextmanager
    def _hierarchy_lock(self) -> Iterator[None]:
        with self._file_lock(self.directory / _HIERARCHY_LOCK):
            yield

    @contextmanager
    def _file_lock(self, path: Path) -> Iterator[None]:
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            stream = path.open("a+b")
        except OSError as exc:
            raise ProjectRepositoryError(f"Cannot open project lock {path}: {exc}") from exc
        with stream:
            try:
                if fcntl is not None:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                elif msvcrt is not None:
                    if stream.seek(0, 2) == 0:
                        stream.write(b"\0")
                        stream.flush()
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
                else:  # pragma: no cover - unsupported platform
                    raise ProjectRepositoryError(
                        "No supported file-locking primitive is available"
                    )
            except OSError as exc:
                raise ProjectRepositoryError(
                    f"Cannot lock project repository at {path}: {exc}"
                ) from exc
            try:
                yield
            finally:
                try:
                    if fcntl is not None:
                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                    elif msvcrt is not None:
                        stream.seek(0)
                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
