"""Registry for task-specific value editors kept outside the generic adapter."""
from __future__ import annotations

from .bsf import EDITORS as BSF_EDITORS
from .common import EDITORS as COMMON_EDITORS
from .value_editor import ParameterValueEditorWidget

EDITOR_FACTORIES = {
    **COMMON_EDITORS,
    **BSF_EDITORS,
}


def create_registered_editor(
    name,
    session,
    placement,
    page_id,
    *,
    atoms=None,
    parent=None,
) -> ParameterValueEditorWidget:
    """Instantiate a task-specific editor implementing the shared contract."""
    try:
        factory = EDITOR_FACTORIES[name]
    except KeyError as exc:
        raise ValueError(f"Unknown registered input editor {name!r}") from exc
    editor = factory(session, placement, page_id, atoms=atoms, parent=parent)
    if not isinstance(editor, ParameterValueEditorWidget):
        raise TypeError(
            f"Registered editor {name!r} must inherit ParameterValueEditorWidget"
        )
    return editor
