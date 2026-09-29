"""Qt-independent binding of one guided field placement to its session."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from guy4ase.gui.input_parameters.bindings import (
    InputParameterPath,
    resolve_option,
)


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

    @property
    def option(self) -> Any:
        return self.session.option(self.path)

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
