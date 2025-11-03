from ase import units
from tkinter import ttk

length_units = {
        "Angstrom (Å)": 1.0,
        "Nanometer (nm)": 10.0,
        "Picometer (pm)": 0.01,
        "Rydberg (Ry)": units.Rydberg / units.Angstrom,
        "Bohr (a0)": units.Bohr / units.Angstrom,
}

def create_units_combo(parent, callback):
    combo = ttk.Combobox(parent, values=list(length_units.keys()))
    combo.set("Angstrom (Å)")
    combo.bind("<<ComboboxSelected>>", lambda event: callback(length_units[combo.get()]) )
    return combo
