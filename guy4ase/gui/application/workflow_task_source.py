"""Default Guided task source assembled from the central task registry."""
from __future__ import annotations

from guy4ase.gui.application.calculation_policy import guided_task_is_recommended
from guy4ase.gui.application.workflow_task_planner import GuidedTaskSource
from guy4ase.gui.input_parameters.tasks import guided_task_definitions


def default_guided_task_source() -> GuidedTaskSource:
    """Return the application's ordered Guided task metadata and policy."""
    return GuidedTaskSource.from_iterable(
        guided_task_definitions(),
        guided_task_is_recommended,
    )
