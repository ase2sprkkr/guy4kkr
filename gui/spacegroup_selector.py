import numpy as np
import tkinter as tk
from tkinter import ttk
from pyxtal.symmetry import Group
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
from ase.cell import Cell


from .lattice import plot_lattice, plot_sites_in_lattice
from ..physics.pyxtal_utils import complete_lattice_params, lattice_fixed_params, lattice_from_params
from .common import create_units_combo

class SpaceGroupSelector(tk.Toplevel):
    def __init__(self, master=None):
        super().__init__(master)
        self.title("Select Space Group")
        self.geometry("1000x650")
        self.selected_group = None

        self.system_var = tk.StringVar(value="All")
        self.search_var = tk.StringVar(value="")
        self.wp_vars = {}
        self.lattice_params = {}  # user-entered only
        self.positions = {}
        self.units = 1.

        self.spacegroups = [Group(i) for i in range(1, 231)]

        self.create_layout()
        self.update_list()

    def validate(self):
        if not self.selected_group:
            return "Select a spacegroup"
        if self.lattice is False:
            return "Invalid angles in the lattice"
        if not self.is_lattice_defined():
            return "Define the lattice parameters"
        if not self.is_any_position_defined():
            return "Select the position(s) of sites"
        return False

    def is_any_position_defined(self):
        for wp in self.wyckoff_positions:
            if not self.checkboxes.get(wp.letter, tk.BooleanVar()).get():
                continue
            return True
        return False

    def update_ok_button_state(self):
        warning = self.validate()
        if warning:
            self.warning_label.pack(side="top", fill="x", before=self.ok_button)
            self.warning_label.config(text = warning)
            self.ok_button.state(["disabled"])
        else:
            self.ok_button.state(["!disabled"])
            self.warning_label.pack_forget()

    def create_layout(self):
        main_frame = ttk.Frame(self)
        main_frame.pack(fill="both", expand=True, padx=4, pady=4)

        # --- Left column: spacegroup list ---
        left_frame = ttk.Frame(main_frame)
        left_frame.pack(side="left", fill="y", padx=(0, 4))

        filter_frame = ttk.Frame(left_frame)
        filter_frame.pack(fill="x", pady=(0, 4))
        ttk.Label(filter_frame, text="System:").pack(side="left")
        systems = ["All", "triclinic", "monoclinic", "orthorhombic",
                   "tetragonal", "trigonal", "hexagonal", "cubic"]
        ttk.OptionMenu(filter_frame, self.system_var, self.system_var.get(), *systems,
                       command=lambda e: self.update_list()).pack(side="left", padx=4)
        ttk.Label(filter_frame, text="Search:").pack(side="left", padx=(8, 0))
        ttk.Entry(filter_frame, textvariable=self.search_var, width=10).pack(side="left")
        self.search_var.trace_add("write", lambda *args: self.update_list())

        tree_frame = ttk.Frame(left_frame)
        tree_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tree_frame, columns=("ID", "Symbol"), show="headings")
        self.tree.heading("ID", text="ID")
        self.tree.heading("Symbol", text="Symbol")
        self.tree.column("ID", width=60, anchor="center")
        self.tree.column("Symbol", width=140, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        # --- Middle column: Wyckoff checkboxes ---
        middle_frame = ttk.Frame(main_frame)
        middle_frame.pack(side="left", fill="y", padx=(0, 4), expand=False)

        checkbox_frame = ttk.LabelFrame(middle_frame, text="Wyckoff sites positions (multiplicity)")
        checkbox_frame.pack(fill="both", expand=True, pady=(0, 6))
        canvas_box = tk.Canvas(checkbox_frame)
        scrollbar = ttk.Scrollbar(checkbox_frame, orient="vertical", command=canvas_box.yview)
        self.checkbox_container = ttk.Frame(canvas_box)
        self.checkbox_container.bind(
            "<Configure>", lambda e: canvas_box.configure(scrollregion=canvas_box.bbox("all"))
        )
        canvas_box.create_window((0, 0), window=self.checkbox_container, anchor="nw")
        canvas_box.configure(yscrollcommand=scrollbar.set)
        canvas_box.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # --- Right column: lattice + visualization ---
        right_frame = ttk.Frame(main_frame)
        right_frame.pack(side="left", fill="both", expand=True)

        # Lattice parameter frame (above plot)
        self.lattice_frame = ttk.LabelFrame(right_frame, text="Lattice parameters")
        self.init_lattice_frame()

        self.fig = plt.Figure(figsize=(5, 5))
        self.ax = self.fig.add_subplot(111, projection="3d")
        self.canvas = FigureCanvasTkAgg(self.fig, master=right_frame)
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.pack(fill="both", expand=True)
        self.canvas_widget.pack_forget()  # 🔹 hidden at startup

        btn_frame = ttk.Frame(right_frame)
        btn_frame.pack(fill="x", pady=(6, 0), side="bottom")

        self.warning_label = tk.Label(
          btn_frame,
          text="Choose a spacegroup",
          fg="red",
          bg="white",
          font=("Arial", 13)
        )
        self.warning_label.pack(side="top", fill="x")  # fill horizontally

        self.ok_button = ttk.Button(btn_frame, text="OK", command=self.confirm, state="disabled")
        self.ok_button.pack(fill="x", pady=2)
        ttk.Button(btn_frame, text="Cancel", command=self.cancel).pack(fill="x", pady=2)

        self.lattice_matrix_frame = ttk.LabelFrame(right_frame, text="Lattice vectors (Å)")
        self.lattice_matrix_frame.pack(fill="x", pady=(6, 6), side="bottom")
        
        # 3x3 matrix of labels
        self.lattice_labels = []
        for i in range(3):
            row = ttk.Frame(self.lattice_matrix_frame)
            row.pack(fill="x", padx=10)
            row_labels = []
            for j in range(3):
                lbl = ttk.Label(row, text="-", width=10, anchor="e")
                lbl.pack(side="left", padx=4)
                row_labels.append(lbl)
            self.lattice_labels.append(row_labels)

    def is_lattice_defined(self):
        system = self.selected_group.lattice_type
        fixed = lattice_fixed_params.get(system, {})

        try:
            for key, (var, ent) in self.lattice_entries.items():
                if key in fixed:
                    continue
                if var.get() <= 0.:
                    return False
            return True
        except:
            return False

    def update_lattice_matrix_frame(self):
        lattice = self.lattice
        if lattice is False or not self.is_lattice_defined():
            for i in range(3):
                for j in range(3):
                    self.lattice_labels[i][j].config(text="–")
            return

        for i in range(3):
            for j in range(3):
                val = lattice[i, j]
                self.lattice_labels[i][j].config(text=f"{val:8.3f}")

    def update_list(self, *args):
        self.tree.delete(*self.tree.get_children())
        system = self.system_var.get()
        search = self.search_var.get().strip().lower()

        for g in self.spacegroups:
            sym = g.symbol
            num = g.number
            if system != "All" and system != g.lattice_type: continue
            if search and search not in str(num) and search not in sym.lower():
                continue
            self.tree.insert("", "end", values=(g.number, sym))

    def on_select(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        values = self.tree.item(sel[0])["values"]
        sg_no = int(values[0])
        self.selected_group = Group(sg_no)
        self.wyckoff_positions = sorted(self.selected_group.Wyckoff_positions, key=lambda wp: wp.letter)
        self.update_lattice_frame()
        self.update_checkboxes()
        self.on_lattice_changed()
        self.canvas_widget.pack(fill="both", expand=True)

    def update_lattice_frame(self):
        if not self.selected_group:
            self.lattice_frame.pack_forget()
        self.lattice_frame.pack(fill="x", pady=(0, 6))

        system = self.selected_group.lattice_type
        fixed = lattice_fixed_params.get(system, {})

        for key, (var, ent) in self.lattice_entries.items():
            var.trace_remove("write", var._trace_id)
            #ent.delete(0, 'end')
            if key in fixed:
                #ent.insert(0, fixed[key])
                ent.state(["disabled"])
                var.set(fixed[key])
            else:
                ent.state(["!disabled"])
                if key in self.lattice_params:
                    var.set(str(self.lattice_params[key]))
                    #ent.insert(0, str(self.lattice_params[key]))
                else:
                    var.set("")
            var._trace_id = var.trace_add("write", var._trace_event)

    def init_lattice_frame(self):
        if not self.selected_group:
            self.lattice_frame.pack_forget()
        self.lattice_entries = {}

        def change(key, var):
            try:
              val = var.get()
              self.lattice_params[key] = val
            except:
              pass
            self.on_lattice_changed()

        def add(label, row):
            ttk.Label(row, text=key + ":").pack(side="left", padx=3)
            var = tk.DoubleVar()
            ent = ttk.Entry(row, textvariable=var, width=6)
            ent.pack(side="left", padx=3)
            var._trace_event = lambda *args, var=var, key=label: change(key, var)
            var._trace_id = var.trace_add("write", var._trace_event)
            self.lattice_entries[key] = var, ent

        # First row: a,b,c
        row1 = ttk.Frame(self.lattice_frame)
        row1.pack(fill="x", pady=2)
        for key in ["a", "b", "c"]:
            add(key, row1)

        # Second row: alpha,beta,gamma
        row2 = ttk.Frame(self.lattice_frame)
        row2.pack(fill="x", pady=2)
        for key in ["α", "β", "γ"]:
            add(key, row2)

        def units_change(units):
            self.units = units
            self.on_lattice_changed()
        combo = create_units_combo(self.lattice_frame, units_change)
        combo.pack(fill='x', side='bottom')

    def on_lattice_changed(self):
        if not self.selected_group:
            return
        # Update only user-entered values
        params = complete_lattice_params(self.selected_group, self.lattice_params)
        try:
            self.lattice = lattice_from_params(params)
            self.lattice*= self.units
        except:
            self.lattice = False
        self.draw_spacegroup()
        self.update_lattice_matrix_frame()
        self.update_ok_button_state()

    def toggle_wp_entries(self, wp):
        """Enable/disable input boxes based on checkbox."""
        active = self.checkboxes[wp.letter].get()
        for ent, _ in self.wp_vars[wp.letter]:
            if active:
                ent.state(["!disabled"])
            else:
                ent.state(["disabled"])
        self.draw_spacegroup()
        self.update_ok_button_state()

    def draw_spacegroup(self):
        self.ax.clear()
        
        if not self.selected_group:
            return

        if self.lattice is False:
            return

        plot_lattice(self.ax, self.lattice)
        pos = (
            self.get_all_wyckoff_positions(wp)
            for wp in self.wyckoff_positions
            if self.checkboxes.get(wp.letter, tk.BooleanVar()).get()
        )
        plot_sites_in_lattice(self.ax, self.lattice, pos)
        self.canvas.draw_idle()        

    def get_all_wyckoff_positions(self, wp):
        params = self.positions.get(wp.letter, [])+[0.,0.,0.]
        return wp.get_all_positions(wp.get_position_from_free_xyzs(params))

    def update_checkboxes(self):
        for w in self.checkbox_container.winfo_children():
            w.destroy()
        if not self.selected_group:
            return

        self.checkboxes = {}
        self.wp_vars = {}
        labels = ['x', 'y', 'z']

        for wp in self.wyckoff_positions:
            var = tk.BooleanVar(value=False)
            self.checkboxes[wp.letter] = var
            frame = ttk.Frame(self.checkbox_container)
            frame.pack(anchor="w", fill="x", pady=(2,0), padx=(10, 0))
            chk = ttk.Checkbutton(frame, text=f"{wp.letter} ({wp.multiplicity}): {wp.gen_pos().as_xyz_str()}", variable=var,
                                  command=lambda wp=wp: self.toggle_wp_entries(wp))
            chk.pack(side="left")

            # If DOF > 0, add entries
            dofs = wp.get_dof()
            entries = []
            if dofs > 0:

                frozen_axis = iter(wp.get_frozen_axis() + [3,])
                f_axis = next(frozen_axis)

                entry_frame = ttk.Frame(self.checkbox_container)
                entry_frame.pack(anchor="w", padx=20)

                i=0
                for axis, lbl in enumerate(labels):
                    if axis == f_axis:
                        f_axis = next(frozen_axis)
                        continue

                    ttk.Label(entry_frame, text=f"{lbl}=").pack(side="left", padx=(15,0))
                    evar = tk.DoubleVar(value=(self.positions.get(wp.letter,[]) + [0.,0.,0.])[i])
                    ent = ttk.Entry(entry_frame, textvariable=evar, width=5)
                    ent.pack(side="left", padx=2)
                    ent.state(["disabled"])  # start grayed outa

                    def update_val(*args, wp_letter=wp.letter, idx=i, var=evar):
                        vals = self.positions.get(wp_letter, [])
                        if len(vals) < dofs:
                            vals += [0.]*dofs
                        vals[idx] = var.get()
                        self.positions[wp_letter] = vals
                        self.draw_spacegroup()
                    i+=1
                    evar.trace_add("write", update_val)
                    entries.append( (ent, evar) )

            self.wp_vars[wp.letter] = entries


    def confirm(self):
        # If validation returns a message -> not valid
        if self.validate():
            return

        sg_number = int(self.selected_group.number)

        positions = {
            wp.letter: self.get_all_wyckoff_positions(wp) 
            for wp in self.selected_group.Wyckoff_positions
            if self.checkboxes.get(wp.letter, tk.BooleanVar()).get()
        }

        cell_obj = Cell(self.lattice)

        self.selected_group = {
            'spacegroup': sg_number,
            'cell': cell_obj,
            'wyckoff_positions': positions,
        }
        self.destroy()

    def cancel(self):
        self.selected_group = None
        self.destroy()



def select_spacegroup(master=None, spacegroup=None, cell=None, positions=None):
    """
    Open selector. Optional initialization:
      - spacegroup: int or pyxtal Group
      - cell: ASE Cell-like (3x3 array or ase.cell.Cell) with lattice vectors as rows
      - positions: dict mapping Wyckoff letter -> list of fractional positions as returned by
                   get_all_wyckoff_positions(wp), e.g.
                   {'a': [[x1,y1,z1], [x2,y2,z2], ...], 'b': [...], ...}
    """
    selector = SpaceGroupSelector(master)

    # initialize spacegroup
    if spacegroup is not None:
        sg = spacegroup if isinstance(spacegroup, Group) else Group(int(spacegroup))
        selector.selected_group = sg

        # initialize lattice params from provided cell (expecting vectors as rows)
        if cell is not None:
            lat = np.asarray(cell)
            # ensure (3,3)
            if lat.shape == (3,):
                lat = lat.reshape((3,1))
            def angle(u, v):
                u = np.array(u); v = np.array(v)
                cosv = np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v))
                return float(np.degrees(np.arccos(np.clip(cosv, -1.0, 1.0))))
            a = float(np.linalg.norm(lat[0]))
            b = float(np.linalg.norm(lat[1]))
            c = float(np.linalg.norm(lat[2]))
            alpha = angle(lat[1], lat[2])
            beta = angle(lat[0], lat[2])
            gamma = angle(lat[0], lat[1])
            selector.lattice_params.update({'a': a, 'b': b, 'c': c, 'α': alpha, 'β': beta, 'γ': gamma})

        # update UI to reflect selected_group
        selector.update_lattice_frame()
        selector.update_checkboxes()

        # If positions provided, they are full fractional positions per letter (no guessing needed)
        if positions:
            def positions_match(prov, comp, atol=1e-6):
                if len(prov) != len(comp):
                    return False
                used = [False] * len(comp)
                for p in prov:
                    matched = False
                    for i, c in enumerate(comp):
                        if used[i]:
                            continue
                        if np.allclose(p, c, atol=atol):
                            used[i] = True
                            matched = True
                            break
                    if not matched:
                        return False
                return True

            for letter, prov_list in positions.items():
                if letter not in selector.checkboxes:
                    continue
                # enable checkbox and entry widgets
                selector.checkboxes[letter].set(True)
                try:
                    wp = next(w for w in selector.selected_group.Wyckoff_positions if w.letter == letter)
                except StopIteration:
                    continue
                selector.toggle_wp_entries(wp)

                prov_arr = np.array(prov_list, dtype=float)
                frozen = wp.get_frozen_axis()
                free_axes = [ax for ax in (0, 1, 2) if ax not in frozen]

                found = False
                # try candidates from provided positions to infer free DOF values
                for cand in prov_arr:
                    dof_guess = [float(cand[ax]) for ax in free_axes]
                    selector.positions[letter] = list(dof_guess)
                    # update UI entry variables
                    for idx, (_, evar) in enumerate(selector.wp_vars.get(letter, [])):
                        try:
                            evar.set(dof_guess[idx])
                        except Exception:
                            pass
                    comp = np.array(selector.get_all_wyckoff_positions(wp))
                    if positions_match(prov_arr, comp, atol=1e-6):
                        found = True
                        break

                if not found:
                    # fallback: use first provided position's coords on free axes
                    if len(prov_arr) > 0:
                        cand = prov_arr[0]
                        dof_guess = [float(cand[ax]) for ax in free_axes]
                        selector.positions[letter] = list(dof_guess)
                        for idx, (_, evar) in enumerate(selector.wp_vars.get(letter, [])):
                            try:
                                evar.set(dof_guess[idx])
                            except Exception:
                                pass

        # Recompute lattice & redraw
        selector.on_lattice_changed()
        selector.canvas_widget.pack(fill="both", expand=True)

    # wait for dialog to close
    if master is None:
        selector.wait_window(selector)
    else:
        master.wait_window(selector)
    return selector.selected_group
