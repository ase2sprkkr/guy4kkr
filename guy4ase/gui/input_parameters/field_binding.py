"""Qt-independent binding of one guided field placement to its session."""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from typing import Any

from guy4ase.gui.input_parameters.bindings import (
    InputParametersBinding,
    InputParameterPath,
    resolve_option,
)

_MISSING = object()


@dataclass(frozen=True)
class FieldValue:
    """Value and default metadata needed by a visual value editor."""

    value: Any
    default: Any = None
    implicit_default: bool = False
    explicit: bool | None = None


def _indexed(value: Any, index: int) -> Any:
    if value is None:
        return None
    try:
        return value[index] if len(value) > index else None
    except (TypeError, IndexError):
        return None


class SessionFieldBinding:
    """Map one FieldPlacement to session reads, defaults and atomic writes."""

    def __init__(self, session: Any, placement: Any, page_id: str) -> None:
        self.session = session
        self.placement = placement
        self.page_id = page_id
        self.path: InputParameterPath = placement.path
        self.read_only = False
        self.allow_empty = False

    @property
    def option(self) -> Any:
        return self.session.option(self.path)

    @property
    def parameters(self) -> Any:
        return self.session.working_parameters

    @property
    def allows_unset(self) -> bool:
        return True

    @property
    def value_type(self) -> Any:
        return self.option._definition.type

    def read(self) -> FieldValue:
        """Return the field value to display without mutating session state."""
        option = self.option
        complete_value = self.session.value(self.path)
        return FieldValue(
            complete_value,
            option.default_value,
            implicit_default=not option.is_set() and complete_value is not None,
            explicit=option.is_set(),
        )

    def set_value(self, value: Any) -> None:
        """Commit the complete option value as one session edit."""
        def update(parameters):
            resolve_option(parameters, self.path).set(value)

        self.session.mutate(
            update,
            source_page=self.page_id,
            path=self.path,
            text=f"Change {self.placement.label.rstrip(':')}",
        )

    def option_at(self, path: InputParameterPath) -> Any:
        return self.session.option(path)

    def value_at(self, path: InputParameterPath) -> Any:
        return self.session.value(path)

    def set_path_value(self, path: InputParameterPath, value: Any, *, text: str) -> Any:
        return self.session.set_value(
            path,
            value,
            source_page=self.page_id,
            text=text,
        )

    def mutate(
        self,
        callback: Callable[[Any], Any],
        *,
        text: str,
        path: InputParameterPath | None = None,
        field_index: int | None = None,
    ) -> Any:
        return self.session.mutate(
            callback,
            source_page=self.page_id,
            path=path or self.path,
            field_index=field_index,
            text=text,
        )


class IndexedFieldBinding(SessionFieldBinding):
    """Expose one explicitly declared component of an array-valued option."""

    @property
    def index(self) -> int:
        return self.placement.index

    @property
    def value_type(self) -> Any:
        return self.option._definition.type.type

    def read(self) -> FieldValue:
        option = self.option
        complete_value = self.session.value(self.path)
        return FieldValue(
            self.session.display_value(self.path, self.index),
            _indexed(option.default_value, self.index),
            implicit_default=not option.is_set() and complete_value is not None,
            explicit=option.is_set(),
        )

    def set_value(self, value: Any) -> None:
        index = self.index

        def update(parameters):
            option = resolve_option(parameters, self.path)
            values = list(option())
            while len(values) <= index:
                values.append(values[0] if values else value)
            values[index] = value
            option.set(values)

        self.session.mutate(
            update,
            source_page=self.page_id,
            path=self.path,
            field_index=index,
            text=f"Change {self.placement.label.rstrip(':')}",
        )


class DirectFieldBinding:
    """Bind an expert-tree field directly to its isolated parameter document."""

    def __init__(
        self,
        model: InputParametersBinding,
        placement: Any,
        *,
        read_value: Callable[[], Any] | None = None,
        apply_value: Callable[[Any], None] | None = None,
        value_type: Any = None,
        allows_unset: bool | None = None,
        read_only: bool = False,
        allow_empty: bool = False,
        cache_applied: bool = True,
    ) -> None:
        self.model = model
        self.placement = placement
        self.path: InputParameterPath = placement.path
        self._read_value = read_value
        self._apply_value = apply_value
        self._value_type = value_type
        self._allows_unset = allows_unset
        self.read_only = read_only
        self.allow_empty = allow_empty
        self._cache_applied = cache_applied
        self._last_applied = _MISSING

    @property
    def parameters(self) -> Any:
        return self.model.parameters

    @property
    def option(self) -> Any:
        return self.model.option(self.path)

    @property
    def value_type(self) -> Any:
        return (
            self._value_type
            if self._value_type is not None
            else self.option._definition.type
        )

    @property
    def allows_unset(self) -> bool:
        if self._allows_unset is not None:
            return self._allows_unset
        optional = self.option._definition.is_optional
        return bool(
            optional(self.option) if callable(optional) else optional
        ) or self.option.default_value is not None

    def read(self) -> FieldValue:
        if self._last_applied is not _MISSING:
            value = self._last_applied
        elif self._read_value is not None:
            value = self._read_value()
            if isinstance(value, FieldValue):
                return value
        else:
            value = self.model.value(self.path)
        option = self.option
        return FieldValue(
            value,
            option.default_value,
            implicit_default=not option.is_set() and value is not None,
            explicit=option.is_set(),
        )

    def set_value(self, value: Any) -> Any:
        if self._apply_value is not None:
            result = self._apply_value(value)
            self._last_applied = value if self._cache_applied else _MISSING
            return result
        return self.model.set_value(self.path, value)

    def option_at(self, path: InputParameterPath) -> Any:
        return self.model.option(path)

    def value_at(self, path: InputParameterPath) -> Any:
        return self.model.value(path)

    def set_path_value(self, path: InputParameterPath, value: Any, *, text: str) -> Any:
        del text
        return self.model.set_value(path, value)

    def mutate(
        self,
        callback: Callable[[Any], Any],
        *,
        text: str,
        path: InputParameterPath | None = None,
        field_index: int | None = None,
    ) -> Any:
        del text, field_index
        return self.model.mutate(callback, path=path or self.path)


def create_field_binding(
    session: Any,
    placement: Any,
    page_id: str,
) -> SessionFieldBinding:
    """Create the narrow binding required by one field placement."""
    binding_type = (
        IndexedFieldBinding
        if placement.index is not None
        else SessionFieldBinding
    )
    return binding_type(session, placement, page_id)
