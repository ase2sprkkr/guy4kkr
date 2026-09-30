"""Transactional editing state for the guided input-parameter dialog."""
from __future__ import annotations

from collections.abc import Callable, Iterable, MutableMapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol, TypeAlias

import numpy as np
from ase2sprkkr.input_parameters.input_parameters import InputParameters
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QUndoCommand, QUndoStack

from guy4ase.gui.input_parameters.bindings import (
    InputParameterPath,
    resolve_option,
    values_equal,
)

DormantKey: TypeAlias = tuple[InputParameterPath, int]
DormantState: TypeAlias = MutableMapping[DormantKey, Any]


class SessionTransactionPlugin(Protocol):
    """Adjust a candidate and its non-serialized editing state atomically."""

    def apply(
        self,
        before_parameters: InputParameters,
        candidate_parameters: InputParameters,
        dormant: DormantState,
    ) -> None: ...


@dataclass(frozen=True)
class _SessionSnapshot:
    """The complete state restored by one undo/redo operation."""

    parameters: InputParameters
    dormant: dict[DormantKey, Any]


def _parameters_equal(left: InputParameters, right: InputParameters) -> bool:
    """Compare effective editable values, excluding derived/generated options."""
    if left.task_name.upper() != right.task_name.upper():
        return False
    # Generated getters are deliberately excluded.  The non-generated effective
    # values are the editable state; generated values are reconstructed by
    # ase2sprkkr from that state.
    left_values = left.as_dict(only_changed=False, generated=False, copy=True)
    right_values = right.as_dict(only_changed=False, generated=False, copy=True)
    return values_equal(left_values, right_values)


def _changed_values(before: InputParameters, after: InputParameters) -> dict:
    """Keep option values intact, including arrays and per-type dictionaries."""
    left = before.as_dict(only_changed=False, generated=False, copy=True)
    right = after.as_dict(only_changed=False, generated=False, copy=True)
    changes = {}
    for section in dict.fromkeys((*left, *right)):
        old, new = left.get(section, {}), right.get(section, {})
        for name in dict.fromkeys((*old, *new)):
            a, b = old.get(name), new.get(name)
            if not values_equal(a, b):
                changes[(section, name)] = (a, b)
    return changes


def _history_value(value: Any) -> str:
    if value is None:
        return "Not set"
    if isinstance(value, np.ndarray):
        value = value.tolist()
    text = str(value)
    return text if len(text) <= 120 else text[:117] + "…"


class _ReplaceParametersCommand(QUndoCommand):
    def __init__(
        self,
        session: "InputParametersSession",
        before: _SessionSnapshot,
        after: _SessionSnapshot,
        *,
        text: str,
        source_page: str | None,
        path: InputParameterPath | None,
        field_index: int | None,
    ) -> None:
        super().__init__(text)
        self._session = session
        self._before = before
        self._after = after
        self.source_page = source_page
        self.path = path
        self.field_index = field_index
        self.changes = _changed_values(before.parameters, after.parameters)
        self._first_redo = True

    def description(self, *, undo: bool) -> str:
        lines = [("Undo: " if undo else "Redo: ") + self.text()]
        for path, (before, after) in list(self.changes.items())[:6]:
            name = ".".join(path)
            if path == self.path and self.field_index is not None:
                index = self.field_index
                before = before[index] if before is not None and len(before) > index else None
                after = after[index] if after is not None and len(after) > index else None
                name += f"[{index + 1}]"
            source, target = (after, before) if undo else (before, after)
            lines.append(f"{name}: {_history_value(source)} → {_history_value(target)}")
        if len(self.changes) > 6:
            lines.append(f"… and {len(self.changes) - 6} more parameters")
        return "\n".join(lines)

    def _notify_navigation(self) -> None:
        """Request navigation to the source field and first changed array element."""
        paths = tuple(dict.fromkeys(((self.path,) if self.path else ()) + tuple(self.changes)))
        indices = {}
        for path, (before, after) in self.changes.items():
            if isinstance(before, (list, tuple, np.ndarray)) and isinstance(after, (list, tuple, np.ndarray)):
                for index in range(max(len(before), len(after))):
                    if (index >= len(before) or index >= len(after)
                            or not values_equal(before[index], after[index])):
                        indices[path] = index
                        break
        if self.path is not None and self.field_index is not None:
            indices[self.path] = self.field_index
        self._session.historyApplied.emit(paths, self.source_page, indices)

    def undo(self) -> None:
        self._session._install(self._before, self.path, reset=True)
        self._notify_navigation()

    def redo(self) -> None:
        self._session._install(
            self._after,
            self.path,
            reset=not self._first_redo or self.path is None,
        )
        # QUndoStack.push() calls redo too. Ordinary edits must not navigate.
        if not self._first_redo:
            self._notify_navigation()
        self._first_redo = False


