"""Execution-profile selection and editing for SPR-KKR calculations."""
from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Any

from ase2sprkkr.configuration import config
from ase2sprkkr.sprkkr.profile import resolve_sprkkr_profile
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from guy4ase.gui.application.window_geometry import manage_window_geometry


_RESERVED_PROFILES = frozenset(("ase", "legacy"))
_SYNC_POLICIES = ("changed", "always", "missing", "never")
_MPI_MODES = (
    ("auto", "Autodetect"),
    ("enabled", "Yes"),
    ("disabled", "No"),
    ("processes", "Number of processes"),
    ("command", "Command"),
)
_RUN_TARGET_DESCRIPTIONS = {
    "local": "Run directly on this computer.",
    "ssh": "Run on another computer connected over SSH.",
    "psij": "Submit the calculation to a workload manager accessible from this computer.",
    "ssh-psij": (
        "Connect to a remote cluster over SSH and submit the calculation "
        "to its workload manager."
    ),
}


def _option_value(profile: Any, name: str) -> Any:
    value = getattr(profile, name, None)
    return value() if callable(value) else value


def _profile_values(profile: Any) -> dict[str, Any]:
    values = profile.as_dict(only_changed="explicit", generated=False) or {}
    values.pop("command", None)
    return dict(values)


def _runtime_profile(name: str | None):
    return resolve_sprkkr_profile(name)


