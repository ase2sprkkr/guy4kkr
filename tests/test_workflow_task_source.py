from guy4ase.gui.application.workflow_facts import ScfProgress
from guy4ase.gui.application.workflow_presentation import WorkflowCommandKind
from guy4ase.gui.application.workflow_task_planner import GuidedWorkflowPlanner
from guy4ase.gui.application.workflow_task_source import default_guided_task_source


class Atoms:
    def get_chemical_formula(self):
        return "Fe"


class Workspace:
    def __init__(self, progress):
        self.atoms = Atoms()
        self._progress = progress

    def scf_progress(self):
        return self._progress

    def structure_kind(self):
        return "3d"

    def can_build_2d(self):
        return True

    def empty_spheres_action(self):
        return None

    def structure_change_requires_scf_restart(self):
        return False


def _task_names(plan):
    calculate = plan.groups[0]
    return tuple(
        action.command.minor
        for action in calculate.actions
        if action.command.kind is WorkflowCommandKind.RUN_TASK
    )


def test_default_task_source_uses_registry_order_before_convergence():
    planner = GuidedWorkflowPlanner(default_guided_task_source())

    plan = planner.for_workspace(Workspace(ScfProgress.NOT_STARTED))

    assert _task_names(plan) == ("scf",)


def test_default_task_source_uses_registry_order_after_convergence():
    planner = GuidedWorkflowPlanner(default_guided_task_source())

    plan = planner.for_workspace(Workspace(ScfProgress.CONVERGED))

    assert _task_names(plan) == ("xas", "arpes", "dos", "bsf", "jxc")


def test_default_task_source_uses_registry_presentation_text():
    planner = GuidedWorkflowPlanner(default_guided_task_source())

    plan = planner.for_workspace(Workspace(ScfProgress.CONVERGED))
    calculate = plan.groups[0]
    dos = next(
        action for action in calculate.actions if action.command.minor == "dos"
    )

    assert dos.title == "Calculate DOS"
    assert dos.description == "Electronic density of states"
