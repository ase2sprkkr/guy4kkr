"""Completion checks shared by both dialogs, without save-only I/O requirements."""
from ase2sprkkr.common.warnings import DataValidityError
from ase2sprkkr.input_parameters.definitions.arpes import angular_scan_errors
from ase2sprkkr.input_parameters.definitions.sections import energy_reference_error


class InputParametersValidationError(ValueError):
    """Validation failure caused by the current editable parameters."""


def validate_setup(parameters):
    """Validate an accepted edit without requiring calculator-supplied POTFIL."""
    try:
        parameters.validate(why='set')
    except DataValidityError as error:
        raise InputParametersValidationError(str(error)) from error
    errors = []
    if 'ENERGY' in parameters:
        error = energy_reference_error(parameters.ENERGY)
        if error:
            errors.append(error)
    if parameters.task_name.lower() == 'arpes':
        errors.extend(angular_scan_errors(parameters))
    if errors:
        raise InputParametersValidationError('\n'.join(errors))
