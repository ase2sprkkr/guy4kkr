"""BSF guided setup pages."""
from dataclasses import replace

from guy4ase.gui.input_parameters.bsf import EK, bsf_mode

from .scf import build_spec as _scf_spec
from .schema import (
    GroupSpec,
    PageSpec,
    PresentationContext,
    TaskDialogSpec,
    energy_bound,
    field,
    main_energy_mesh_field,
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


def ek_mode(context: PresentationContext) -> bool:
    return bsf_mode(context.parameters) == EK


def kk_mode(context: PresentationContext) -> bool:
    return not ek_mode(context)


def custom_ek_path(context: PresentationContext) -> bool:
    return ek_mode(context) and context.value("TASK", "KPATH") is None


def vectors_visible(context: PresentationContext) -> bool:
    return kk_mode(context) or custom_ek_path(context)


def vectors_title(context: PresentationContext) -> str:
    return "Custom path" if ek_mode(context) else "K–k plane"


def vectors_label(context: PresentationContext) -> str:
    return "Path segments (2π/a):" if ek_mode(context) else "Plane origin KA (2π/a):"


def energy_minimum_label(context: PresentationContext) -> str:
    return "Minimum energy:" if ek_mode(context) else "Fixed energy:"


def _scf_pages(is_2d: bool) -> tuple[PageSpec, PageSpec]:
    """Reuse the common physical and KKR controls, plus CPA convergence."""
    pages = {page.id: page for page in _scf_spec(is_2d).pages}
    physical = pages["physical"]
    physical_groups = {group.id: group for group in physical.groups}
    physical = replace(physical, groups=(
        GroupSpec("Relativity", (MODE,)),
        *(physical_groups[group_id] for group_id in (
            "magnetism",
            "orientation",
            "beyond_dft",
            "scaling",
        )),
    ))
    cpa = next(group for group in pages["convergence"].groups if group.id == "cpa")
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
                collapsed=group.id == "hff")
        for group in output.groups
    )
    files = GroupSpec("File names", (
        field("CONTROL", "DATASET", "Dataset / output prefix:", "text"),
        field("CONTROL", "POTFIL", "Input potential file:", "text"),
    ), collapsed=True, note="Leave the potential file empty to let the calculator supply it.", id="files")
    return replace(output, title="Output & advanced", groups=(*groups, files))


def build_spec(is_2d: bool = False) -> TaskDialogSpec:
    bsf_emin = replace(energy_bound("EMIN", "Minimum / fixed energy:"), label_when=energy_minimum_label)
    bsf_emax = replace(energy_bound("EMAX", "Maximum energy:"), visible_when=ek_mode)
    bsf_ne = main_energy_mesh_field("NE", "BSF mode / energy points:", editor="bsf_mesh")
    bsf_im = field("ENERGY", "ImE", "Imaginary broadening:", "energy", minimum=0.)
    kpath = field("TASK", "KPATH", "Path:", editor="bsf_kpath", visible_when=ek_mode)
    nk = field("TASK", "NK", "Total points along path:", "integer", minimum=2, maximum=100000,
               step=10, visible_when=ek_mode)
    nk1 = field("TASK", "NK1", "Points along K1:", "integer", minimum=1, maximum=100000,
                nullable=True, visible_when=kk_mode, required_when=kk_mode)
    nk2 = field("TASK", "NK2", "Points along K2:", "integer", minimum=1, maximum=100000,
                nullable=True, visible_when=kk_mode, required_when=kk_mode)
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
            ), id="ek_path", visible_when=ek_mode),
            GroupSpec("Explicit k-vectors", (
                field("TASK", "KA", "Path segments / plane origin:", editor="bsf_vectors",
                      related_paths=(("TASK", "KE"),), label_when=vectors_label,
                      enabled_when=vectors_visible, required_when=custom_ek_path),
                field("TASK", "K1", "First spanning vector (2π/a):", "vector",
                      visible_when=kk_mode, required_when=kk_mode), nk1,
                field("TASK", "K2", "Second spanning vector (2π/a):", "vector",
                      visible_when=kk_mode, required_when=kk_mode), nk2,
            ), id="vectors", visible_when=vectors_visible, title_when=vectors_title),
        ), SPECIAL_COLOR),
        physical,
        kkr,
        _bsf_output_page(),
    ))
