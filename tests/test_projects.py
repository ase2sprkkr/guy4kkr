"""Tests for per-project JSON persistence and project invariants."""
from __future__ import annotations

import json
import multiprocessing

import pytest
from ase2sprkkr.common.file_locks import FileLock

from guy4ase.gui.application.projects import (
    Project,
    ProjectConflictError,
    ProjectRepository,
    ProjectRepositoryError,
)

ROOT_A = "11111111111111111111111111111111"
ROOT_B = "22222222222222222222222222222222"
CHILD = "33333333333333333333333333333333"
GRANDCHILD = "44444444444444444444444444444444"


def _write_project(directory, project_id, **values):
    data = {
        "schema_version": 1,
        "id": project_id,
        "generation": 1,
        "name": project_id,
        "parent_id": None,
        "persistent_refs": [],
    }
    data.update(values)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{project_id}.json").write_text(json.dumps(data), encoding="utf-8")


def _hold_hierarchy_lock(directory, acquired, release):
    with FileLock(directory / ".hierarchy.lock"):
        acquired.set()
        release.wait(5)


def _save_project(directory, project_id, started):
    repository = ProjectRepository(directory)
    project = repository.project(project_id)
    started.set()
    repository.save(project.rename("Writer"))


def test_project_owns_local_edit_operations():
    project = Project(id=ROOT_A, generation=3, name="Old", persistent_refs=("run-1",))
    renamed = project.rename("New")
    moved = renamed.move_to(ROOT_B)
    with_run = moved.add_run("run-2")
    without_run = with_run.remove_run("run-1")

    assert renamed.name == "New"
    assert renamed.generation == 3
    assert moved.parent_id == ROOT_B
    assert with_run.persistent_refs == ("run-1", "run-2")
    assert without_run.persistent_refs == ("run-2",)
    assert with_run.add_run("run-2") is with_run
    assert without_run.remove_run("not-there") is without_run


def test_project_rejects_invalid_local_edits():
    project = Project(id=ROOT_A, generation=1, name="Project")
    with pytest.raises(ValueError, match="empty"):
        project.rename("   ")
    with pytest.raises(ValueError, match="own parent"):
        project.move_to(project.id)
    with pytest.raises(ValueError, match="must not be empty"):
        project.add_run("")


def test_repository_uses_one_generation_checked_json_per_project(tmp_path):
    repository = ProjectRepository(tmp_path / "projects")
    parent = repository.create("Parent")
    child = repository.create("Child", parent_id=parent.id)
    json_files = sorted(repository.directory.glob("*.json"))
    assert [path.stem for path in json_files] == sorted([parent.id, child.id])
    assert repository.project(child.id).parent_id == parent.id


def test_save_detects_stale_generation_before_validating_edit(tmp_path):
    repository = ProjectRepository(tmp_path / "projects")
    parent = repository.create("Parent")
    child = repository.create("Child", parent_id=parent.id)
    stale = repository.project(parent.id)
    current = repository.save(stale.rename("Current"))
    with pytest.raises(ProjectConflictError) as exc_info:
        repository.save(stale.move_to(child.id))
    assert exc_info.value.current == current


def test_overwrite_replaces_newer_snapshot_explicitly(tmp_path):
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("Original")
    stale = repository.project(project.id)
    current = repository.save(stale.rename("Renamed elsewhere"))
    overwritten = repository.save(stale.add_run("run-17"), overwrite=True)
    assert overwritten.name == "Original"
    assert overwritten.persistent_refs == ("run-17",)
    assert overwritten.generation == current.generation + 1


def test_save_validates_project_hierarchy(tmp_path):
    directory = tmp_path / "projects"
    _write_project(directory, ROOT_A, name="A")
    _write_project(directory, CHILD, name="Child", parent_id=ROOT_A)
    repository = ProjectRepository(directory)
    with pytest.raises(ProjectRepositoryError, match="cycle"):
        repository.save(repository.project(ROOT_A).move_to(CHILD))


def test_delete_rejects_root_and_parent_but_allows_leaf_child(tmp_path):
    directory = tmp_path / "projects"
    _write_project(directory, ROOT_A, name="Root")
    _write_project(directory, CHILD, name="Child", parent_id=ROOT_A)
    _write_project(directory, GRANDCHILD, name="Grandchild", parent_id=CHILD)
    repository = ProjectRepository(directory)
    with pytest.raises(ProjectRepositoryError, match="Root projects"):
        repository.delete(repository.project(ROOT_A))
    with pytest.raises(ProjectRepositoryError, match="child projects"):
        repository.delete(repository.project(CHILD))
    repository.delete(repository.project(GRANDCHILD))
    with pytest.raises(KeyError):
        repository.project(GRANDCHILD)


def test_repository_emits_change_and_reload_protocol(tmp_path):
    repository = ProjectRepository(tmp_path / "projects")
    changed = []
    reloaded = []
    repository.changed.connect(changed.append)
    repository.reloaded.connect(lambda: reloaded.append(True))
    project = repository.create("Project")
    project = repository.save(project.add_run("run-1"))
    repository.refresh()
    assert changed == [project.id, project.id]
    assert reloaded == [True]


def test_save_waits_for_repository_interprocess_lock(tmp_path):
    directory = tmp_path / "projects"
    repository = ProjectRepository(directory)
    project = repository.create("Project")
    context = multiprocessing.get_context("spawn")
    acquired = context.Event()
    release = context.Event()
    started = context.Event()
    holder = context.Process(target=_hold_hierarchy_lock, args=(directory, acquired, release))
    writer = context.Process(target=_save_project, args=(directory, project.id, started))
    holder.start()
    assert acquired.wait(5)
    writer.start()
    assert started.wait(5)
    writer.join(timeout=0.2)
    assert writer.is_alive()
    release.set()
    holder.join(5)
    writer.join(5)
    assert holder.exitcode == 0
    assert writer.exitcode == 0
    assert repository.project(project.id).name == "Writer"