def _argv_text(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        return value
    return shlex.join(str(item) for item in value)


def _backend_kind(profile: Any) -> str:
    executor = _option_value(profile, "executor") or "local"
    if executor == "ssh" and (
        _option_value(profile, "psij_backend") is not None
        or _option_value(profile, "psij_url") is not None
    ):
        return "ssh-psij"
    return str(executor)


def _draft_kind(values: dict[str, Any]) -> str:
    executor = values.get("executor") or "local"
    if executor == "ssh" and (
        values.get("psij_backend") is not None
        or values.get("psij_url") is not None
    ):
        return "ssh-psij"
    return str(executor)


def _kind_label(kind: str) -> str:
    return {
        "local": "Local computer",
        "ssh": "Remote computer (SSH)",
        "psij": "Workload manager (PSI/J)",
        "ssh-psij": "Remote workload manager (SSH + PSI/J)",
    }.get(kind, kind)


def profile_description(name: str | None) -> str:
    """Return a short user-facing description of one resolved profile."""
    profile = _runtime_profile(name)
    kind = _backend_kind(profile)
    if kind == "local":
        where = "Local execution"
    elif kind == "ssh":
        where = f"SSH to {profile.host or '(host not set)'}"
    elif kind == "ssh-psij":
        backend = profile.psij_backend or "slurm"
        where = f"SSH to {profile.host or '(host not set)'} + PSI/J ({backend})"
    elif kind == "psij":
        where = f"PSI/J ({profile.psij_backend or 'slurm'})"
    else:
        where = f"{profile.executor} execution"

    mpi = profile.mpi
    if mpi is False:
        mpi_text = "MPI disabled"
    elif mpi is True:
        mpi_text = "MPI enabled"
    elif mpi is None or mpi == "auto":
        mpi_text = "MPI automatic"
    elif isinstance(mpi, int):
        mpi_text = f"MPI: {mpi} processes"
    elif isinstance(mpi, (tuple, list)):
        mpi_text = "MPI: " + shlex.join(str(item) for item in mpi)
    else:
        mpi_text = f"MPI: {mpi}"

    executable = profile.executable_dir or "PATH"
    if profile.executable_suffix:
        executable = f"{executable} (suffix {profile.executable_suffix})"
    return f"{where} · {mpi_text}\nExecutables: {executable}"


@dataclass
class _ProfileDraft:
    name: str
    values: dict[str, Any]
    read_only: bool = False


class _MpiEditor(QWidget):
    """Typed editor for the supported MPI profile values."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.mode = QComboBox(self)
        for value, label in _MPI_MODES:
            self.mode.addItem(label, value)
        self.mode.setMinimumContentsLength(18)
        layout.addWidget(self.mode)

        self.detail = QStackedWidget(self)
        self._blank = QWidget(self.detail)
        self.processes = QSpinBox(self.detail)
        self.processes.setRange(1, 1_000_000)
        self.processes.setValue(2)
        self.command = QLineEdit(self.detail)
        self.command.setPlaceholderText("e.g. mpirun --bind-to core")
        self.detail.addWidget(self._blank)
        self.detail.addWidget(self.processes)
        self.detail.addWidget(self.command)
        layout.addWidget(self.detail, 1)

        self.mode.currentIndexChanged.connect(self._update_detail)
        self._update_detail()

    def _update_detail(self) -> None:
        mode = self.mode.currentData()
        if mode == "processes":
            self.detail.setCurrentWidget(self.processes)
        elif mode == "command":
            self.detail.setCurrentWidget(self.command)
        else:
            self.detail.setCurrentWidget(self._blank)

    def set_value(self, value: Any) -> None:
        if value is None or value == "auto":
            mode = "auto"
        elif value is True:
            mode = "enabled"
        elif value is False:
            mode = "disabled"
        elif isinstance(value, int):
            mode = "processes"
            self.processes.setValue(max(1, value))
        elif isinstance(value, (tuple, list)):
            mode = "command"
            self.command.setText(_argv_text(value))
        elif isinstance(value, str):
            mode = "command"
            self.command.setText(value)
        else:
            mode = "auto"
        self.mode.setCurrentIndex(max(self.mode.findData(mode), 0))
        self._update_detail()

    def value(self) -> Any:
        mode = self.mode.currentData()
        if mode == "auto":
            return "auto"
        if mode == "enabled":
            return True
        if mode == "disabled":
            return False
        if mode == "processes":
            return self.processes.value()
        return shlex.split(self.command.text())

    def setText(self, text: str) -> None:
        """Compatibility helper for older callers/tests using the former QLineEdit."""
        text = text.strip()
        lowered = text.lower()
        if lowered in {"", "auto"}:
            self.set_value("auto")
        elif lowered in {"false", "off", "no"}:
            self.set_value(False)
        elif lowered in {"true", "on", "yes"}:
            self.set_value(True)
        else:
            try:
                self.set_value(int(text))
            except ValueError:
                self.set_value(shlex.split(text))


class _ProfileForm(QWidget):
    """Edit one mutable profile; backend-specific sections follow its type."""

    _KINDS = (
        ("local", "Local computer"),
        ("ssh", "Remote computer (SSH)"),
        ("psij", "Workload manager (PSI/J)"),
        ("ssh-psij", "Remote workload manager (SSH + PSI/J)"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(14)

        self.title = QLabel("Profile settings", self)
        title_font = self.title.font()
        title_font.setPointSize(title_font.pointSize() + 2)
        title_font.setBold(True)
        self.title.setFont(title_font)
        root.addWidget(self.title)

        self.read_only_note = QLabel(
            "This profile is provided by another configuration source and is read-only.",
            self,
        )
        self.read_only_note.setWordWrap(True)
        root.addWidget(self.read_only_note)

        self.form_widget = QWidget(self)
        form_root = QVBoxLayout(self.form_widget)
        form_root.setContentsMargins(0, 0, 0, 0)
        form_root.setSpacing(12)

        run_box = QGroupBox("Run target", self.form_widget)
        run_form = QFormLayout(run_box)
        run_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.kind = QComboBox(run_box)
        for value, label in self._KINDS:
            self.kind.addItem(label, value)
        self.kind.setMinimumContentsLength(30)
        self.kind.currentIndexChanged.connect(self._update_visibility)
        run_form.addRow("Type:", self.kind)
        self.run_target_description = QLabel(run_box)
        self.run_target_description.setWordWrap(True)
        self.run_target_description.setStyleSheet("color: palette(mid);")
        run_form.addRow(self.run_target_description)
        self.mpi = _MpiEditor(run_box)
        self.mpi.mode.currentIndexChanged.connect(self._update_mpi_warning_visibility)
        run_form.addRow("MPI:", self.mpi)
        self.mpi_warning = QCheckBox("Warn if MPI is not detected", run_box)
        self.mpi_warning.setToolTip(
            "Show a warning when MPI autodetection cannot find an MPI runner "
            "and the calculation falls back to non-MPI execution."
        )
        self.mpi_warning.setChecked(True)
        run_form.addRow(self.mpi_warning)
        form_root.addWidget(run_box)

        executable_box = QGroupBox("SPR-KKR executables", self.form_widget)
        executable_form = QFormLayout(executable_box)
        executable_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.executable_dir = QLineEdit(executable_box)
        self.executable_dir.setPlaceholderText("Use PATH when empty")
        executable_form.addRow("Directory:", self.executable_dir)
        self.executable_suffix = QLineEdit(executable_box)
        self.executable_suffix.setPlaceholderText("e.g. _v8")
        executable_form.addRow("Suffix:", self.executable_suffix)
        form_root.addWidget(executable_box)

        self.ssh_box = QGroupBox("SSH connection and workspace", self.form_widget)
        ssh_form = QFormLayout(self.ssh_box)
        ssh_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.host = QLineEdit(self.ssh_box)
        self.host.setPlaceholderText("user@cluster.example")
        ssh_form.addRow("Host:", self.host)
        self.local_root = QLineEdit(self.ssh_box)
        ssh_form.addRow("Local root:", self.local_root)
        self.remote_root = QLineEdit(self.ssh_box)
        ssh_form.addRow("Remote root:", self.remote_root)
        self.ssh_options = QLineEdit(self.ssh_box)
        self.ssh_options.setPlaceholderText("e.g. -p 2222")
        ssh_form.addRow("SSH options:", self.ssh_options)
        self.remote_command = QLineEdit(self.ssh_box)
        self.remote_command.setPlaceholderText("ase2sprkkr remote")
        ssh_form.addRow("Remote command:", self.remote_command)
        self.input_sync = QComboBox(self.ssh_box)
        self.output_sync = QComboBox(self.ssh_box)
        for policy in _SYNC_POLICIES:
            self.input_sync.addItem(policy)
            self.output_sync.addItem(policy)
        ssh_form.addRow("Input sync:", self.input_sync)
        ssh_form.addRow("Output sync:", self.output_sync)
        form_root.addWidget(self.ssh_box)

        self.psij_box = QGroupBox("Workload manager (PSI/J)", self.form_widget)
        psij_form = QFormLayout(self.psij_box)
        psij_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.psij_backend = QLineEdit(self.psij_box)
        self.psij_backend.setPlaceholderText("slurm")
        psij_form.addRow("Backend:", self.psij_backend)
        self.psij_url = QLineEdit(self.psij_box)
        self.psij_url.setPlaceholderText("Optional executor URL")
        psij_form.addRow("URL:", self.psij_url)
        form_root.addWidget(self.psij_box)

        root.addWidget(self.form_widget)
        root.addStretch(1)
        self._update_visibility()

    def _update_mpi_warning_visibility(self) -> None:
        self.mpi_warning.setVisible(self.mpi.mode.currentData() == "auto")

    def _update_visibility(self) -> None:
        kind = str(self.kind.currentData())
        ssh = kind in {"ssh", "ssh-psij"}
        psij = kind in {"psij", "ssh-psij"}
        self.run_target_description.setText(_RUN_TARGET_DESCRIPTIONS.get(kind, ""))
        self.ssh_box.setVisible(ssh)
        self.psij_box.setVisible(psij)
        self._update_mpi_warning_visibility()
        for widget in (
            self.host,
            self.local_root,
            self.remote_root,
            self.ssh_options,
            self.remote_command,
            self.input_sync,
            self.output_sync,
        ):
            widget.setVisible(ssh)
        self.psij_backend.setVisible(psij)
        self.psij_url.setVisible(psij)

    def load(self, draft: _ProfileDraft) -> None:
        values = draft.values
        kind = _draft_kind(values)
        self.kind.setCurrentIndex(max(self.kind.findData(kind), 0))
        self.mpi.set_value(values.get("mpi"))
        self.mpi_warning.setChecked(bool(values.get("mpi_warning", True)))
        self.executable_dir.setText(str(values.get("executable_dir") or ""))
        self.executable_suffix.setText(str(values.get("executable_suffix") or ""))
        self.host.setText(str(values.get("host") or ""))
        self.local_root.setText(str(values.get("local_root") or ""))
        self.remote_root.setText(str(values.get("remote_root") or ""))
        self.ssh_options.setText(_argv_text(values.get("ssh_options")))
        self.remote_command.setText(_argv_text(values.get("remote_command")))
        self.input_sync.setCurrentText(str(values.get("input_sync") or "changed"))
        self.output_sync.setCurrentText(str(values.get("output_sync") or "changed"))
        self.psij_backend.setText(str(values.get("psij_backend") or ""))
        self.psij_url.setText(str(values.get("psij_url") or ""))
        self.form_widget.setEnabled(not draft.read_only)
        self.read_only_note.setVisible(draft.read_only)
        self._update_visibility()

    def values(self) -> dict[str, Any]:
        kind = str(self.kind.currentData())
        executor = "ssh" if kind == "ssh-psij" else kind
        values: dict[str, Any] = {
            "executor": executor,
            "mpi": self.mpi.value(),
            "mpi_warning": self.mpi_warning.isChecked(),
        }
        for name, edit in (
            ("executable_dir", self.executable_dir),
            ("executable_suffix", self.executable_suffix),
        ):
            text = edit.text().strip()
            if text:
                values[name] = text

        if kind in {"ssh", "ssh-psij"}:
            for name, edit in (
                ("host", self.host),
                ("local_root", self.local_root),
                ("remote_root", self.remote_root),
            ):
                text = edit.text().strip()
                if text:
                    values[name] = text
            ssh_options = shlex.split(self.ssh_options.text())
            remote_command = shlex.split(self.remote_command.text())
            if ssh_options:
                values["ssh_options"] = ssh_options
            if remote_command:
                values["remote_command"] = remote_command
            values["input_sync"] = self.input_sync.currentText()
            values["output_sync"] = self.output_sync.currentText()

        if kind in {"psij", "ssh-psij"}:
            backend = self.psij_backend.text().strip()
            url = self.psij_url.text().strip()
            if backend:
                values["psij_backend"] = backend
            if url:
                values["psij_url"] = url
        return values


class ProfilesDialog(QDialog):
    """Edit persistent ASE2SPRKKR execution profiles."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("SPR-KKR Execution Profiles")
        self.setMinimumSize(1040, 680)
        manage_window_geometry(
            self,
            "execution-profiles",
            default_size=(1200, 800),
        )
        self._drafts: dict[str, _ProfileDraft] = {}
        for name, profile in config.profiles.items():
            self._drafts[str(name)] = _ProfileDraft(
                str(name),
                _profile_values(profile),
                bool(getattr(profile, "read_only", False)) or name in _RESERVED_PROFILES,
            )

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 14)
        root.setSpacing(12)

        heading = QLabel("Execution profiles", self)
        heading_font = heading.font()
        heading_font.setPointSize(heading_font.pointSize() + 3)
        heading_font.setBold(True)
        heading.setFont(heading_font)
        root.addWidget(heading)
        intro = QLabel(
            "Profiles define where SPR-KKR runs and how executables, MPI and remote workspaces are configured.",
            self,
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        left = QWidget(splitter)
        left.setMinimumWidth(230)
        left.setMaximumWidth(330)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(8)
        list_heading = QLabel("Profiles", left)
        list_font = list_heading.font()
        list_font.setBold(True)
        list_heading.setFont(list_font)
        left_layout.addWidget(list_heading)
        self.list = QListWidget(left)
        self.list.setAlternatingRowColors(True)
        self.list.currentItemChanged.connect(self._selection_changed)
        left_layout.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.add_button = QPushButton("New…", left)
        self.delete_button = QPushButton("Delete", left)
        self.add_button.clicked.connect(self._add_profile)
        self.delete_button.clicked.connect(self._delete_profile)
        row.addWidget(self.add_button)
        row.addWidget(self.delete_button)
        left_layout.addLayout(row)
        splitter.addWidget(left)

        self.form = _ProfileForm(splitter)
        splitter.addWidget(self.form)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 700])

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._reload_list()

    def _store_current(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        name = str(item.data(Qt.ItemDataRole.UserRole))
        draft = self._drafts[name]
        if not draft.read_only:
            draft.values = self.form.values()

    def _reload_list(self, select: str | None = None) -> None:
        current = select
        if current is None and self.list.currentItem() is not None:
            current = str(self.list.currentItem().data(Qt.ItemDataRole.UserRole))
        self.list.blockSignals(True)
        self.list.clear()
        for name in sorted(self._drafts):
            draft = self._drafts[name]
            kind = _kind_label(_draft_kind(draft.values))
            suffix = " · read-only" if draft.read_only else ""
            item = QListWidgetItem(f"{name}\n{kind}{suffix}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.list.addItem(item)
            if name == current:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        else:
            self._selection_changed(self.list.currentItem(), None)

    def _selection_changed(
        self,
        current: QListWidgetItem | None,
        previous: QListWidgetItem | None,
    ) -> None:
        if previous is not None:
            name = str(previous.data(Qt.ItemDataRole.UserRole))
            draft = self._drafts.get(name)
            if draft is not None and not draft.read_only:
                draft.values = self.form.values()
        if current is None:
            self.form.setEnabled(False)
            self.delete_button.setEnabled(False)
            return
        name = str(current.data(Qt.ItemDataRole.UserRole))
        draft = self._drafts[name]
        self.form.setEnabled(True)
        self.form.title.setText(name)
        self.form.load(draft)
        self.delete_button.setEnabled(not draft.read_only)

    def _add_profile(self) -> None:
        self._store_current()
        name, ok = QInputDialog.getText(self, "New Execution Profile", "Profile name:")
        name = name.strip()
        if not ok or not name:
            return
        if name in _RESERVED_PROFILES or name in self._drafts:
            QMessageBox.warning(
                self,
                "Profile Name",
                f"Profile {name!r} already exists or is reserved.",
            )
            return
        self._drafts[name] = _ProfileDraft(
            name,
            {"executor": "local", "mpi": "auto", "mpi_warning": True},
        )
        self._reload_list(name)

    def _delete_profile(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        name = str(item.data(Qt.ItemDataRole.UserRole))
        draft = self._drafts[name]
        if draft.read_only:
            return
        del self._drafts[name]
        self._reload_list()

    def accept(self) -> None:  # type: ignore[override]
        self._store_current()
        editable = {
            name: draft.values
            for name, draft in self._drafts.items()
            if not draft.read_only
        }
        try:
            config.profiles.set(editable)
            default_profile = config.default_profile()
            if default_profile is not None and default_profile not in self._drafts:
                config.default_profile.set(None)
            config.save_user_preferences()
        except (OSError, TypeError, ValueError) as exc:
            QMessageBox.critical(self, "Cannot Save Profiles", str(exc))
            return
        super().accept()


class ProfileSelectionDialog(QDialog):
    """Choose the execution profile for one calculation."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Run SPR-KKR Calculation")
        self.resize(650, 330)
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 16)
        layout.setSpacing(14)

        heading = QLabel("Execution profile", self)
        heading_font = heading.font()
        heading_font.setPointSize(heading_font.pointSize() + 3)
        heading_font.setBold(True)
        heading.setFont(heading_font)
        layout.addWidget(heading)
        intro = QLabel(
            "Choose where this calculation will run. The profile also controls MPI and executable selection.",
            self,
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        profile_box = QGroupBox("Run configuration", self)
        profile_layout = QVBoxLayout(profile_box)
        select_row = QHBoxLayout()
        self.profiles = QComboBox(profile_box)
        self.profiles.setMinimumContentsLength(24)
        self.profiles.currentIndexChanged.connect(self._update_description)
        select_row.addWidget(self.profiles, 1)
        self.edit_profiles_button = QPushButton("Manage Profiles…", profile_box)
        self.edit_profiles_button.clicked.connect(self._edit_profiles)
        select_row.addWidget(self.edit_profiles_button)
        profile_layout.addLayout(select_row)
        self.description = QLabel(profile_box)
        self.description.setWordWrap(True)
        self.description.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        profile_layout.addWidget(self.description)
        layout.addWidget(profile_box)
        layout.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._reload_profiles()

    def _reload_profiles(self, selected: str | None = None) -> None:
        if selected is None and self.profiles.count():
            selected = self.profiles.currentData()
        self.profiles.clear()
        names = tuple(str(name) for name in config.profiles)
        if not names:
            self.profiles.addItem("Automatic / built-in", None)
        else:
            for name in names:
                self.profiles.addItem(name, name)
        default = config.profiles.resolve_name(None)
        wanted = selected if selected in names else default
        index = self.profiles.findData(wanted)
        self.profiles.setCurrentIndex(max(index, 0))
        self._update_description()

    def _update_description(self) -> None:
        try:
            text = profile_description(self.profiles.currentData())
        except (KeyError, TypeError, ValueError) as exc:
            text = f"Profile cannot be resolved: {exc}"
        self.description.setText(text)

    def _edit_profiles(self) -> None:
        selected = self.profiles.currentData()
        if ProfilesDialog(self).exec() == QDialog.DialogCode.Accepted:
            self._reload_profiles(selected)

    def profile_name(self) -> str | None:
        value = self.profiles.currentData()
        return None if value is None else str(value)


def select_execution_profile(parent: QWidget | None = None) -> str | None:
    """Return the selected profile name, or ``None`` if cancelled/automatic."""
    dialog = ProfileSelectionDialog(parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.profile_name()
