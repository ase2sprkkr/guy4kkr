"""Registry for compound field editors kept outside the generic adapter."""
from __future__ import annotations

from .bsf import EDITORS as BSF_EDITORS
from .common import EDITORS as COMMON_EDITORS
from .compound import CompoundParameterEditor

EDITOR_FACTORIES = {
    **COMMON_EDITORS,
    **BSF_EDITORS,
}


def create_compound_editor(
    name,
    session,
    placement,
    page_id,
    *,
    atoms=None,
    parent=None,
) -> CompoundParameterEditor:
    """Instantiate a registered editor implementing the explicit contract."""
    try:
        factory = EDITOR_FACTORIES[name]
    except KeyError as exc:
        raise ValueError(f"Unknown compound input editor {name!r}") from exc
    editor = factory(session, placement, page_id, atoms=atoms, parent=parent)
    if not isinstance(editor, CompoundParameterEditor):
        raise TypeError(
            f"Compound editor {name!r} must inherit CompoundParameterEditor"
        )
    return editor
