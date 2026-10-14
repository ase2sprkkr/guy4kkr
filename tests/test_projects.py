"""Tests for per-project JSON persistence and optimistic concurrency."""
from __future__ import annotations

import json

import pytest

from guy4ase.gui.application.projects import (
    ProjectConflictError,
    ProjectRepository,
    ProjectRepositoryError,
)

ROOT_A = "11111111111111111111111111111111"
ROOT_B = "22222222222222222222222222222222"
CHILD = "33333333333333333333333333333333"


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
    (directory / f"{project_id}.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


def test_repository_uses_one_generation_checked_json_per_project(tmp_path):
    repository = ProjectRepository(tmp_path / "projects")
    parent = repository.create("Parent")
    child = repository.create("Child", parent_id=parent.id)

    json_files = sorted(repository.directory.glob("*.json"))
    assert [path.stem for path in json_files] == sorted([parent.id, child.id])
    assert repository.project(child.id).parent_id == parent.id
    data = json.loads(
        (repository.directory / f"{parent.id}.json").read_text(encoding="utf-8")
    )
    assert data["generation"] == 1
    assert data["persistent_refs"] == []


def test_stale_write_conflicts_and_overwrite_reapplies_operation(tmp_path):
    first = ProjectRepository(tmp_path / "projects")
    second = ProjectRepository(first.directory)
    project = first.create("Original")

    first_snapshot = first.project(project.id)
    second_snapshot = second.project(project.id)
    renamed = first.rename(
        project.id,
        "Renamed elsewhere",
        expected_generation=first_snapshot.generation,
    )

    with pytest.raises(ProjectConflictError) as exc_info:
        second.add_run(
            project.id,
            "run-17",
            expected_generation=second_snapshot.generation,
        )
    assert exc_info.value.current == renamed

    updated = second.add_run(
        project.id,
        "run-17",
        expected_generation=second_snapshot.generation,
        overwrite=True,
    )
    assert updated.name == "Renamed elsewhere"
    assert updated.persistent_refs == ("run-17",)
    assert updated.generation == renamed.generation + 1


def test_move_changes_only_child_document_and_keeps_hierarchy_valid(tmp_path):
    directory = tmp_path / "projects"
    _write_project(directory, ROOT_A, name="A")
    _write_project(directory, ROOT_B, name="B")
    _write_project(directory, CHILD, name="Child", parent_id=ROOT_A)
    repository = ProjectRepository(directory)

    before_a = repository.project(ROOT_A)
    before_b = repository.project(ROOT_B)
    before_child = repository.project(CHILD)
    moved = repository.move(
        CHILD,
        ROOT_B,
        expected_generation=before_child.generation,
    )

    assert moved.parent_id == ROOT_B
    assert moved.generation == before_child.generation + 1
    assert repository.project(ROOT_A) == before_a
    assert repository.project(ROOT_B) == before_b


def test_hierarchy_rejects_cycles(tmp_path):
    directory = tmp_path / "projects"
    _write_project(directory, ROOT_A, name="A")
    _write_project(directory, CHILD, name="Child", parent_id=ROOT_A)
    repository = ProjectRepository(directory)

    root = repository.project(ROOT_A)
    with pytest.raises(ProjectRepositoryError, match="cycle"):
        repository.move(
            ROOT_A,
            CHILD,
            expected_generation=root.generation,
        )


def test_persistent_reference_membership_is_owned_only_by_project_file(tmp_path):
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("Project")

    with_run = repository.add_run(
        project.id,
        "persistent-run-id",
        expected_generation=project.generation,
    )
    assert with_run.persistent_refs == ("persistent-run-id",)

    without_run = repository.remove_run(
        project.id,
        "persistent-run-id",
        expected_generation=with_run.generation,
    )
    assert without_run.persistent_refs == ()
