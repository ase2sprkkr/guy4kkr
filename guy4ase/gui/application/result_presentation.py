"""Qt-independent presentation models for calculation results."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from guy4ase.gui.application.result_action_policy import (
    ResultActionAvailability,
    result_action_availability,
)
from guy4ase.gui.application.result_artifacts import resolve_result_value
from guy4ase.gui.application.result_history import ResultHistory, ResultRecord

logger = logging.getLogger(__name__)

_TASK_LABELS = {
    "empty_spheres": "Empty spheres",
}


@dataclass(frozen=True)
class ResultValuePresentation:
    value: Any | None
    name: str
    info: str
    summary: str
    actions: tuple[str, ...] = ()
    warning: str | None = None
    show_in_summary: bool = False
    always_visible: bool = False


@dataclass(frozen=True)
class ResultPresentation:
    result_id: int | None
    values: tuple[ResultValuePresentation, ...] = ()
    file_warning: str | None = None
    actions: ResultActionAvailability = field(default_factory=ResultActionAvailability)


@dataclass(frozen=True)
class ResultTreeNode:
    label: str
    result_id: int | None = None
    children: tuple["ResultTreeNode", ...] = ()


@dataclass(frozen=True)
class ResultTreeModel:
    roots: tuple[ResultTreeNode, ...] = ()
    selected_result_id: int | None = None
    selected: ResultPresentation | None = None


@dataclass
class _MutableTreeNode:
    label: str
    result_id: int | None = None
    children: list["_MutableTreeNode"] = field(default_factory=list)

    def freeze(self) -> ResultTreeNode:
        return ResultTreeNode(
            self.label,
            self.result_id,
            tuple(child.freeze() for child in self.children),
        )


def _result_label(record: ResultRecord) -> str:
    result = record.result
    task = _TASK_LABELS.get(record.task_name, record.task_name.upper())
    try:
        output = getattr(result, "output_file", None)
        output_name = Path(str(output)).name if output else ""
    except Exception:  # noqa: BLE001 - optional presentation metadata
        output_name = ""
    return " — ".join(part for part in (task, output_name) if part)


def _error_value(name: str, exc: Exception | None = None) -> ResultValuePresentation:
    detail = f": {exc}" if exc else ""
    return ResultValuePresentation(
        value=None,
        name=f"{name} ⚠",
        info="",
        summary="Unavailable",
        warning=f"Could not display this output{detail}",
        always_visible=True,
    )


def _present_value(
    key: str,
    value: Any,
    *,
    warning: str | None = None,
    disable_actions: bool = False,
) -> ResultValuePresentation:
    try:
        fallback_name = getattr(value, "name", key)
        name = str(getattr(value, "display_name", fallback_name))
        raw_info = getattr(value, "info", "")
        info = str(raw_info) if raw_info else ""
        summary = str(value.value_label())
        show_in_summary = bool(getattr(value, "show_in_summary", False))
    except Exception as exc:
        logger.exception("Failed to display output value %r", key)
        return _error_value(f"{key}: unavailable", exc)

    try:
        actions = () if disable_actions else tuple(str(action) for action in value.actions())
    except Exception as exc:
        logger.exception("Failed to load actions for output value %r", key)
        action_warning = f"Actions could not be loaded: {exc}"
        return ResultValuePresentation(
            value=value,
            name=name,
            info=info,
            summary=summary,
            actions=(),
            warning="\n\n".join(part for part in (warning, action_warning) if part),
            show_in_summary=show_in_summary,
            always_visible=True,
        )

    if warning:
        name = f"{name} ⚠"
    return ResultValuePresentation(
        value=value,
        name=name,
        info=info,
        summary=summary,
        actions=actions,
        warning=warning,
        show_in_summary=show_in_summary,
    )


def present_result(
    result: Any | None,
    *,
    result_id: int | None = None,
    record: ResultRecord | None = None,
    history: ResultHistory | None = None,
    actions: ResultActionAvailability | None = None,
) -> ResultPresentation | None:
    if result is None:
        return None

    try:
        items = list(result.output_values.items())
    except Exception as exc:
        logger.exception("Failed to load result output values")
        return ResultPresentation(
            result_id=result_id,
            values=(_error_value("Output values could not be loaded", exc),),
            actions=actions or ResultActionAvailability(),
        )

    values: list[ResultValuePresentation] = []
    has_replaced_result_file = False
    has_unavailable_result_file = False
    for key, value in items:
        try:
            name = str(key)
        except Exception:
            logger.exception("Failed to read an output value name")
            name = "<unknown output>"

        resolved = resolve_result_value(history, record, name, value)
        has_replaced_result_file |= resolved.replaced
        has_unavailable_result_file |= resolved.unavailable
        values.append(
            _present_value(
                name,
                resolved.value,
                warning=resolved.warning,
                disable_actions=resolved.disable_actions,
            )
        )

    file_warning = None
    if has_replaced_result_file:
        file_warning = (
            "⚠ Historical result files were overwritten. Showing current contents "
            "where available; these are not the original data from the selected "
            "calculation."
        )
    elif has_unavailable_result_file:
        file_warning = "⚠ Some historical result files are no longer available."

    return ResultPresentation(
        result_id=result_id,
        values=tuple(values),
        file_warning=file_warning,
        actions=actions or ResultActionAvailability(),
    )


def present_result_record(
    history: ResultHistory,
    record: ResultRecord,
    *,
    current_structure_id: int | None,
    current_state_id: int | None,
) -> ResultPresentation:
    availability = result_action_availability(
        history,
        record,
        current_structure_id=current_structure_id,
        current_state_id=current_state_id,
    )
    presentation = present_result(
        record.result,
        result_id=record.id,
        record=record,
        history=history,
        actions=availability,
    )
    assert presentation is not None
    return presentation


def present_result_tree(
    history: ResultHistory,
    *,
    current_structure_id: int | None,
    current_state_id: int | None,
    selected_result_id: int | None = None,
) -> ResultTreeModel:
    """Project exact provenance into a Qt-independent selector tree."""
    ordered_records = tuple(sorted(history.results, key=lambda record: record.id))
    result_nodes: dict[int, _MutableTreeNode] = {}
    records: dict[int, ResultRecord] = {}

    imported_by_directory: dict[str | None, list[ResultRecord]] = {}
    for record in ordered_records:
        if record.imported:
            imported_by_directory.setdefault(record.directory, []).append(record)

    directory_nodes: list[_MutableTreeNode] = []
    for directory, imported in imported_by_directory.items():
        directory_node = _MutableTreeNode(directory or "(unknown directory)")
        directory_nodes.append(directory_node)
        for record in imported:
            records[record.id] = record
            node = _MutableTreeNode(_result_label(record), result_id=record.id)
            directory_node.children.append(node)
            result_nodes[record.id] = node

    roots: list[_MutableTreeNode] = []
    formula_counts: dict[str, int] = {}
    for structure in history.structures:
        structure_records = tuple(
            record
            for record in ordered_records
            if record.structure_id == structure.id and not record.imported
        )
        if not structure_records:
            continue

        structure_node = _MutableTreeNode(structure.formula)
        for record in structure_records:
            records[record.id] = record
            node = _MutableTreeNode(_result_label(record), result_id=record.id)
            result_nodes[record.id] = node

            if record.task_name in {"scf", "empty_spheres"}:
                structure_node.children.append(node)
                continue

            source = history.potential_source_result(record.input_state_id)
            parent = result_nodes.get(source.id) if source is not None else None
            (parent.children if parent is not None else structure_node.children).append(node)

        if structure_node.children:
            number = formula_counts.get(structure.formula, 0) + 1
            formula_counts[structure.formula] = number
            if number > 1:
                structure_node.label = f"{structure.formula} ({number})"
            roots.append(structure_node)

    roots.extend(directory_nodes)

    unstructured = tuple(
        record
        for record in ordered_records
        if not record.imported and record.structure_id is None
    )
    if unstructured:
        unknown = _MutableTreeNode("Unknown structure")
        roots.append(unknown)
        for record in unstructured:
            records[record.id] = record
            node = _MutableTreeNode(_result_label(record), result_id=record.id)
            unknown.children.append(node)
            result_nodes[record.id] = node

    target_id = selected_result_id if selected_result_id in records else None
    if target_id is None:
        active = history.latest_result_for_state(current_state_id)
        if active is not None and active.id in records:
            target_id = active.id
    if target_id is None and records:
        target_id = max(records)

    selected = (
        present_result_record(
            history,
            records[target_id],
            current_structure_id=current_structure_id,
            current_state_id=current_state_id,
        )
        if target_id is not None
        else None
    )
    return ResultTreeModel(
        roots=tuple(root.freeze() for root in roots),
        selected_result_id=target_id,
        selected=selected,
    )
