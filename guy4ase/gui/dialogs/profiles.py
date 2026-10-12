"""Execution-profile selection and editing for SPR-KKR calculations."""
from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Any

from ase2sprkkr.configuration import config
from ase2sprkkr.sprkkr.profile import resolve_sprkkr_profile
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QInputDialog,
)


_RESERVED_PROFILES = frozenset(("ase", "legacy"))
_SYNC_POLICIES = ("changed", "always", "missing", "never")


def _option_value(profile: Any, name: str) -> Any:
    value = getattr(profile, name, None)
    return value() if callable(value) else value


def _profile_values(profile: Any) -> dict[str, Any]:
    values = profile.as_dict(only_changed="explicit", generated=False) or {}
    values.pop("command", None)
    return dict(values)


def _runtime_profile(name: str | None):
    return resolve_sprkkr_profile(name)


def _mpi_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (tuple, list)):
        return shlex.join(str(item) for item in value)
    return str(value)


def _parse_mpi(text: str) -> Any:
    text = text.strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in {"false", "off", "no"}:
        return False
    if lowered in {"true", "on", "yes"}:
        return True
    if lowered == "auto":
        return "auto"
    try:
        return int(text)
    except ValueError:
        return shlex.split(text)


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
    if mpi is False or mpi is None:
        mpi_text = "MPI disabled"
    elif mpi is True:
        mpi_text = "MPI enabled"
    elif mpi == "auto":
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


class _ProfileForm(QWidget):
    """Edit one mutable profile; backend-specific fields follow its type."""

    _KINDS = (
        ("local", "Local"),
        ("ssh", "SSH"),
        ("psij", "PSI/J"),
        ("ssh-psij", "SSH + PSI/J"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        self.read_only_note = QLabel(
            "This profile is provided by another configuration source and is read-only."
        )
        self.read_only_note.setWordWrap(True)
        root.addWidget(self.read_only_note)

        self.form_widget = QWidget(self)
        form = QFormLayout(self.form_widget)
        self.kind = QComboBox(self.form_widget)
        for value, label in self._KINDS:
            self.kind.addItem(label, value)
        self.kind.currentIndexChanged.connect(self._update_visibility)
        form.addRow("Execution:", self.kind)

        self.mpi = QLineEdit(self.form_widget)
        self.mpi.setPlaceholderText("false, true, auto, number, or command")
        form.addRow("MPI:", self.mpi)
        self.executable_dir = QLineEdit(self.form_widget)
        form.addRow("Executable directory:", self.executable_dir)
        self.executable_suffix = QLineEdit(self.form_widget)
        form.addRow("Executable suffix:", self.executable_suffix)

        self.host = QLineEdit(self.form_widget)
        form.addRow("SSH host:", self.host)
        self.local_root = QLineEdit(self.form_widget)
        form.addRow("Local root:", self.local_root)
        self.remote_root = QLineEdit(self.form_widget)
        form.addRow("Remote root:", self.remote_root)
        self.ssh_options = QLineEdit(self.form_widget)
        self.ssh_options.setPlaceholderText("e.g. -p 2222")
        form.addRow("SSH options:", self.ssh_options)
        self.remote_command = QLineEdit(self.form_widget)
        self.remote_command.setPlaceholderText("ase2sprkkr remote")
        form.addRow("Remote command:", self.remote_command)

        self.input_sync = QComboBox(self.form_widget)
        self.output_sync = QComboBox(self.form_widget)
        for policy in _SYNC_POLICIES:
            self.input_sync.addItem(policy)
            self.output_sync.addItem(policy)
        form.addRow("Input sync:", self.input_sync)
        form.addRow("Output sync:", self.output_sync)

        self.psij_backend = QLineEdit(self.form_widget)
        self.psij_backend.setPlaceholderText("slurm")
        form.addRow("PSI/J backend:", self.psij_backend)
        self.psij_url = QLineEdit(self.form_widget)
        form.addRow("PSI/J URL:", self.psij_url)
        root.addWidget(self.form_widget)
        root.addStretch(1)
        self._update_visibility()

    def _set_row_visible(self, widget: QWidget, visible: bool) -> None:
        widget.setVisible(visible)
        label = self.form_widget.layout().labelForField(widget)
        if label is not None:
            label.setVisible(visible)

    def _update_visibility(self) -> None:
        kind = self.kind.currentData()
        ssh = kind in {"ssh", "ssh-psij"}
        psij = kind in {"psij", "ssh-psij"}
        for widget in (
            self.host,
            self.local_root,
            self.remote_root,
            self.ssh_options,
            self.remote_command,
            self.input_sync,
            self.output_sync,
        ):
            self._set_row_visible(widget, ssh)
        self._set_row_visible(self.psij_backend, psij)
        self._set_row_visible(self.psij_url, psij)

    def load(self, draft: _ProfileDraft) -> None:
        values = draft.values
        executor = values.get("executor") or "local"
        kind = executor
        if executor == "ssh" and (
            values.get("psij_backend") is not None
            or values.get("psij_url") is not None
        ):
            kind = "ssh-psij"
        index = self.kind.findData(kind)
        self.kind.setCurrentIndex(max(index, 0))
        self.mpi.setText(_mpi_text(values.get("mpi")))
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
        values: dict[str, Any] = {"executor": executor}
        mpi = _parse_mpi(self.mpi.text())
        if mpi is not None:
            values["mpi"] = mpi
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
        self.resize(850, 560)
        self._drafts: dict[str, _ProfileDraft] = {}
        for name, profile in config.profiles.items():
            self._drafts[str(name)] = _ProfileDraft(
                str(name),
                _profile_values(profile),
                bool(getattr(profile, "read_only", False)) or name in _RESERVED_PROFILES,
            )

        root = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        root.addWidget(splitter, 1)

        left = QWidget(splitter)
        left_layout = QVBoxLayout(left)
        self.list = QListWidget(left)
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

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
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
            label = name + ("  [read-only]" if draft.read_only else "")
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.list.addItem(item)
            if name == current:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        else:
            self._selection_changed(self.list.currentItem(), None)

    def _selection_changed(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
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
        self.form.load(draft)
        self.delete_button.setEnabled(not draft.read_only)

    def _add_profile(self) -> None:
        self._store_current()
        name, ok = QInputDialog.getText(self, "New Execution Profile", "Profile name:")
        name = name.strip()
        if not ok or not name:
            return
        if name in _RESERVED_PROFILES or name in self._drafts:
            QMessageBox.warning(self, "Profile Name", f"Profile {name!r} already exists or is reserved.")
            return
        self._drafts[name] = _ProfileDraft(name, {"executor": "local"})
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
        self.resize(560, 230)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.profiles = QComboBox(self)
        self.profiles.currentIndexChanged.connect(self._update_description)
        form.addRow("Execution profile:", self.profiles)
        layout.addLayout(form)
        self.description = QLabel(self)
        self.description.setWordWrap(True)
        layout.addWidget(self.description)
        edit = QPushButton("Edit Profiles…", self)
        edit.clicked.connect(self._edit_profiles)
        layout.addWidget(edit, 0, Qt.AlignmentFlag.AlignLeft)
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
