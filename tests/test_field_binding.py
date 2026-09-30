"""Regressions for the Qt-independent guided field/session adapter."""
from ase2sprkkr.input_parameters.input_parameters import InputParameters

from guy4ase.gui.input_parameters.field_binding import (
    IndexedFieldBinding,
    SessionFieldBinding,
    create_field_binding,
)
from guy4ase.gui.input_parameters.session import InputParametersSession
from guy4ase.gui.input_parameters.single_site_contour import SingleSiteContourPlugin
from guy4ase.gui.input_parameters.specs.schema import field


def _secondary_ne_binding(session):
    placement = field(
        "ENERGY",
        "NE",
        "Single-site energy points",
        "integer",
        index=1,
    )
    return create_field_binding(session, placement, "energy")


def _contour_session():
    return InputParametersSession(
        InputParameters.create("scf"),
        plugins=(SingleSiteContourPlugin(),),
    )


def test_indexed_field_binding_replaces_only_its_component():
    session = _contour_session()
    session.set_value(("ENERGY", "SPLITSS"), True)
    before = list(session.value(("ENERGY", "NE")))
    binding = _secondary_ne_binding(session)

    binding.set_value(87)

    assert list(session.value(("ENERGY", "NE"))) == [before[0], 87]


def test_field_binding_displays_dormant_mesh_without_storing_it():
    session = _contour_session()
    session.set_value(("ENERGY", "SPLITSS"), True)
    binding = _secondary_ne_binding(session)
    binding.set_value(87)
    session.set_value(("ENERGY", "SPLITSS"), False)
    history_count = session.undo_stack.count()

    state = binding.read()

    assert state.value == 87
    assert len(session.result().ENERGY.NE()) == 1
    assert session.undo_stack.count() == history_count


def test_explicit_index_uses_specialized_field_binding():
    session = InputParametersSession(InputParameters.create("scf"))
    placement = field("ENERGY", "NE", "Energy points", index=0)

    binding = create_field_binding(session, placement, "energy")

    assert isinstance(binding, IndexedFieldBinding)
    assert binding.index == 0


def test_scalar_option_uses_whole_value_binding():
    session = InputParametersSession(InputParameters.create("scf"))
    placement = field("SCF", "NITER", "Iterations")

    binding = create_field_binding(session, placement, "convergence")

    assert type(binding) is SessionFieldBinding


def test_array_type_without_explicit_index_remains_a_whole_value_binding():
    session = InputParametersSession(InputParameters.create("scf"))
    placement = field("SCF", "MSPIN", "Spin moments", "literal")

    binding = create_field_binding(session, placement, "initial")

    assert type(binding) is SessionFieldBinding


def test_dormant_only_plugin_state_is_generic_and_undoable():
    path = ("ENERGY", "NE")

    class DormantValuePlugin:
        def apply(self, _before, _candidate, dormant):
            dormant[(path, 1)] = 87

    session = InputParametersSession(
        InputParameters.create("scf"),
        plugins=(DormantValuePlugin(),),
    )
    binding = _secondary_ne_binding(session)

    assert session.mutate(lambda _candidate: None, text="Remember draft")
    assert binding.read().value == 87
    assert session.undo_stack.count() == 1

    session.undo_stack.undo()
    assert binding.read().value is None
    session.undo_stack.redo()
    assert binding.read().value == 87
