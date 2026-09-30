"""Qt-independent expert-field declaration tests."""

from ase2sprkkr.input_parameters.input_parameters import InputParameters

from guy4ase.gui.input_parameters.expert_fields import (
    EXPERT_FIELDS,
    applicable_expert_fields,
)


def test_expert_field_specs_create_registry_placements():
    spec = EXPERT_FIELDS[('ENERGY', 'EMIN')]
    placement = spec.placement(('ENERGY', 'EMIN'), 'EMIN')

    assert placement.editor == 'energy_bound'
    assert placement.label == 'EMIN / EMINEV'
    assert placement.related_paths == (('ENERGY', 'EMINEV'),)
    assert placement.minimum == -1e9


def test_only_fields_present_in_a_task_are_applicable():
    scf = applicable_expert_fields(InputParameters.create('scf'))
    dos = applicable_expert_fields(InputParameters.create('dos'))

    assert ('ENERGY', 'EMIN') in scf
    assert ('ENERGY', 'EMAX') not in scf
    assert ('MODE', 'C') in scf
    assert ('MODE', 'SOC') in scf
    assert ('ENERGY', 'EMAX') in dos
