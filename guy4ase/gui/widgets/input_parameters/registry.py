"""Registry for compound field editors kept outside the generic adapter."""
from __future__ import annotations

from PyQt6.QtWidgets import QWidget

from .bsf import EDITORS as BSF_EDITORS
from .common import EDITORS as COMMON_EDITORS

EDITOR_FACTORIES = {
    **COMMON_EDITORS,
    **BSF_EDITORS,
}


def create_compound_editor(name, session, placement, page_id, *, atoms=None, parent=None) -> QWidget:
    """Instantiate a registered editor and verify its small lifecycle API."""
    try:
        factory = EDITOR_FACTORIES[name]
    except KeyError as exc:
        raise ValueError(f"Unknown compound input editor {name!r}") from exc
    editor = factory(session, placement, page_id, atoms=atoms, parent=parent)
    missing = [method for method in ("refresh", "commit", "focus_for_history")
               if not callable(getattr(editor, method, None))]
    if not hasattr(editor, "validationChanged"):
        missing.append("validationChanged signal")
    if missing:
        raise TypeError(f"Compound editor {name!r} lacks: {', '.join(missing)}")
    return editor
