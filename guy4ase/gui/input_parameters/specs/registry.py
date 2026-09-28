"""Select a task's declarative guided layout."""
from . import arpes, bsf, dos, jxc, scf, xas
from .schema import TaskDialogSpec

_BUILDERS = {"scf": scf.build_spec, "bsf": bsf.build_spec, "dos": dos.build_spec,
             "xas": xas.build_spec, "arpes": arpes.build_spec, "jxc": jxc.build_spec}


def task_dialog_spec(task: str, *, is_2d: bool = False) -> TaskDialogSpec:
    builder = _BUILDERS.get(task.lower())
    if builder is None:
        raise ValueError(f"No guided setup is defined for task {task.upper()}.")
    spec = builder(is_2d)
    spec.primary_pages()
    return spec
