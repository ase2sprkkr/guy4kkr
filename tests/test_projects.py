"""Tests for persistent project ownership and hierarchy invariants."""
from __future__ import annotations

import json

import pytest

from guy4ase.gui.application.projects import (
    ProjectRecord,
    ProjectStore,
    ProjectStoreError,
    root_projects,
    validate_projects,
)


def test_project_store_persists_owned_jobs_and_children(tmp_path):
    store = ProjectStore(tmp_path / "projects.json")
    child = ProjectRecord(id="child", name="Child", job_ids=("job-2",))
    parent = ProjectRecord(
        id="parent",
        name="Parent",
        job_ids=("job-1",),
        child_project_ids=(child.id,),
    )

    store.replace_all((parent, child))

    assert store.projects() == (parent, child)
    assert root_projects(store.projects()) == (parent,)
    data = json.loads(store.path.read_text(encoding="utf-8"))
    assert all("project_id" not in record for record in data["projects"])
    assert data["projects"][0]["job_ids"] == ["job-1"]


def test_job_can_be_owned_by_only_one_project():
    projects = (
        ProjectRecord(id="a", name="A", job_ids=("same-job",)),
        ProjectRecord(id="b", name="B", job_ids=("same-job",)),
    )

    with pytest.raises(ProjectStoreError, match="belongs to both"):
        validate_projects(projects)


def test_project_tree_rejects_multiple_parents_and_cycles():
    child = ProjectRecord(id="child", name="Child")
    first = ProjectRecord(id="first", name="First", child_project_ids=(child.id,))
    second = ProjectRecord(id="second", name="Second", child_project_ids=(child.id,))
    with pytest.raises(ProjectStoreError, match="two parents"):
        validate_projects((first, second, child))

    a = ProjectRecord(id="a", name="A", child_project_ids=("b",))
    b = ProjectRecord(id="b", name="B", child_project_ids=("a",))
    with pytest.raises(ProjectStoreError, match="cycle"):
        validate_projects((a, b))


def test_add_and_remove_job_mutate_only_project_membership(tmp_path):
    store = ProjectStore(tmp_path / "projects.json")
    project = ProjectRecord(id="p", name="Project")
    store.replace_all((project,))

    store.add_job(project.id, "run-17")
    assert store.projects()[0].job_ids == ("run-17",)

    store.remove_job(project.id, "run-17")
    assert store.projects()[0].job_ids == ()


def test_add_job_refuses_implicit_move_between_projects(tmp_path):
    store = ProjectStore(tmp_path / "projects.json")
    store.replace_all(
        (
            ProjectRecord(id="a", name="A", job_ids=("run-17",)),
            ProjectRecord(id="b", name="B"),
        )
    )

    with pytest.raises(ValueError, match="already belongs"):
        store.add_job("b", "run-17")
