"""Shared fields, colors and page groups for task definitions."""
from dataclasses import replace

from .schema import Choice, FieldPlacement, GroupSpec, PageSpec, field

QUICK_COLOR = "#2878b8"
MODEL_COLOR = "#27836b"
CONVERGENCE_COLOR = "#6f8f32"
INITIAL_COLOR = "#7655a6"
ENERGY_COLOR = "#c27622"
OUTPUT_COLOR = "#a84e64"
GEOMETRY_COLOR = "#536f9e"
SPECIAL_COLOR = "#8a5b9f"
ADVANCED_COLOR = "#607d8b"


VXC = field("SCF", "VXC", "Exchange-correlation:", "keyword")
MODE = field(
    "MODE", "MODE", "Relativity and spin:", "keyword",
    choices=(Choice("Fully relativistic (default)", None),),
)
NONMAG = field("CONTROL", "NONMAG", "Non-magnetic calculation:", "boolean")
FULLPOT = field("SCF", "FULLPOT", "Full potential:", "boolean")
KRMT = field("CONTROL", "KRMT", "Muffin-tin radius scheme:", "keyword", descriptions=True,
             choices=(Choice("Automatic (not specified)", None),))
USEVMATT = field(
    "SCF", "USEVMATT", "Starting guess:", "choice",
    choices=(
        Choice("Atomic charge density (recommended)", False),
        Choice("Mattheiss potential", True),
    ),
)
NITER = field("SCF", "NITER", "Maximum iterations:", "integer", minimum=1, maximum=2000, step=10)
TOL = field("SCF", "TOL", "Convergence tolerance:", "real", minimum=1e-10, maximum=1.0,
            step=1e-6, decimals=10)
ALG = field("SCF", "ALG", "Mixing algorithm:", "keyword")
MIX = field("SCF", "MIX", "Mixing factor:", "real", minimum=.001, maximum=1., step=.01, decimals=4)
ISTBRY = field("SCF", "ISTBRY", "Start Broyden after:", "integer", minimum=1, maximum=100)
ITDEPT = field("SCF", "ITDEPT", "Broyden history length:", "integer", minimum=1, maximum=500)
BZINT = field("TAU", "BZINT", "BZ integration:", "keyword")
KKRMODE = field(
    "TAU", "KKRMODE", "KKR representation:", "keyword",
    choices=(Choice("Default", None),),
)
GRID = field("ENERGY", "GRID", "Energy grid (contour):", "keyword", index=0, descriptions=True)


def _energy_grid_groups(ne: FieldPlacement) -> tuple[GroupSpec, ...]:
    return (
        GroupSpec("Single-site contribution", (
            field("ENERGY", "SPLITSS", "Separate single-site contour:", "boolean"),
            field("CONTROL", "SPLITSS", "Force separate contour (CONTROL):", "boolean"),
        ), note="Also required by CONTROL.FSOHFF. Disabled single-site settings are remembered until this dialog is closed. SPRKKR sets Im(E) to zero when SPLITSS is active."),
        GroupSpec("Energy grids", (
            replace(GRID, label="Main energy grid (contour):"),
            replace(GRID, index=1, label="Single-site energy grid (contour):"),
            ne,
            field("ENERGY", "NE", "Single-site energy points:", "integer",
                  index=1, minimum=1, maximum=100000, nullable=True),
        ), special="energy_grids"),
    )


def _output_page(*, include_hff: bool = True, scf: bool = False) -> PageSpec:
    hyperfine_fields = (
        field("TASK", "HFF", "Calculate hyperfine field:", "boolean"),
        field("CONTROL", "NOHFF", "Disable hyperfine-field calculation:", "boolean"),
        field("CONTROL", "FSOHFF", "Relativistic HFF decomposition:", "boolean"),
    ) if include_hff else (
        field("CONTROL", "NOHFF", "Disable hyperfine-field calculation:", "boolean"),
        field("CONTROL", "FSOHFF", "Relativistic HFF decomposition:", "boolean"),
    )
    hyperfine_fields += () if scf else (
        field("CONTROL", "SPLITSS", "Force separate single-site contour:", "boolean"),
    )
    return PageSpec("output", "Results & files" if scf else "Output & diagnostics", (
        GroupSpec("Output", (
            field("CONTROL", "PRINT", "Print level:", "integer", minimum=0, maximum=5),
        ) + (() if scf else (field("CONTROL", "NOSYM", "Disable symmetry:", "boolean"),))),
        GroupSpec("Hyperfine field", hyperfine_fields, id="hff"),
    ) + ((GroupSpec("File names", (
        field("CONTROL", "DATASET", "Dataset / output prefix:", "text"),
        field("CONTROL", "POTFIL", "Input potential file:", "text"),
    ), collapsed=True, note="Leave the potential file empty to let the calculator supply it."),) if scf else ()), OUTPUT_COLOR)

nktab = field("TAU", "NKTAB", "Special k-points:", "integer", minimum=1, maximum=1000000, step=50)
nl = field("SITES", "NL", "Angular-momentum cutoffs (NL):", "literal")
