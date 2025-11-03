from pyxtal.symmetry import Group
import math
import re
import numpy as np
from ase.geometry import cellpar_to_cell

lattice_fixed_params = {
    "triclinic":    {},
    "monoclinic":   { 'α': 90., 'γ': 90. },
    "orthorhombic": { 'α': 90., 'β': 90., 'γ': 90. },
    "tetragonal":   { 'b': 'a', 'α': 90., 'β': 90., 'γ': 90. },
    "hexagonal":    { 'b': 'a', 'α': 90., 'β': 90., 'γ': 120. },
    "trigonal":     { 'b': 'a', 'α': 90., 'β': 90., 'γ': 120. },
    "cubic":        { 'b': 'a', 'c': 'a', 'α': 90., 'β': 90., 'γ': 90. }
}

lattice_default_params = {
        'a' : 1.0,
        'b' : 1.3,
        'c' : 1.6,
        'α' : 80,
        'β':  100,
        'γ':  110
}

def complete_lattice_params(group, params):
    info = lattice_fixed_params[group.lattice_type]
    out = params.copy()
    for k, v in lattice_default_params.items():
        f = info.get(k, None)
        if f is not None:
            if isinstance(f, float):
                out[k] = f
            else:
                out[k] = out[f]
        elif out.get(k, 0.) == 0.:
            out[k] = v
    return out;

def lattice_from_params(params):
    """
    Return 3x3 lattice vectors (rows) in Cartesian coordinates for visualization.
    """
    return cellpar_to_cell([params[k] for k in lattice_default_params])
