"""Select a task's declarative guided layout."""
from .schema import TaskDialogSpec
from ..tasks import guided_task_definition


def task_dialog_spec(task: str, *, is_2d: bool = False) -> TaskDialogSpec:
    return guided_task_definition(task).dialog_spec(is_2d=is_2d)
