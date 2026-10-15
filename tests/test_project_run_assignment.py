from guy4ase.gui.application.projects import ProjectRepository


def test_add_run_replays_on_latest_project_snapshot_after_conflict(tmp_path, monkeypatch):
    directory = tmp_path / "projects"
    repository = ProjectRepository(directory)
    project = repository.create("Original")
    external = ProjectRepository(directory)

    original_save = repository.save
    conflicted = False

    def save_with_one_conflict(edited, *, expected_generation, overwrite=False):
        nonlocal conflicted
        if not conflicted:
            conflicted = True
            current = external.project(project.id)
            external.save(
                current.rename("Changed elsewhere"),
                expected_generation=current.generation,
            )
        return original_save(
            edited,
            expected_generation=expected_generation,
            overwrite=overwrite,
        )

    monkeypatch.setattr(repository, "save", save_with_one_conflict)

    saved = repository.add_run(project.id, "run-17")

    assert conflicted
    assert saved.name == "Changed elsewhere"
    assert saved.persistent_refs == ("run-17",)
    assert repository.project(project.id) == saved


def test_add_run_is_idempotent(tmp_path):
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("Project")

    first = repository.add_run(project.id, "run-17")
    second = repository.add_run(project.id, "run-17")

    assert second == first
    assert second.persistent_refs == ("run-17",)
