"""Energy units and absolute/relative InputParameters mappings."""
from dataclasses import dataclass

from ase2sprkkr.common.grammar_types import Energy


def convert_energy(value, source, target):
    return float((value * Energy.units[source]).to_value(Energy.units[target]))


@dataclass(frozen=True)
class EnergyState:
    """A displayed energy and unit; relative means referenced to Fermi energy."""
    value: float | None
    unit: str
    relative: bool = False


def bound_energy_state(parameters, name):
    """Read a bound, preferring an explicit relative *EV value over absolute Ry."""
    section = parameters.ENERGY
    relative = section[name + 'EV']()
    if relative is not None:
        return EnergyState(float(relative), 'eV', True)
    absolute = section[name]()
    return EnergyState(None if absolute is None else float(absolute), 'Ry')


def bound_energy_updates(name, value, unit, relative):
    """Build updates selecting one representation and clearing its counterpart.

    The caller must apply the returned mapping atomically. Values are converted
    to the backend's eV (relative) or Ry (absolute), without changing reference.
    """
    absolute_name, relative_name = name, name + 'EV'
    target = relative_name if relative else absolute_name
    return {absolute_name: None, relative_name: None,
            target: None if value is None else convert_energy(value, unit, 'eV' if relative else 'Ry')}
