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


def _scf_pages(is_2d: bool) -> tuple[PageSpec, PageSpec]:
    """Reuse the common physical and KKR controls, plus CPA convergence."""
    pages = {page.id: page for page in _scf_spec(is_2d).pages}
    physical = pages["physical"]
    physical_groups = {group.title: group for group in physical.groups}
    physical = replace(physical, groups=(
        GroupSpec("Relativity", (MODE,)),
        *(physical_groups[name] for name in (
            "Magnetism and symmetry",
            "Magnetisation orientation",
            "Beyond DFT",
            "Relativistic scaling",
        )),
    ))
    cpa = next(group for group in pages["convergence"].groups
               if group.title == "CPA convergence")
    kkr = pages["kkr"]
    return physical, replace(kkr, groups=(*kkr.groups, cpa))


def _bsf_output_page() -> PageSpec:
    """Keep common diagnostics while moving BSF's file names to this page."""
    output = _output_page()
    groups = tuple(
        replace(group,
                fields=tuple(item for item in group.fields if item.path not in {
                    ("CONTROL", "NOSYM"), ("CONTROL", "SPLITSS"),
                }),
                collapsed=group.title == "Hyperfine field")
        for group in output.groups
    )
    files = GroupSpec("File names", (
        field("CONTROL", "DATASET", "Dataset / output prefix:", "text"),
        field("CONTROL", "POTFIL", "Input potential file:", "text"),
    ), collapsed=True, note="Leave the potential file empty to let the calculator supply it.")
    return replace(output, title="Output & advanced", groups=(*groups, files))


def build_spec(is_2d: bool = False) -> TaskDialogSpec:
    bsf_emin = energy_bound("EMIN", "Minimum / fixed energy:")
    bsf_emax = energy_bound("EMAX", "Maximum energy:")
    bsf_ne = field("ENERGY", "NE", "BSF mode / energy points:", "bsf_mesh")
    bsf_im = field("ENERGY", "ImE", "Imaginary broadening:", "energy", minimum=0.)
    kpath = field("TASK", "KPATH", "Path:", "kpath")
    nk = field("TASK", "NK", "Total points along path:", "integer", minimum=2, maximum=100000, step=10)
    nk1 = field("TASK", "NK1", "Points along K1:", "integer", minimum=1, maximum=100000, nullable=True)
    nk2 = field("TASK", "NK2", "Points along K2:", "integer", minimum=1, maximum=100000, nullable=True)
    physical, kkr = _scf_pages(is_2d)
    return TaskDialogSpec("bsf", "bsf", "BSF Calculation Setup", (
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
        _bsf_output_page(),
    ))