class InputParametersSession(QObject):
    """Own an isolated working copy and its undo/redo history."""

    valueChanged = pyqtSignal(object)
    parametersReplaced = pyqtSignal()
    editApplied = pyqtSignal(object, bool)  # changed paths, discard all drafts
    modifiedChanged = pyqtSignal(bool)
    historyApplied = pyqtSignal(object, object, object)

    def __init__(
        self,
        parameters: InputParameters,
        parent: QObject | None = None,
        *,
        plugins: Iterable[SessionTransactionPlugin] = (),
    ) -> None:
        super().__init__(parent)
        self._initial = parameters.copy(copy_values=True)
        self._working = parameters.copy(copy_values=True)
        self._plugins = tuple(plugins)
        # Non-serialized field values belong to editing state. Commands retain
        # them with the parameter snapshot, including across history branches.
        self._dormant: dict[DormantKey, Any] = {}
        self._modified = False
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setUndoLimit(100)

    @property
    def initial_parameters(self) -> InputParameters:
        """Return the baseline object; callers must treat it as read-only."""
        return self._initial

    @property
    def working_parameters(self) -> InputParameters:
        """Return the live snapshot; write through session methods, never directly.

        Undo commands retain this object, so mutating it would also alter history.
        """
        return self._working

    def result(self) -> InputParameters:
        """Return a detached copy safe for callers or a nested editor to modify."""
        return self._working.copy(copy_values=True)

    def option(self, path: InputParameterPath) -> Any:
        return resolve_option(self._working, path)

    def value(self, path: InputParameterPath) -> Any:
        """Read the complete option, including global and per-type overrides."""
        return self.option(path)(all_values=True)

    def display_value(self, path: InputParameterPath, index: int | None = None) -> Any:
        """Return an active component or its non-serialized displayed value."""
        value = self.value(path)
        if index is None:
            return value
        try:
            if value is not None and len(value) > index:
                return value[index]
        except (TypeError, IndexError):
            pass
        return self._dormant.get((path, index))

    def history_description(self, *, undo: bool) -> str:
        """Describe the next history command, with old/new values for its tooltip."""
        stack = self.undo_stack
        available = stack.canUndo() if undo else stack.canRedo()
        if not available:
            return "Nothing to undo" if undo else "Nothing to redo"
        command = stack.command(stack.index() - 1 if undo else stack.index())
        return command.description(undo=undo)

    def is_changed(self, path: InputParameterPath) -> bool:
        left = resolve_option(self._initial, path)(all_values=True)
        current = resolve_option(self._working, path)
        right = current(all_values=True)
        try:
            return not current._definition.type.is_the_same_value(right, left)
        except Exception:
            return not values_equal(left, right)

    def changed_paths(self, paths: Iterable[InputParameterPath]) -> set[InputParameterPath]:
        return {path for path in paths if self.is_changed(path)}

    def is_modified(self) -> bool:
        return not _parameters_equal(self._initial, self._working)

    def set_value(
        self,
        path: InputParameterPath,
        value: Any,
        *,
        source_page: str | None = None,
        text: str | None = None,
    ) -> bool:
        return self.mutate(
            lambda candidate: resolve_option(candidate, path).set(value),
            text=text or f"Change {'.'.join(path)}",
            source_page=source_page,
            path=path,
        )

    def mutate(
        self,
        callback: Callable[[InputParameters], Any],
        *,
        text: str,
        source_page: str | None = None,
        path: InputParameterPath | None = None,
        field_index: int | None = None,
    ) -> bool:
        """Apply a compound edit to a copy and record it as one command.

        The callback may update several dependent options. Exceptions propagate
        without installing the candidate; an unchanged candidate adds no command.
        Return whether a command was added. Page/path/index identify the field
        to reveal on undo or redo, not a separate store of parameter values.
        """
        candidate = self._working.copy(copy_values=True)
        callback(candidate)
        return self._push(candidate, text=text, source_page=source_page, path=path, field_index=field_index)

    def replace_parameters(
        self,
        parameters: InputParameters,
        *,
        text: str = "Replace input parameters",
        source_page: str | None = None,
    ) -> bool:
        """Copy same-task input into one undoable edit; reject a different task."""
        if parameters.task_name.upper() != self._working.task_name.upper():
            raise ValueError(
                f"Expected {self._working.task_name.upper()} input parameters, "
                f"got {parameters.task_name.upper()}."
            )
        candidate = parameters.copy(copy_values=True)
        return self._push(candidate, text=text, source_page=source_page, path=None)

    def _push(
        self,
        candidate: InputParameters,
        *,
        text: str,
        source_page: str | None,
        path: InputParameterPath | None,
        field_index: int | None = None,
    ) -> bool:
        dormant = deepcopy(self._dormant)
        for plugin in self._plugins:
            plugin.apply(self._working, candidate, dormant)
        if (
            _parameters_equal(candidate, self._working)
            and values_equal(dormant, self._dormant)
        ):
            return False
        before = _SessionSnapshot(self._working, deepcopy(self._dormant))
        after = _SessionSnapshot(candidate, deepcopy(dormant))
        command = _ReplaceParametersCommand(
            self,
            before,
            after,
            text=text,
            source_page=source_page,
            path=path,
            field_index=field_index,
        )
        self.undo_stack.push(command)
        return True

    def _install(
        self,
        snapshot: _SessionSnapshot,
        path: InputParameterPath | None,
        *,
        reset: bool = False,
    ) -> None:
        """Install an immutable-by-convention snapshot and notify all editors."""
        # Snapshots placed on the undo stack are never mutated: every user edit
        # starts from a fresh copy.  Reusing the snapshot here is therefore safe.
        changes = tuple(_changed_values(self._working, snapshot.parameters))
        self._working = snapshot.parameters
        self._dormant = snapshot.dormant
        self.editApplied.emit(changes, reset)
        if path is not None:
            self.valueChanged.emit(path)
        self.parametersReplaced.emit()
        modified = self.is_modified()
        if modified != self._modified:
            self._modified = modified
            self.modifiedChanged.emit(modified)
