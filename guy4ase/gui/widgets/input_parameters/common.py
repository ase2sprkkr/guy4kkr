"""Session adapters for compound controls shared by guided task dialogs."""
from __future__ import annotations

from guy4ase.gui.input_parameters.energy import (
    bound_energy_state,
    reference_selectable,
    set_bound_energy,
)
from guy4ase.gui.widgets.input_parameters.energy import EnergyEditor
from guy4ase.gui.widgets.input_parameters.relativistic_scaling import (
    RelativisticScalingEditor,
)


class BoundEnergyParameterEditor(EnergyEditor):
    """Bind the shared absolute/relative energy widget to a guided session."""

    def __init__(self, session, placement, page_id, atoms=None, parent=None):
        del atoms
        self.session = session
        self.placement = placement
        self.page_id = page_id
        name = placement.path[-1]

        def apply(value, unit, relative):
            session.mutate(
                lambda parameters: set_bound_energy(parameters, name, value, unit, relative),
                source_page=page_id,
                path=placement.path,
                text=f"Change {placement.label.rstrip(':')}",
            )

        super().__init__(
            lambda: bound_energy_state(session.working_parameters, name),
            apply,
            parent,
            reference_selectable=lambda: reference_selectable(
                session.working_parameters, name
            ),
        )

class RelativisticScalingParameterEditor(RelativisticScalingEditor):
    """Adapt the shared per-type scaling table to a guided field placement."""

    # The number of orbital columns follows SITES.NL as well as the edited path.
    dependencies = (("SITES", "NL"),)

    def __init__(self, session, placement, page_id, atoms=None, parent=None):
        del atoms
        self.placement = placement
        super().__init__(session, placement.path, page_id, parent)

    def focus_for_history(self, _path, index) -> None:
        if self.table.rowCount():
            self.table.setCurrentCell(min(index or 0, self.table.rowCount() - 1), 0)
        super().focus_for_history(_path, index)


EDITORS = {
    "energy_bound": BoundEnergyParameterEditor,
    "scaling": RelativisticScalingParameterEditor,
}
