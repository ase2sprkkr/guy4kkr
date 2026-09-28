"""Qt-independent declarations of fields, groups and wizard pages."""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from guy4ase.gui.input_parameters.bindings import InputParameterPath


class FieldRole(Enum):
    """Distinguish a field's main location from a Quick setup view of that field."""
    PRIMARY = "primary"
    MIRROR = "mirror"


@dataclass(frozen=True)
class Choice:
    label: str
    value: Any


@dataclass(frozen=True)
class FieldPlacement:
    """Describe a view of an option, not an additional stored parameter value.

    ``index`` selects one array element; ``related_paths`` belong to the same
    composite editor. Defaults come exclusively from InputParameters and are
    shown as placeholders, not duplicated in layout specifications.
    """
    path: InputParameterPath
    label: str
    kind: str = "auto"
    role: FieldRole = FieldRole.PRIMARY
    minimum: float | int | None = None
    maximum: float | int | None = None
    step: float | int | None = None
    decimals: int = 6
    choices: tuple[Choice, ...] = ()
    special_value_text: str | None = None
    nullable: bool = False
    index: int | None = None
    descriptions: bool = False
    related_paths: tuple[InputParameterPath, ...] = ()

    @property
    def paths(self):
        return (self.path,) + self.related_paths


@dataclass(frozen=True)
class GroupSpec:
    """Group fields on a page; ``special`` selects dialog-specific group behavior."""
    title: str
    fields: tuple[FieldPlacement, ...]
    special: str | None = None
    collapsed: bool = False
    note: str | None = None
    id: str | None = None


@dataclass(frozen=True)
class PageSpec:
    id: str
    title: str
    groups: tuple[GroupSpec, ...]
    color: str
    quick: bool = False


@dataclass(frozen=True)
class TaskDialogSpec:
    task: str
    parameter_task: str
    title: str
    pages: tuple[PageSpec, ...]

    def primary_pages(self) -> dict[InputParameterPath, str]:
        """Map paths to their owning page, validating primary/mirror placements.

        Different array indices may share a page. Quick setup mirrors must have
        a primary placement; related paths also belong to their composite field.
        """
        result: dict[InputParameterPath, str] = {}
        mirrors: set[InputParameterPath] = set()
        placements: set[tuple[InputParameterPath, int | None]] = set()
        for page in self.pages:
            for group in page.groups:
                for field in group.fields:
                    if field.role is FieldRole.MIRROR:
                        if not page.quick:
                            raise ValueError(
                                f"Mirror {'.'.join(field.path)} is only allowed on Quick setup."
                            )
                        mirrors.add(field.path)
                    elif ((field.path, field.index) in placements
                          or (field.path in result and result[field.path] != page.id)):
                        raise ValueError(f"Duplicate primary field {'.'.join(field.path)}")
                    else:
                        for path in field.paths:
                            if path in result and path != field.path:
                                raise ValueError(f"Duplicate primary field {'.'.join(path)}")
                            result[path] = page.id
                            placements.add((path, field.index))
        missing = mirrors - result.keys()
        if missing:
            names = ", ".join(".".join(path) for path in sorted(missing))
            raise ValueError(f"Mirrored fields have no primary placement: {names}")
        return result

    def all_paths(self) -> tuple[InputParameterPath, ...]:
        return tuple(dict.fromkeys(
            path
            for page in self.pages
            for group in page.groups
            for field in group.fields
            for path in field.paths
        ))


def field(section: str, option: str, label: str, kind: str = "auto", **kwargs: Any) -> FieldPlacement:
    """Declare one view of an input-parameter option."""
    return FieldPlacement((section, option), label, kind, **kwargs)


def main_energy_mesh_field(option: str, label: str, kind: str = "auto", **kwargs: Any) -> FieldPlacement:
    """Declare the main (index-zero) component of ``ENERGY.GRID`` or ``NE``."""
    if option not in {"GRID", "NE"}:
        raise ValueError(f"{option} is not an energy-mesh option")
    return field("ENERGY", option, label, kind, index=0, **kwargs)


def mirror(value: FieldPlacement) -> FieldPlacement:
    return replace(value, role=FieldRole.MIRROR)


def energy_bound(name: str, label: str) -> FieldPlacement:
    return field("ENERGY", name, label, "energy_bound", related_paths=(("ENERGY", name + "EV"),))
