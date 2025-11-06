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

def chain_dialogs(*funcs, initial={}, all=False, back=False):
    if initial is None:
        initial = {}

    results = []
    i = 0

    while i < len(funcs):
        func = funcs[i]

        # Určit argumenty pro aktuální funkci
        if i == 0 and len(results) == 0:
            args = initial
        else:
            # Vezmeme výsledek předchozí funkce a přidáme případný back argument
            args = results[i-1].copy()
        if back and i > 0:
            if back is True:
                args['back'] = True
            else:
                args[back] = True

        result = func(**args, **all)

        if result is None:
            return None
        elif isinstance(result, str) and result == 'back':
            # Pokud funkce vrátí 'back', vrátíme se k předchozí
            if i == 0:
                return None
            i -= 1
            continue
 
        if len(results) <= i:
            results.append(result)
        else:
            results[-1] = result
        

        i += 1

    return results if all else results[-1] if results else None