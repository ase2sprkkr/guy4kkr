"""Prepare task input before creating an editing session, without GUI dependencies."""
from .bsf import prepare_bsf


def prepare_parameters(parameters, task):
    """Normalize BSF aliases and add curated extensible options to a copy.

    Task identity is checked before canonicalization, never inferred from the
    destination dialog. Imported input is not populated with new-task presets.
    """
    if task == 'bsf':
        return prepare_bsf(parameters)
    if parameters.task_name.lower() != task:
        raise ValueError(f'Expected {task.upper()} input parameters, got {parameters.task_name.upper()}.')
    prepared = parameters.copy(copy_values=True)
    if task == 'xas' and 'EMAX' not in prepared.ENERGY:
        prepared.ENERGY.add('EMAX', 4.0)
    if task == 'jxc' and 'DMI' not in prepared.TASK:
        prepared.TASK.add('DMI', False)
    return prepared
