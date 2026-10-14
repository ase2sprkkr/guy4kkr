"""Layout-only lookup backed by the Guided task registry.

Task identity and workflow metadata are owned by :mod:`..tasks`; this module
provides the declarative-spec lookup API without maintaining another registry.
"""

from __future__ import annotations

from ..tasks import guided_task_definition


def task_dialog_spec(task: str, *, is_2d: bool = False):
    """Return the declarative Guided layout for *task*."""
    return guided_task_definition(task).build_spec(is_2d=is_2d)
