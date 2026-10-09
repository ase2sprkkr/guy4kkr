"""Prepare task input before creating an editing session, without GUI dependencies."""
from ase2sprkkr.input_parameters.input_parameters import InputParameters


def prepare_parameters(parameters, task):
    """Check task identity and return an independent copy for editing."""
    if parameters.task_name.lower() != task:
        raise ValueError(f'Expected {task.upper()} input parameters, got {parameters.task_name.upper()}.')
    return parameters.copy(copy_values=True)


def new_parameters(task):
    """Create a task input with domain defaults needed by the guided workflow."""
    parameters = InputParameters.create(task)
    if task == "bsf":
        # XBand's initial k-k plane. Imported BSF input is never populated by
        # this factory; prepare_parameters only normalizes it.
        parameters.TASK.set({
            "NK1": 60,
            "NK2": 60,
            "K1": [1., 0., 0.],
            "K2": [0., 1., 0.],
        })
    return parameters
