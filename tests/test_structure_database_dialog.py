import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/guy4ase-test-matplotlib")

from PyQt6.QtWidgets import QApplication

from guy4ase.gui.dialogs.structures.spacegroup_selector import SpaceGroupSelectorDialog
from guy4ase.gui.dialogs.structures.database import StructureDatabaseDialog
from guy4ase.physics.structure_database import load_structure_database


def test_filtered_selection_and_details_stay_synchronized():
    application = QApplication.instance() or QApplication([])
    dialog = StructureDatabaseDialog()

    dialog.search_edit.setText("CsCl")
    application.processEvents()

    assert dialog.selected_prototype is not None
    assert dialog.selected_prototype.name.startswith("B2")
    assert "Space group 221" in dialog.details_label.text()
    assert "B2" in dialog.details_label.text()
    assert dialog.table.horizontalHeaderItem(0).text() == "Description"
    assert dialog.table.horizontalHeaderItem(1).text() == "Structure type"
    dialog.close()


def test_unknown_structure_type_is_presented_without_source_placeholder():
    application = QApplication.instance() or QApplication([])
    dialog = StructureDatabaseDialog()

    dialog.search_edit.setText("ReSi2")
    application.processEvents()

    assert dialog.table.item(0, 1).text() == "Unknown"
    assert "Unknown oI6 ReSi2" in dialog.details_label.text()
    assert "???" not in dialog.details_label.text()
    dialog.close()


def test_every_database_prototype_can_preload_the_shared_editor():
    application = QApplication.instance() or QApplication([])
    dialog = SpaceGroupSelectorDialog()

    for prototype in load_structure_database():
        dialog.load_prototype(prototype)
        selected_space_group = int(
            dialog.table.item(dialog.table.currentRow(), 0).text()
        )
        assert selected_space_group == prototype.space_group
        assert sum(map(len, dialog._selected_sites.values())) == len(prototype.sites)

    dialog.close()
    application.processEvents()


def test_shared_editor_creates_representative_database_structures():
    application = QApplication.instance() or QApplication([])
    dialog = SpaceGroupSelectorDialog()
    expected_atom_counts = {
        "B2    cP2   CsCl": 2,
        "C4    tP6   TiO2 (Rutil)": 6,
        "L1_1  hR32  CuPt": 6,
        "Molecular Perovskite x": 12,
    }

    prototypes = {item.name: item for item in load_structure_database()}
    for name, atom_count in expected_atom_counts.items():
        dialog.load_prototype(prototypes[name])
        values = {
            "a": 4.0,
            "b": 5.0,
            "c": 6.0,
            "α": 80.0,
            "β": 90.0,
            "γ": 100.0,
        }
        for key, value in values.items():
            if dialog._lat_vars[key].isEnabled():
                dialog._lat_vars[key].setText(str(value))

        atoms = dialog.create_atoms()
        assert len(atoms) == atom_count
        assert len(set(atoms.arrays["spacegroup_kinds"])) == len(
            prototypes[name].sites
        )

    dialog.close()
    application.processEvents()


def test_database_editor_focuses_first_editable_lattice_parameter():
    application = QApplication.instance() or QApplication([])
    dialog = SpaceGroupSelectorDialog()
    prototype = next(
        item for item in load_structure_database() if item.name.startswith("C4 ")
    )
    dialog.load_prototype(prototype)
    dialog.show()

    dialog.focus_lattice_parameters()
    application.processEvents()

    assert application.focusWidget() is dialog._lat_vars["a"]
    dialog.close()
