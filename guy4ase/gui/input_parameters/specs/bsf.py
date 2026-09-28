"""BSF guided setup pages."""
from dataclasses import replace

from .scf import build_spec as _scf_spec
from .schema import (
    GroupSpec,
    PageSpec,
    TaskDialogSpec,
    energy_bound,
    field,
    mirror,
)
from .shared import (
    ENERGY_COLOR,
    MODE,
    QUICK_COLOR,
    SPECIAL_COLOR,
    _energy_grid_groups,
    _output_page,
)


def build_spec(is_2d: bool = False) -> TaskDialogSpec:
    """Declare both BSF modes; the dialog adapts visible fields to ENERGY.NE[0]."""
    bsf_emin = energy_bound("EMIN", "Minimum / fixed energy:")
    bsf_emax = energy_bound("EMAX", "Maximum energy:")
    bsf_ne = field("ENERGY", "NE", "BSF mode / energy points:", "bsf_mesh")
    bsf_im = field("ENERGY", "ImE", "Imaginary broadening:", "energy", minimum=0.)
    kpath = field("TASK", "KPATH", "Path:", "kpath")
    nk = field("TASK", "NK", "Total points along path:", "integer", minimum=2, maximum=100000, step=10)
    nk1 = field("TASK", "NK1", "Points along K1:", "integer", minimum=1, maximum=100000, nullable=True)
    nk2 = field("TASK", "NK2", "Points along K2:", "integer", minimum=1, maximum=100000, nullable=True)
    # Reuse shared SCF groups, excluding SCF-only potential/initial-state fields.
    common = {page.id: page for page in _scf_spec(is_2d).pages}
    physical = replace(common["physical"], groups=(
        GroupSpec("Relativity", (MODE,)),
    ) + tuple(group for group in common["physical"].groups
              if group.id in {"magnetism", "orientation", "beyond_dft", "scaling"}))
    kkr = replace(common["kkr"], groups=common["kkr"].groups + tuple(
        group for group in common["convergence"].groups if group.id == "cpa"))
    output = replace(_output_page(), title="Output & advanced", groups=tuple(
        replace(group, fields=tuple(f for f in group.fields if f.path not in {
            ("CONTROL", "NOSYM"), ("CONTROL", "SPLITSS")}),
            collapsed=group.id == "hff")
        for group in _output_page().groups
    ) + (GroupSpec("File names", (
        field("CONTROL", "DATASET", "Dataset / output prefix:", "text"),
        field("CONTROL", "POTFIL", "Input potential file:", "text"),
    ), collapsed=True, note="Leave the potential file empty to let the calculator supply it."),))
    bsf = TaskDialogSpec("bsf", "bsf", "BSF Calculation Setup", (
        PageSpec("quick", "Quick setup", (GroupSpec("Common BSF settings", (
            mirror(bsf_ne), mirror(bsf_emin), mirror(bsf_emax), mirror(bsf_im),
            mirror(kpath), mirror(nk), mirror(nk1), mirror(nk2),
        )),), QUICK_COLOR, quick=True),
        PageSpec("energy", "Mode & energy", _energy_grid_groups(bsf_ne) + (
            GroupSpec("Energy range / fixed energy", (bsf_emin, bsf_emax, bsf_im),
                      note="The main energy grid defines BSF sampling: NE > 1 gives an E–k path; NE = 1 a k–k map. Switching mode resets its geometry and energy settings; Undo restores them."),
        ), ENERGY_COLOR),
        PageSpec("path", "K-space geometry", (
            GroupSpec("E–k path", (
                kpath,
                nk,
            ), special="bsf_ek"),
            GroupSpec("Explicit k-vectors", (
                field("TASK", "KA", "Path segments / plane origin:", "bsf_vectors",
                      related_paths=(("TASK", "KE"),)),
                field("TASK", "K1", "First spanning vector (2π/a):", "vector"), nk1,
                field("TASK", "K2", "Second spanning vector (2π/a):", "vector"), nk2,
            ), special="bsf_vectors"),
        ), SPECIAL_COLOR),
        physical,
        kkr,
        output,
    ))

    return bsf
