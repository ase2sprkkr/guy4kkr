"""Persistent project metadata and optimistic-concurrency repository."""
from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterator, Protocol
from uuid import UUID, uuid4

import platformdirs

from guy4ase.gui.application.atomic_io import atomic_write_json

try:  # POSIX
    import fcntl  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised on Windows
    fcntl = None

try:  # Windows
    import msvcrt  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised on POSIX
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


@dataclass(frozen=True)
class Project:
    """One persistent Guy4ASE project.

    ``persistent_refs`` contains stable ASE2SPRKKR persistent-run references.
    Runs themselves deliberately contain no reverse project reference.
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
        parent_id = (
            None if self.parent_id is None else _project_id(self.parent_id)
        )
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


class ProjectSource(Protocol):
    """Read-only project source used by presentation code."""

    def projects(self) -> tuple[Project, ...]: ...


def default_projects_directory() -> Path:
    """Return the per-user directory containing one JSON file per project."""
    return Path(
        platformdirs.user_data_dir("guy4ase", appauthor="ase2sprkkr")
    ) / "projects"


def _project_id(value: str) -> str:
    text = str(value).strip()
    try:
        return UUID(text).hex
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid project UUID {value!r}") from exc


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
    """Persist projects as independent generation-checked JSON documents.

    A stable sidecar lock serializes each read-check-write sequence. Project
    hierarchy mutations also use one repository-level lock because validating a
    parent move is a cross-project invariant. Generation checking remains the
    public stale-write guard; file locking is an implementation detail.
    """

    def __init__(self, directory: str | Path | None = None) -> None:
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

    def rename(
        self,
        project_id: str,
        name: str,
        *,
        expected_generation: int,
        overwrite: bool = False,
    ) -> Project:
        """Rename a project, optionally reapplying the edit after a conflict."""
        normalized = str(name).strip()
        if not normalized:
            raise ValueError("Project name must not be empty")
        return self._mutate(
            project_id,
            expected_generation=expected_generation,
            overwrite=overwrite,
            transform=lambda current: (
                current if current.name == normalized
                else replace(current, name=normalized)
            ),
        )

    def move(
        self,
        project_id: str,
        parent_id: str | None,
        *,
        expected_generation: int,
        overwrite: bool = False,
    ) -> Project:
        """Move a project in the hierarchy without editing either parent."""
        canonical_id = _project_id(project_id)
        parent = None if parent_id is None else _project_id(parent_id)
        if canonical_id == parent:
            raise ValueError("Project cannot be its own parent")

        with self._hierarchy_lock():
            def transform(current: Project) -> Project:
                if current.parent_id == parent:
                    return current
                projects = self.projects()
                if parent is not None and all(
                    item.id != parent for item in projects
                ):
                    raise KeyError(parent)
                candidate = replace(current, parent_id=parent)
                snapshot = tuple(
                    candidate if item.id == current.id else item
                    for item in projects
                )
                validate_hierarchy(snapshot)
                return candidate

            return self._mutate(
                canonical_id,
                expected_generation=expected_generation,
                overwrite=overwrite,
                transform=transform,
            )

    def add_run(
        self,
        project_id: str,
        persistent_ref: str,
        *,
        expected_generation: int,
        overwrite: bool = False,
    ) -> Project:
        """Add one stable persistent-run reference to a project."""
        ref = str(persistent_ref).strip()
        if not ref:
            raise ValueError("Persistent run reference must not be empty")
        return self._mutate(
            project_id,
            expected_generation=expected_generation,
            overwrite=overwrite,
            transform=lambda current: (
                current
                if ref in current.persistent_refs
                else replace(
                    current,
                    persistent_refs=(*current.persistent_refs, ref),
                )
            ),
        )

    def remove_run(
        self,
        project_id: str,
        persistent_ref: str,
        *,
        expected_generation: int,
        overwrite: bool = False,
    ) -> Project:
        """Remove one persistent-run reference without touching the run."""
        ref = str(persistent_ref).strip()
        return self._mutate(
            project_id,
            expected_generation=expected_generation,
            overwrite=overwrite,
            transform=lambda current: (
                current
                if ref not in current.persistent_refs
                else replace(
                    current,
                    persistent_refs=tuple(
                        value
                        for value in current.persistent_refs
                        if value != ref
                    ),
                )
            ),
        )

    def _mutate(
        self,
        project_id: str,
        *,
        expected_generation: int,
        overwrite: bool,
        transform: Callable[[Project], Project],
    ) -> Project:
        canonical = _project_id(project_id)
        with self._project_lock(canonical):
            current = self.project(canonical)
            candidate = transform(current)
            if candidate == current:
                return current
            if current.generation != expected_generation and not overwrite:
                raise ProjectConflictError(
                    canonical,
                    expected_generation=expected_generation,
                    current=current,
                )
            updated = replace(
                candidate,
                generation=current.generation + 1,
            )
            self._write(updated)
            return updated

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
                f"Unsupported project schema version {schema_version!r} "
                f"in {path}"
            )
        try:
            project = Project(**data)
        except (TypeError, ValueError) as exc:
            raise ProjectRepositoryError(
                f"Invalid project file {path}: {exc}"
            ) from exc
        if path.stem != project.id:
            raise ProjectRepositoryError(
                f"Project file name {path.stem!r} does not match id "
                f"{project.id!r}"
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
            raise ProjectRepositoryError(
                f"Cannot open project lock {path}: {exc}"
            ) from exc
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
                else:  # pragma: no cover - unsupported Python platform
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
