"""SCF guided setup pages and their parameter-driven presentation rules."""
from dataclasses import replace

from .schema import (
    Choice,
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
    ALG,
    BZINT,
    CONVERGENCE_COLOR,
    ENERGY_COLOR,
    FULLPOT,
    GEOMETRY_COLOR,
    INITIAL_COLOR,
    ISTBRY,
    ITDEPT,
    KKRMODE,
    KRMT,
    MIX,
    MODE,
    MODEL_COLOR,
    NITER,
    NONMAG,
    QUICK_COLOR,
    TOL,
    USEVMATT,
    VXC,
    _energy_grid_groups,
    _output_page,
    beyond_dft_enabled,
    bz_integration_enabled,
    cluster_active,
    cluster_centre_reason,
    cluster_extent_enabled,
    cluster_extent_reason,
    cluster_note,
    explicit_reference_energy_enabled,
    lda_u_enabled,
    magnetic_enabled,
    points_integration_enabled,
    structure_constants_enabled,
    weyl_integration_enabled,
)


def broyden_enabled(context: PresentationContext) -> bool:
    """Broyden history settings apply only to the BROYDEN2 mixer."""
    return context.value("SCF", "ALG") == "BROYDEN2"


def build_spec(is_2d: bool) -> TaskDialogSpec:
    kpoints = (
        field("TAU", "NKTAB2D", "2D-region k-points:", "integer", minimum=1, maximum=100000, step=10,
              enabled_when=points_integration_enabled),
        field("TAU", "NKTAB3D", "3D-region k-points:", "integer", minimum=1, maximum=100000, step=10,
              enabled_when=points_integration_enabled),
    ) if is_2d else (
        field("TAU", "NKTAB", "Special k-points:", "integer", minimum=1, maximum=100000, step=10,
              enabled_when=points_integration_enabled),
    )
    ne = main_energy_mesh_field("NE", "Energy-mesh points:", "integer", minimum=1, maximum=100000)
    return TaskDialogSpec("scf", "scf", "SCF Calculation Setup", (
        PageSpec("quick", "Quick setup", (
            GroupSpec("Common SCF settings", (
                mirror(VXC), mirror(NITER), mirror(TOL), mirror(ne), mirror(kpoints[0]), mirror(USEVMATT),
            )),
        ), QUICK_COLOR, quick=True),
        PageSpec("physical", "Physical model", (
            GroupSpec("Exchange-correlation and relativity", (VXC, MODE)),
            GroupSpec("Magnetism and symmetry", (
                NONMAG,
                field("CONTROL", "NOSYM", "Disable symmetry:", "boolean"),
            ), id="magnetism"),
            GroupSpec("Magnetisation orientation", (
                field("MODE", "MDIR", "Direction vector [x, y, z]:", "literal", enabled_when=magnetic_enabled),
                field("MODE", "MALF", "Alpha angle:", "real", minimum=-360., maximum=360., step=1., nullable=True,
                      enabled_when=magnetic_enabled),
                field("MODE", "MBET", "Beta angle:", "real", minimum=-360., maximum=360., step=1., nullable=True,
                      enabled_when=magnetic_enabled),
                field("MODE", "MGAM", "Gamma angle:", "real", minimum=-360., maximum=360., step=1., nullable=True,
                      enabled_when=magnetic_enabled),
            ), collapsed=True, id="orientation"),
            GroupSpec("Potential shape and atomic radii", (
                FULLPOT,
                field(
                    "CONTROL", "KRWS", "Wigner-Seitz radii:", "choice",
                    choices=(Choice("Read from potential", 0), Choice("Calculate by scaling RMT", 1)),
                ),
                KRMT,
            )),
            GroupSpec("Beyond DFT", (
                field("MODE", "OP", "Beyond-DFT method:", "keyword"),
                field("MODE", "LOPT", "Correlated orbitals:", "literal", enabled_when=beyond_dft_enabled),
                field("MODE", "IEREF", "Reference-energy method:", "keyword", descriptions=True,
                      enabled_when=lda_u_enabled),
                field("MODE", "EREF", "Reference energy:", "real", minimum=-100., maximum=100., step=.01,
                      enabled_when=explicit_reference_energy_enabled),
                field("MODE", "UMODE", "LDA+U formulation:", "keyword", enabled_when=lda_u_enabled),
                field("MODE", "UEFF", "U values:", "literal", enabled_when=lda_u_enabled),
                field("MODE", "JEFF", "J values:", "literal", enabled_when=lda_u_enabled),
            ), collapsed=True, id="beyond_dft"),
            GroupSpec("Relativistic scaling", (
                field("MODE", "C", "Speed-of-light scale:", "scaling"),
                field("MODE", "SOC", "Spin-orbit scale:", "scaling"),
            ), collapsed=True, id="scaling"),
        ), MODEL_COLOR),
        PageSpec("initial", "Initial state", (
            GroupSpec("Starting potential", (USEVMATT,)),
            GroupSpec("Initial charge density", (
                field("SCF", "QION", "Ionic charges by atomic type:", "literal"),
                field("SCF", "QIONSCL", "Ionic-charge scale:", "real",
                      minimum=0., maximum=10., step=.01, nullable=True),
            ), note="Charges are ordered by atomic type in the potential file, not by site. Leave empty to use defaults."),
            GroupSpec("Initial magnetisation density", (
                field("SCF", "MSPIN", "Spin moments by atomic type:", "literal", enabled_when=magnetic_enabled),
            ), note="One value per atomic type, in potential-file order. Leave empty to use defaults."),
        ), INITIAL_COLOR),
        PageSpec("convergence", "SCF convergence", (
            GroupSpec("Stopping criteria", (NITER, TOL)),
            GroupSpec("Potential mixing", (
                ALG, MIX,
                replace(ISTBRY, enabled_when=broyden_enabled),
                replace(ITDEPT, enabled_when=broyden_enabled),
                field("SCF", "MIXOP", "Orbital-potential mixing:", "real",
                      minimum=.001, maximum=1., step=.01, decimals=4, nullable=True,
                      enabled_when=beyond_dft_enabled),
            )),
            GroupSpec("Fermi energy", (
                field("SCF", "EFGUESS", "Initial Fermi-energy guess:", "energy",
                      minimum=-100., maximum=100., step=.01, nullable=True),
            )),
            GroupSpec("CPA convergence", (
                field("CPA", "NITER", "Maximum CPA iterations:", "integer", minimum=1, maximum=2000),
                field("CPA", "TOL", "CPA tolerance:", "real", minimum=1e-10, maximum=1., step=1e-5, decimals=10),
            ), collapsed=True, note="Relevant for substitutionally disordered systems.", id="cpa"),
        ), CONVERGENCE_COLOR),
        PageSpec("energy", "Energy grids", _energy_grid_groups(ne) + (
            GroupSpec("Energy range", (
                energy_bound("EMIN", "Minimum energy:"),
                field("ENERGY", "ImE", "Imaginary energy:", "energy", minimum=0.),
            )),
        ), ENERGY_COLOR),
        PageSpec("kkr", "KKR & integration", (
            GroupSpec("KKR representation and basis", (
                KKRMODE,
                field("SITES", "NL", "Angular-momentum cutoffs:", "literal"),
                field("TAU", "CLUSTER", "Use cluster mode:", "boolean"),
                field("TAU", "MOL", "Molecular calculation:", "boolean"),
            )),
            GroupSpec("Brillouin-zone integration", (replace(BZINT, enabled_when=bz_integration_enabled),)
                      + kpoints + (
                field("TAU", "NKMIN", "Minimum k-points:", "integer", minimum=1, maximum=1000000, step=50,
                      enabled_when=weyl_integration_enabled),
                field("TAU", "NKMAX", "Maximum k-points:", "integer", minimum=1, maximum=1000000, step=50,
                      enabled_when=weyl_integration_enabled),
                field("MODE", "LLOYD", "Use Lloyd formula:", "boolean"),
            ), id="bz_integration"),
            GroupSpec("Cluster extent and centre", (
                field("TAU", "NSHLCLU", "Cluster shells:", "integer", minimum=1, maximum=100, nullable=True,
                      enabled_when=cluster_extent_enabled, disabled_reason_when=cluster_extent_reason),
                field("TAU", "CLURAD", "Cluster radius:", "real", minimum=0., maximum=100., step=.1,
                      nullable=True, enabled_when=cluster_extent_enabled,
                      disabled_reason_when=cluster_extent_reason),
                field("TAU", "IQCNTR", "Central site:", "integer", minimum=1, maximum=999999, nullable=True,
                      enabled_when=cluster_active, disabled_reason_when=cluster_centre_reason),
                field("TAU", "ITCNTR", "Central atomic type:", "integer", minimum=1, maximum=999999, nullable=True,
                      enabled_when=cluster_active, disabled_reason_when=cluster_centre_reason),
                field("TAU", "NLOUT", "Cluster angular cutoff:", "integer", minimum=1, maximum=12,
                      enabled_when=cluster_active, disabled_reason_when=cluster_centre_reason),
            ), id="cluster_extent", note="Set the extent using shells or radius.", note_when=cluster_note),
            GroupSpec("Structure constants", (
                field("STRCONST", "ETA", "Ewald parameter:", "real", minimum=0., maximum=100., step=.01,
                      nullable=True, enabled_when=structure_constants_enabled),
                field("STRCONST", "RMAX", "Real-space convergence radius:", "real",
                      minimum=0., maximum=100., step=.1, nullable=True,
                      enabled_when=structure_constants_enabled),
                field("STRCONST", "GMAX", "Reciprocal-space convergence radius:", "real",
                      minimum=0., maximum=100., step=.1, nullable=True,
                      enabled_when=structure_constants_enabled),
            ), collapsed=True, id="structure_constants"),
        ), GEOMETRY_COLOR),
        _output_page(scf=True),
    ), intro=(
        "Configure the most useful task parameters. Quick setup mirrors a small selection from the detailed "
        "categories; all remaining parameters are available in Expert settings."
        + (" One SCF run for a 2D system converges the bulk regions and then the interaction zone."
           if is_2d else "")
    ))
