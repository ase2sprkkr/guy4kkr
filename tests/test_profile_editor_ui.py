from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from guy4ase.gui.dialogs import profiles as profiles_module


def _app():
    return QApplication.instance() or QApplication([])


def test_profile_form_exposes_all_execution_types():
    _application = _app()
    form = profiles_module._ProfileForm()

    kinds = [form.kind.itemData(index) for index in range(form.kind.count())]
    labels = [form.kind.itemText(index) for index in range(form.kind.count())]

    assert kinds == ["local", "ssh", "psij", "ssh-psij"]
    assert labels == [
        "Local computer",
        "Remote computer (SSH)",
        "Workload manager (PSI/J)",
        "Remote workload manager (SSH + PSI/J)",
    ]
    form.close()


def test_profile_form_explains_selected_run_target():
    _application = _app()
    form = profiles_module._ProfileForm()

    expected = {
        "local": "Run directly on this computer.",
        "ssh": "Run on another computer connected over SSH.",
        "psij": (
            "Submit the calculation to a workload manager accessible from this computer."
        ),
        "ssh-psij": (
            "Connect to a remote cluster over SSH and submit the calculation "
            "to its workload manager."
        ),
    }
    for kind, description in expected.items():
        form.kind.setCurrentIndex(form.kind.findData(kind))
        assert form.run_target_description.text() == description

    form.close()


def test_profile_form_serializes_all_execution_types():
    _application = _app()
    form = profiles_module._ProfileForm()

    form.kind.setCurrentIndex(form.kind.findData("local"))
    assert form.values()["executor"] == "local"

    form.kind.setCurrentIndex(form.kind.findData("ssh"))
    form.host.setText("user@cluster")
    ssh = form.values()
    assert ssh["executor"] == "ssh"
    assert ssh["host"] == "user@cluster"
    assert "psij_backend" not in ssh

    form.kind.setCurrentIndex(form.kind.findData("psij"))
    form.psij_backend.setText("slurm")
    psij = form.values()
    assert psij["executor"] == "psij"
    assert psij["psij_backend"] == "slurm"
    assert "host" not in psij

    form.kind.setCurrentIndex(form.kind.findData("ssh-psij"))
    combined = form.values()
    assert combined["executor"] == "ssh"
    assert combined["host"] == "user@cluster"
    assert combined["psij_backend"] == "slurm"
    form.close()


def test_profile_form_shows_only_backend_specific_sections():
    _application = _app()
    form = profiles_module._ProfileForm()

    form.kind.setCurrentIndex(form.kind.findData("local"))
    assert form.ssh_box.isHidden()
    assert form.psij_box.isHidden()

    form.kind.setCurrentIndex(form.kind.findData("ssh"))
    assert not form.ssh_box.isHidden()
    assert form.psij_box.isHidden()

    form.kind.setCurrentIndex(form.kind.findData("psij"))
    assert form.ssh_box.isHidden()
    assert not form.psij_box.isHidden()

    form.kind.setCurrentIndex(form.kind.findData("ssh-psij"))
    assert not form.ssh_box.isHidden()
    assert not form.psij_box.isHidden()
    form.close()


def test_mpi_editor_supports_all_modes():
    _application = _app()
    editor = profiles_module._MpiEditor()

    for mode, value in (
        ("auto", "auto"),
        ("enabled", True),
        ("disabled", False),
    ):
        editor.mode.setCurrentIndex(editor.mode.findData(mode))
        assert editor.value() == value

    editor.mode.setCurrentIndex(editor.mode.findData("processes"))
    editor.processes.setValue(12)
    assert editor.value() == 12
    assert editor.detail.currentWidget() is editor.processes

    editor.mode.setCurrentIndex(editor.mode.findData("command"))
    editor.command.setText("mpirun --bind-to core")
    assert editor.value() == ["mpirun", "--bind-to", "core"]
    assert editor.detail.currentWidget() is editor.command
    editor.close()


def test_mpi_editor_loads_existing_typed_values():
    _application = _app()
    editor = profiles_module._MpiEditor()

    for value, mode in (
        (None, "disabled"),
        ("auto", "auto"),
        (True, "enabled"),
        (False, "disabled"),
        (8, "processes"),
        (["srun", "-n", "4"], "command"),
    ):
        editor.set_value(value)
        assert editor.mode.currentData() == mode

    assert editor.command.text() == "srun -n 4"
    editor.close()
