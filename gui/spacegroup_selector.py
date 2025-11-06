import numpy as np
import tkinter as tk
from tkinter import ttk
from pyxtal.symmetry import Group
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
from ase.cell import Cell
import threading


from .lattice import plot_lattice, plot_sites_in_lattice
from ..physics.pyxtal_utils import complete_lattice_params, lattice_fixed_params, lattice_from_params
from ..physics.wyckoff_data import wyckoff_data
from .common import create_units_combo

# Keep (and reuse) one dialog instance per master
try:
    from weakref import WeakKeyDictionary
    _SG_SELECTOR_INSTANCES = WeakKeyDictionary()
except Exception:
    _SG_SELECTOR_INSTANCES = {}
_SG_DEFAULT_KEY = object()

class SpaceGroupSelector(tk.Toplevel):
    def __init__(self, master=None, back: bool = False):
        super().__init__(master)
        self.title("Select Space Group")
        self.geometry("1000x650")
        self.selected_group = None
        # when True, show Back button next to Cancel and return 'back' on Back
        self._allow_back = bool(back)
        # signal to wait on instead of destroying the window
        self._done = tk.BooleanVar(value=False)

        self.system_var = tk.StringVar(value="All")
        self.search_var = tk.StringVar(value="")
        self.wp_vars = {}
        self.lattice_params = {}  # user-entered only
        self.positions = {}
        self.units = 1.

        self.spacegroups = [Group(i) for i in range(1, 231)]

        self.create_layout()
        self.update_list()
        # render coordination
        self._draw_counter = 0  # increasing token to ignore stale renders
        # cache UI widgets for Wyckoff positions to reuse instead of recreating
        self._wp_widgets = {}  # letter -> {frame, check, var, entry_frame, entries: [pair dicts]}
        # suppress UI-change traces when bulk-updating variables
        self._suspend_update = False
        # background render worker (single thread) to avoid spawning per redraw
        self._worker_event = threading.Event()
        self._worker_stop = threading.Event()
        self._worker_lock = threading.Lock()
        self._latest_request = None  # dict snapshot for rendering
        self._worker = threading.Thread(target=self._render_worker_loop, daemon=True)
        self._worker.start()

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
        # show lattice type as a third column
        self.tree = ttk.Treeview(tree_frame, columns=("ID", "Symbol", "Lattice"), show="headings")
        self.tree.heading("ID", text="ID")
        self.tree.heading("Symbol", text="Symbol")
        self.tree.heading("Lattice", text="Lattice")
        self.tree.column("ID", width=40, anchor="center")
        self.tree.column("Symbol", width=110, anchor="w")
        self.tree.column("Lattice", width=120, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        # Buttons below the tree
        left_buttons = ttk.Frame(left_frame)
        left_buttons.pack(fill="x", pady=(4, 0))
        if self._allow_back:
            btn_row = ttk.Frame(left_buttons)
            btn_row.pack(fill="x")
            ttk.Button(btn_row, text="Back", command=self.back).pack(side="left", expand=True, fill="x", padx=(0, 4))
            ttk.Button(btn_row, text="Cancel", command=self.cancel).pack(side="left", expand=True, fill="x")
        else:
            ttk.Button(left_buttons, text="Cancel", command=self.cancel).pack(fill="x")


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
        # Use grid in the container so checkboxes and entry rows align vertically
        try:
            self.checkbox_container.grid_columnconfigure(0, weight=0, minsize=0)
            self.checkbox_container.grid_columnconfigure(1, weight=1, minsize=0)
        except Exception:
            pass

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
            lattice = g.lattice_type
            if system != "All" and system != lattice: continue
            if search and search not in str(num) and search not in sym.lower() and search not in str(lattice).lower():
                continue
            # keep number at index 0 so selection logic (values[0]) remains valid
            self.tree.insert("", "end", values=(g.number, sym, lattice))

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
        """Backward-compatible: toggle by wp object; delegates by letter."""
        self.toggle_wp_entries_by_letter(wp.letter)

    def toggle_wp_entries_by_letter(self, letter: str):
        """Show/hide the values row for a Wyckoff site based on checkbox state."""
        if letter not in self._wp_widgets:
            return
        widget = self._wp_widgets[letter]
        active = self.checkboxes.get(letter, tk.BooleanVar()).get()
        entry_frame = widget.get('entry_frame')
        entries = widget.get('entries', [])
        # show the entry frame only if active and entries exist
        if entry_frame is not None:
            if active and len(entries) > 0:
                try:
                    entry_frame.grid()
                except Exception:
                    pass
            else:
                try:
                    entry_frame.grid_remove()
                except Exception:
                    pass
        self.draw_spacegroup()
        self.update_ok_button_state()

    def draw_spacegroup(self):
        """Send latest state to single background worker and draw via Tk idle."""
        token = self._next_draw_token()

        # if invalid/empty state, clear plot immediately (and invalidate any worker result)
        if not self.selected_group or self.lattice is False:
            def _clear_if_latest(tok=token):
                if tok != self._draw_counter:
                    return
                self.ax.clear()
                self.after_idle(lambda: self.canvas.draw())
            self.after_idle(_clear_if_latest)
            # also notify worker that nothing to render
            with self._worker_lock:
                self._latest_request = None
            self._worker_event.set()
            return

        # build snapshot for the worker
        snap = self._snapshot_for_render(token)
        with self._worker_lock:
            self._latest_request = snap
        self._worker_event.set()

    def _snapshot_for_render(self, token):
        lattice_copy = np.array(self.lattice, dtype=float, copy=True)
        selected_wps = [
            wp for wp in getattr(self, 'wyckoff_positions', [])
            if self.checkboxes.get(wp.letter, tk.BooleanVar()).get()
        ]
        pos_snapshot = {k: list(v) for k, v in self.positions.items()}
        return {
            'token': token,
            'lattice': lattice_copy,
            'wyckoffs': selected_wps,
            'positions': pos_snapshot,
        }

    def _render_worker_loop(self):
        while not self._worker_stop.is_set():
            self._worker_event.wait()
            if self._worker_stop.is_set():
                break
            # fetch latest request and coalesce many triggers
            with self._worker_lock:
                req = self._latest_request
                self._latest_request = None
                # reset event so we can block again; if another request came in
                # between lock and clear, the next iteration will handle it
                self._worker_event.clear()
            if not req:
                # nothing to render (e.g., invalid state)
                continue

            tok = req['token']
            lattice = req['lattice']
            wps = req['wyckoffs']
            pos_snap = req['positions']

            # compute the heavy data off the main thread
            try:
                positions_list = []
                for wp in wps:
                    params = pos_snap.get(wp.letter, []) + [0.0, 0.0, 0.0]
                    all_pos = wp.get_all_positions(wp.get_position_from_free_xyzs(params))
                    positions_list.append(np.array(all_pos, dtype=float))
            except Exception:
                positions_list = []

            def apply_if_latest(token=tok, lattice_copy=lattice, pos_list=positions_list):
                if token != self._draw_counter:
                    return
                self.ax.clear()
                plot_lattice(self.ax, lattice_copy)
                if pos_list:
                    plot_sites_in_lattice(self.ax, lattice_copy, pos_list)
                # perform the canvas draw on idle
                self.after_idle(lambda: self.canvas.draw())

            # marshal to main thread
            try:
                self.after(0, apply_if_latest)
            except Exception:
                pass

    def _next_draw_token(self):
        self._draw_counter += 1
        return self._draw_counter

    def destroy(self):
        # stop the worker thread cleanly
        try:
            self._worker_stop.set()
            self._worker_event.set()
        except Exception:
            pass
        return super().destroy()

    def get_all_wyckoff_positions(self, wp):
        params = self.positions.get(wp.letter, [])+[0.,0.,0.]
        return wp.get_all_positions(wp.get_position_from_free_xyzs(params))

    def update_checkboxes(self):
        if not self.selected_group:
            return

        if not hasattr(self, 'checkboxes'):
            self.checkboxes = {}
        if not hasattr(self, 'wp_vars'):
            self.wp_vars = {}

        labels = ['x', 'y', 'z']
        current_letters = {wp.letter for wp in self.wyckoff_positions}

        # Hide rows for letters no longer present
        for letter, widget in list(self._wp_widgets.items()):
            if letter not in current_letters:
                if widget.get('entry_frame') is not None:
                    try:
                        widget['entry_frame'].grid_remove()
                    except Exception:
                        pass
                if widget.get('check') is not None:
                    try:
                        widget['check'].grid_remove()
                    except Exception:
                        pass

        # Ensure frames exist and update content for current WPs

        pos_label = wyckoff_data[self.selected_group.number]
        for row_index, wp in enumerate(self.wyckoff_positions):
            letter = wp.letter
            widget = self._wp_widgets.get(letter)
            if widget is None:
                widget = {}
                widget['row'] = row_index
                var = self.checkboxes.get(letter, tk.BooleanVar(value=False))
                self.checkboxes[letter] = var
                chk = ttk.Checkbutton(
                    self.checkbox_container,
                    text=f"{letter} ({wp.multiplicity}): {pos_label[letter].label}",
                    variable=var,
                    command=lambda letter=letter: self.toggle_wp_entries_by_letter(letter)
                )
                chk.grid(row=row_index, column=0, sticky="w", padx=(10,0), pady=(2,0))
                widget['check'] = chk
                widget['var'] = var

                # values row sits in column 1 of the same row to align across rows
                entry_frame = ttk.Frame(self.checkbox_container)
                widget['entry_frame'] = entry_frame
                widget['entries'] = []  # list of pair dicts
                entry_frame.grid(row=row_index, column=1, sticky="w", padx=(6,0), pady=(2,0))
                self._wp_widgets[letter] = widget
            else:
                # ensure correct row assignment and visibility
                widget['row'] = row_index
                try:
                    widget['check'].grid(row=row_index, column=0, sticky="w", padx=(10,0), pady=(2,0))
                    widget['entry_frame'].grid(row=row_index, column=1, sticky="w", padx=(6,0), pady=(2,0))
                except Exception:
                    pass
                # update label text in case it changed
                widget['check'].configure(text=f"{letter} ({wp.multiplicity}): {wp.gen_pos().as_xyz_str()}")

            # compute free axes and desired number of inputs
            frozen_axes = pos_label[letter].frozen_axes
            free_axes = [ax for ax in (0,1,2) if ax not in frozen_axes]
            dofs = len(free_axes)

            # Prepare values from model state
            vals = list(self.positions.get(letter, []))
            if len(vals) < dofs:
                vals += [0.0] * (dofs - len(vals))

            # ensure entry_frame exists and is attached as needed
            entry_frame = widget['entry_frame']
            # keep columns tight: no expansion spacing
            for c in range(6):
                try:
                    entry_frame.grid_columnconfigure(c, weight=0, minsize=0)
                except Exception:
                    pass
            # create or reuse entry pairs; keep 3 slots (x,y,z) for fixed columns
            pairs = widget['entries']

            # grow pairs up to 3 (for x, y, z)
            while len(pairs) < 3:
                lbl = ttk.Label(entry_frame, text="x=", width=2, anchor="e")
                evar = tk.DoubleVar(value=0.0)
                ent = ttk.Entry(entry_frame, textvariable=evar, width=6)

                # create pair first so we can reference it in the callback closure
                pair = {'label': lbl, 'entry': ent, 'var': evar, 'axis': None}

                # dynamic handler factory: computes index based on current free axes and this pair's axis
                def make_update_handler(p_ref):
                    def update_val(*args, wp_letter=letter, var=p_ref['var']):
                        if self._suspend_update:
                            return
                        try:
                            axis = p_ref.get('axis')
                            if axis is None:
                                return
                            frozen_axes = wyckoff_data[self.selected_group.number][wp_letter].frozen_axes
                            free_axes_now = [ax for ax in (0, 1, 2) if ax not in frozen_axes]
                            d = len(free_axes_now)
                            vals = list(self.positions.get(wp_letter, []))
                            if len(vals) < d:
                                vals += [0.0] * (d - len(vals))
                            idx_now = free_axes_now.index(axis)
                            vals[idx_now] = var.get()
                            self.positions[wp_letter] = vals
                        except Exception:
                            return
                        self.draw_spacegroup()
                    return update_val

                handler = make_update_handler(pair)
                tid = evar.trace_add("write", handler)
                pair['update_handler'] = handler
                pair['trace_id'] = tid
                pairs.append(pair)

            # hide all pairs to start clean
            for p in pairs:
                try:
                    p['label'].grid_remove()
                    p['entry'].grid_remove()
                except Exception:
                    pass

            # configure and show only the free axes, at fixed columns (x->0/1, y->2/3, z->4/5)
            _prev_suppress = self._suspend_update
            self._suspend_update = True
            for i, ax in enumerate(free_axes):
                pair = pairs[ax]  # index pairs by axis (0:x,1:y,2:z)
                pair['axis'] = ax
                pair['label'].configure(text=f"{labels[ax]}=")
                # set value without triggering many redraws
                try:
                    # temporarily remove trace to avoid firing handler
                    if 'trace_id' in pair and pair['trace_id'] is not None:
                        try:
                            pair['var'].trace_remove('write', pair['trace_id'])
                        except Exception:
                            pass
                    pair['var'].set(vals[i])
                    # restore the trace
                    tid = pair['var'].trace_add('write', pair.get('update_handler'))
                    pair['trace_id'] = tid
                except Exception:
                    pass
                # fixed column placement by axis
                pair['label'].grid(row=0, column=2*ax, padx=(4, 2), pady=(1,1), sticky="e")
                pair['entry'].grid(row=0, column=2*ax+1, padx=(2, 4), pady=(1,1), sticky="w")
            self._suspend_update = _prev_suppress

            # expose wp_vars compatibility in free-axes order
            self.wp_vars[letter] = [(pairs[ax]['entry'], pairs[ax]['var']) for ax in free_axes]

            # finally show/hide the whole entry row depending on active + dofs
            active = self.checkboxes.get(letter, tk.BooleanVar()).get()
            if dofs > 0 and active:
                try:
                    entry_frame.grid()
                except Exception:
                    pass
            else:
                try:
                    entry_frame.grid_remove()
                except Exception:
                    pass

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
        # don't destroy; just hide and signal completion
        self.withdraw()
        self._done.set(True)

    def cancel(self):
        self.selected_group = None
        self.withdraw()
        self._done.set(True)

    def back(self):
        # Return a sentinel value so the caller can go back to previous step
        self.selected_group = 'back'
        self.withdraw()
        self._done.set(True)

    # --- setup API to (re)initialize the dialog without recreating it ---
    def setup(self, spacegroup=None, cell=None, wyckoff_positions=None, back: bool = False):
        """Configure dialog state and UI for a new or repeated use.

        - If any of spacegroup/cell/wyckoff_positions is None, clear related UI/data.
        - If provided, initialize from values (accepts int or pyxtal Group for spacegroup,
          ASE Cell-like for cell, and a dict of Wyckoff letter -> list of fractional positions).
        - back toggles whether Back button should be presented for this session.
        """
        # update back flag (UI was built for the initial value; assume consistent usage per instance)
        self._allow_back = bool(back)

        # Reset per-session state
        self.lattice_params = {}
        self.positions = {}

        # Clear selection if no spacegroup
        if spacegroup is None:
            self.selected_group = None
            # Reset UI areas
            try:
                self.lattice_frame.pack_forget()
            except Exception:
                pass
            try:
                self.canvas_widget.pack_forget()
            except Exception:
                pass
            # Clear lattice matrix labels
            try:
                for i in range(3):
                    for j in range(3):
                        self.lattice_labels[i][j].config(text="–")
            except Exception:
                pass
            # Hide all checkbox rows
            try:
                for widget in self._wp_widgets.values():
                    if widget.get('entry_frame') is not None:
                        widget['entry_frame'].grid_remove()
                    if widget.get('check') is not None:
                        widget['check'].grid_remove()
            except Exception:
                pass
            # Update list and warning/OK
            self.update_list()
            try:
                self.warning_label.config(text="Choose a spacegroup")
                self.ok_button.state(["disabled"]) 
            except Exception:
                pass
            return

        # Initialize spacegroup
        sg = spacegroup if isinstance(spacegroup, Group) else Group(int(spacegroup))
        self.selected_group = sg

        # If cell is provided, set lattice params from it
        if cell is not None:
            lat = np.asarray(cell)
            if lat.shape == (3,):
                lat = lat.reshape((3, 1))
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
            self.lattice_params.update({'a': a, 'b': b, 'c': c, 'α': alpha, 'β': beta, 'γ': gamma})

        # Reflect selection in UI
        self.update_lattice_frame()
        self.update_checkboxes()

        # Initialize free DOF values from provided full Wyckoff positions
        if wyckoff_positions:
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

            for letter, prov_list in wyckoff_positions.items():
                if letter not in self.checkboxes:
                    continue
                # enable checkbox and entry widgets
                self.checkboxes[letter].set(True)
                try:
                    wp = next(w for w in self.selected_group.Wyckoff_positions if w.letter == letter)
                except StopIteration:
                    continue
                self.toggle_wp_entries(wp)

                prov_arr = np.array(prov_list, dtype=float)
                frozen = wp.get_frozen_axis()
                free_axes = [ax for ax in (0, 1, 2) if ax not in frozen]

                found = False
                for cand in prov_arr:
                    dof_guess = [float(cand[ax]) for ax in free_axes]
                    self.positions[letter] = list(dof_guess)
                    for idx, (_, evar) in enumerate(self.wp_vars.get(letter, [])):
                        try:
                            evar.set(dof_guess[idx])
                        except Exception:
                            pass
                    comp = np.array(self.get_all_wyckoff_positions(wp))
                    if positions_match(prov_arr, comp, atol=1e-6):
                        found = True
                        break
                if not found and len(prov_arr) > 0:
                    cand = prov_arr[0]
                    dof_guess = [float(cand[ax]) for ax in free_axes]
                    self.positions[letter] = list(dof_guess)
                    for idx, (_, evar) in enumerate(self.wp_vars.get(letter, [])):
                        try:
                            evar.set(dof_guess[idx])
                        except Exception:
                            pass

        # Recompute lattice & redraw
        self.on_lattice_changed()
        self.canvas_widget.pack(fill="both", expand=True)



def select_spacegroup(master=None, spacegroup=None, cell=None, wyckoff_positions=None, back: bool = False):
    """
    Open selector. Optional initialization:
      - spacegroup: int or pyxtal Group
      - cell: ASE Cell-like (3x3 array or ase.cell.Cell) with lattice vectors as rows
      - positions: dict mapping Wyckoff letter -> list of fractional positions as returned by
                   get_all_wyckoff_positions(wp), e.g.
                   {'a': [[x1,y1,z1], [x2,y2,z2], ...], 'b': [...], ...}
    """
    # reuse or create one instance per master
    key = master if master is not None else _SG_DEFAULT_KEY
    selector = _SG_SELECTOR_INSTANCES.get(key)
    if selector is None or not int(selector.winfo_exists()):
        selector = SpaceGroupSelector(master, back=back)
        _SG_SELECTOR_INSTANCES[key] = selector
    # (Re)setup state and show dialog
    selector.setup(spacegroup=spacegroup, cell=cell, wyckoff_positions=wyckoff_positions, back=back)
    selector._done.set(False)
    try:
        selector.deiconify()
        selector.lift()
        selector.focus_set()
    except Exception:
        pass
    # wait until one of confirm/cancel/back signals completion
    if master is None:
        selector.wait_variable(selector._done)
    else:
        master.wait_variable(selector._done)
    return selector.selected_group
