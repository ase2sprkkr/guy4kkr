import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Optional
import numpy as np
import threading
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt

from pyxtal.symmetry import Group
from ase.cell import Cell

from .lattice import plot_lattice
from ..physics.wyckoff_data import wyckoff_data
from .element_selector import select_element, ELEMENT_DATA


_VALID_SYMBOLS = set(d.get('symbol') for d in ELEMENT_DATA.values() if isinstance(d, dict) and d.get('symbol'))


try:
    from weakref import WeakKeyDictionary
    _EA_SELECTOR_INSTANCES = WeakKeyDictionary()
except Exception:
    _EA_SELECTOR_INSTANCES = {}
_EA_DEFAULT_KEY = object()


class ElementAssignmentDialog(tk.Toplevel):
    """
    Dialog to assign elements and occupancies to already-selected Wyckoff sites.

    Inputs may be provided either as separate arguments or as the dict returned by
    select_spacegroup: {'spacegroup': int, 'cell': Cell, 'wyckoff_positions': dict(letter -> [[x,y,z], ...])}.

    Result mirrors the select_spacegroup dict with an additional 'site_elements' mapping:
        { letter: [{ 'symbol': 'Fe', 'occupancy': 0.8 }, ...], ... }
    """

    def __init__(self, master=None, back: bool = False):
        super().__init__(master)
        self.title("Assign elements to sites")
        self.geometry("1000x650")
        self._suspend = False
        # when True, show Back button next to Cancel and return 'back' on Back
        self._allow_back = bool(back)
        # completion signal (we hide instead of destroy)
        self._done = tk.BooleanVar(value=False)

        # initial empty inputs; will be set via setup()
        self.sg_number: Optional[int] = None
        self.group: Optional[Group] = None
        self.cell: Optional[np.ndarray] = None
        self.positions: Dict[str, List[List[float]]] = {}

        # internal state: mapping letter -> list of {symbol, var_symbol, var_occ, frame}
        self.site_elements: Dict[str, List[dict]] = {}
        # start with empty state; setup() will populate

        self._draw_counter = 0
        self._worker_event = threading.Event()
        self._worker_stop = threading.Event()
        self._worker_lock = threading.Lock()
        self._latest: Optional[dict] = None
        self._highlight_letter: Optional[str] = None

        self._build_layout()
        self._start_worker()
        self._update_plot()

    # ---- UI construction ----
    def _build_layout(self):
        main = ttk.Frame(self)
        main.pack(fill="both", expand=True, padx=6, pady=6)
        main.columnconfigure(0, weight=6)  # left gets 70%
        main.columnconfigure(1, weight=4)  # right gets 30%

        # Define a larger, bold font style for glyph buttons
        try:
            style = ttk.Style(self)
            style.configure('Glyph.TButton', font=('TkDefaultFont', 14, 'bold'))
        except Exception:
            pass

        left = ttk.Frame(main)
        left.grid(row=0, column=0, sticky="nsew")

        ttk.Label(left, text="Wyckoff sites").pack(anchor="w")

        box = ttk.LabelFrame(left, text="Elements and occupancies")
        box.pack(fill="both", expand=True, pady=(4, 0))

        canvas = tk.Canvas(box)
        scroll = ttk.Scrollbar(box, orient="vertical", command=canvas.yview)
        self.list_container = ttk.Frame(canvas)
        self.list_container.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.list_container, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        # configure grid for alignment
        try:
            self.list_container.grid_columnconfigure(0, weight=0, minsize=0)  # letter + label
            self.list_container.grid_columnconfigure(1, weight=1)
        except Exception:
            pass

        # Right side: plot + buttons
        right = ttk.Frame(main)
        right.grid(row=0, column=1, sticky="nsew")
        

        self.fig = plt.Figure(figsize=(5, 5))
        self.ax = self.fig.add_subplot(111, projection="3d")
        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.pack(fill="both", expand=True)

        btns = ttk.Frame(right)
        btns.pack(fill="x")
        self.warning_label = tk.Label(btns, text="", fg="red")
        self.warning_label.pack(fill="x", pady=(4, 2))
        ttk.Button(btns, text="OK", command=self._on_ok).pack(fill="x")
        # Prepare both variants; we'll toggle visibility in setup()
        self._btns_back_row = ttk.Frame(btns)
        self._btns_back_row.pack(fill="x", pady=(4, 0))
        ttk.Button(self._btns_back_row, text="Back", command=self._on_back).pack(side="left", expand=True, fill="x", padx=(0, 4))
        ttk.Button(self._btns_back_row, text="Cancel", command=self._on_cancel).pack(side="left", expand=True, fill="x")
        self._btn_cancel_only = ttk.Button(btns, text="Cancel", command=self._on_cancel)
        self._btn_cancel_only.pack(fill="x", pady=(4, 0))
        # initial toggle
        self._toggle_back_cancel()

        self._populate_letters()

    def _populate_letters(self):
        # clear
        
        for child in list(self.list_container.children.values()):
            try:
                child.destroy()
            except Exception:
                pass

        pos_label = wyckoff_data.get(self.sg_number, {})

        def _fmt_coord(v: float) -> str:
            try:
                from fractions import Fraction
                frac = Fraction(float(v)).limit_denominator(12)
                if abs(float(frac) - float(v)) < 1e-8:
                    # exact simple fraction
                    if frac.denominator == 1:
                        return f"{frac.numerator}"
                    return f"{frac.numerator}/{frac.denominator}"
            except Exception:
                pass
            try:
                return f"{float(v):.3f}"
            except Exception:
                return str(v)
        row = 0
        for letter in sorted(self.positions.keys()):
            # label row
            # show actual representative coordinates instead of generic x,y,z
            try:
                rep = np.array(self.positions[letter][0], dtype=float)
                coords = ", ".join(_fmt_coord(x) for x in rep)
            except Exception:
                coords = (pos_label.get(letter).label if pos_label and letter in pos_label else '') or ''

            title = f"{letter} ({len(self.positions[letter])}): {coords}"
            lbl = ttk.Label(self.list_container, text=title)
            
            lbl.grid(row=row, column=0, sticky="nw", padx=(6, 4), pady=(4, 0))
            

            site_frame = ttk.Frame(self.list_container)
            # reduce left padding to move inputs left
            site_frame.grid(row=row, column=1, sticky="nw", padx=(0, 2), pady=(2, 2)); 

            # header inside site_frame
            header = ttk.Frame(site_frame)
            header.grid(row=0, column=0, sticky="w")
            # Normalize occupancy button in header
            ttk.Button(header, text="Normalize occupancy", command=lambda L=letter: self._normalize_letter(L)).grid(row=0, column=0, padx=(0, 6))
            
            # container for rows
            rows_cont = ttk.Frame(site_frame)
            rows_cont.grid(row=1, column=0, columnspan=3, sticky="w")
            rows_cont.grid_columnconfigure(0, weight=0)
            rows_cont.grid_columnconfigure(1, weight=0)
            rows_cont.grid_columnconfigure(2, weight=0)
            rows_cont.grid_columnconfigure(3, weight=0)
            rows_cont.grid_columnconfigure(4, weight=0)
            rows_cont.grid_columnconfigure(5, weight=0)

            site_frame.rows_container = rows_cont
            site_frame.letter = letter

            # initial: single row with default occupancy 1.0
            self._ensure_state_for_letter(letter)
            if not self.site_elements[letter]:
                self._add_element_row(letter, focus=True)
            else:
                for _ in list(self.site_elements[letter]):
                    # rebuild from state
                    self._add_element_row(letter, from_state=True)

            # footer with + Add below rows
            footer = ttk.Frame(site_frame)
            footer.grid(row=2, column=0, sticky="w", pady=(2, 0))
            ttk.Button(footer, text="+ Add", command=lambda L=letter: self._add_element_row(L, focus=True)).grid(row=0, column=0)

            row += 1

    def _ensure_state_for_letter(self, letter):
        self.site_elements.setdefault(letter, [])

    def _add_element_row(self, letter, focus=False, from_state=False):
        self._ensure_state_for_letter(letter)
        # find container widgets
        container = None
        for child in self.list_container.grid_slaves():
            try:
                if getattr(child, 'letter', None) == letter:
                    container = child
                    break
            except Exception:
                pass
        if container is None:
            return
        rows_cont = container.rows_container

        state_list = self.site_elements[letter]
        if not from_state:
            # default occupancy = max(0, 1 - sum(existing))
            occ_default = max(0.0, 1.0 - sum((item.get('var_occ').get() if isinstance(item.get('var_occ'), tk.DoubleVar) else float(item.get('occupancy', 0.0))) for item in state_list))
            occ_default = round(occ_default, 2)
            row_state = {
                'symbol': '',
                'occupancy': occ_default,
            }
            state_list.append(row_state)
        else:
            row_state = state_list[len([c for c in rows_cont.grid_slaves() if int(c.grid_info().get('row', 0)) >= 1])]

        r = len([c for c in rows_cont.grid_slaves() if int(c.grid_info().get('row', 0)) >= 1]) + 1
        # row frame to group all widgets for easy removal
        row_frame = ttk.Frame(rows_cont)
        row_frame.grid(row=r, column=0, columnspan=6, sticky='w')

        # element label + entry + chooser
        ttk.Label(row_frame, text='Element').grid(row=0, column=0, padx=(0, 2), pady=(2, 2), sticky='w')
        var_sym = tk.StringVar(value=row_state.get('symbol', ''))
        ent_sym = ttk.Entry(row_frame, textvariable=var_sym, width=8)
        ent_sym.grid(row=0, column=1, padx=(0, 2), pady=(2, 2), sticky='w')
        ent_sym.bind('<FocusIn>', lambda e, L=letter: self._highlight(L))
        # use an alchemy flask glyph if available
        ttk.Button(row_frame, text='⚛️', style='Glyph.TButton', width=2, command=lambda v=var_sym: self._choose_element(v)).grid(row=0, column=2, padx=(0, 6), pady=(2, 2), sticky='w')

        # occupancy label + entry
        ttk.Label(row_frame, text='Occupancy').grid(row=0, column=3, padx=(0, 4), pady=(2, 2), sticky='w')
        var_occ = tk.DoubleVar(value=row_state.get('occupancy', 0.0))
        ent_occ = ttk.Entry(row_frame, textvariable=var_occ, width=6)
        ent_occ.grid(row=0, column=4, padx=(0, 6), pady=(2, 2), sticky='w')
        ent_occ.bind('<FocusIn>', lambda e, L=letter: self._highlight(L))

        # remove row button (trash icon)
        del_btn = ttk.Button(row_frame, text='🗑', style='Glyph.TButton', width=2, command=lambda L=letter, rf=row_frame, vs=var_sym, vo=var_occ: self._remove_row(L, rf, vs, vo))
        del_btn.grid(row=0, column=5, padx=(0, 0), pady=(2, 2))

        # attach to state
        row_state.update({'var_sym': var_sym, 'var_occ': var_occ, 'ent_sym': ent_sym, 'ent_occ': ent_occ, 'frame': row_frame, 'del_btn': del_btn})

        # traces
        var_sym.trace_add('write', lambda *a, L=letter, v=var_sym: self._on_symbol_change(L, v))
        var_occ.trace_add('write', lambda *a, L=letter: self._validate_letter(L))

        if focus:
            try:
                ent_sym.focus_set()
            except Exception:
                pass
        # validate after creation
        self._validate_letter(letter)
        self._update_delete_state(letter)

    def _remove_row(self, letter, row_frame, vs, vo):
        # detach entire row frame
        try:
            row_frame.destroy()
        except Exception:
            pass
        # remove from state (match by variables)
        arr = self.site_elements.get(letter, [])
        for idx, item in enumerate(list(arr)):
            if item.get('var_sym') is vs and item.get('var_occ') is vo:
                arr.pop(idx)
                break
        self._validate_letter(letter)
        self._update_delete_state(letter)

    def _update_delete_state(self, letter):
        arr = self.site_elements.get(letter, [])
        only_one = len(arr) <= 1
        for item in arr:
            btn = item.get('del_btn')
            if btn:
                try:
                    if only_one:
                        btn.state(['disabled'])
                    else:
                        btn.state(['!disabled'])
                except Exception:
                    try:
                        btn.configure(state='disabled' if only_one else 'normal')
                    except Exception:
                        pass

    def _normalize_letter(self, letter):
        arr = self.site_elements.get(letter, [])
        if not arr:
            return
        total = 0.0
        for item in arr:
            try:
                total += float(item.get('var_occ').get())
            except Exception:
                pass
        if total <= 0:
            # set first to 1.0
            try:
                arr[0].get('var_occ').set(1.0)
            except Exception:
                pass
            return
        for item in arr:
            try:
                val = float(item.get('var_occ').get())
                item.get('var_occ').set(round(val / total, 2))
            except Exception:
                pass

    def _choose_element(self, var_sym: tk.StringVar):
        sym = select_element(self)
        if sym:
            var_sym.set(sym)

    def _toggle_back_cancel(self):
        # show back/cancel row or single cancel based on _allow_back
        try:
            if self._allow_back:
                self._btn_cancel_only.pack_forget()
                self._btns_back_row.pack(fill="x", pady=(4, 0))
            else:
                self._btns_back_row.pack_forget()
                self._btn_cancel_only.pack(fill="x", pady=(4, 0))
        except Exception:
            pass

    # ---- validation ----
    def _is_symbol_valid(self, sym: str) -> bool:
        if not isinstance(sym, str) or not sym:
            return False
        return sym in _VALID_SYMBOLS

    def _on_symbol_change(self, letter, var_sym):
        sym = var_sym.get().strip()
        # update entry style
        entry = None
        for item in self.site_elements.get(letter, []):
            if item.get('var_sym') is var_sym:
                entry = item.get('ent_sym')
                item['symbol'] = sym
                break
        if entry is not None:
            ok = self._is_symbol_valid(sym)
            self._set_entry_error(entry, not ok)
        # revalidate whole letter for occupancy also
        self._validate_letter(letter)

    def _set_entry_error(self, entry: ttk.Entry, is_error: bool):
        try:
            style = ttk.Style()
            style.configure('Error.TEntry', fieldbackground='#ffd9d9')
            entry.configure(style='Error.TEntry' if is_error else 'TEntry')
        except Exception:
            # Fallback if style change fails
            try:
                entry.configure(background='#ffd9d9' if is_error else 'white')
            except Exception:
                pass

    def _validate_letter(self, letter):
        # sum occupancies and validate symbols
        total = 0.0
        is_error = False
        for item in self.site_elements.get(letter, []):
            sym = item.get('var_sym').get().strip()
            occ = 0.0
            try:
                occ = float(item.get('var_occ').get())
            except Exception:
                is_error = True
            total += max(0.0, occ)
            # symbol valid?
            if sym and not self._is_symbol_valid(sym):
                is_error = True
            # apply style to occupancy when invalid state
            self._set_entry_error(item.get('ent_occ'), total > 1.0000001)
        # show a warning label if invalid
        if total > 1.0000001:
            self.warning_label.config(text=f"Occupancy for {letter} exceeds 1.0 ({total:.3f})")
        else:
            # clear only if no other errors
            self.warning_label.config(text="")
        # update plot highlighting (in case focus changed)
        self._update_plot()

    # ---- plotting ----
    def _start_worker(self):
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    def _next_token(self):
        self._draw_counter += 1
        return self._draw_counter

    def _snapshot(self, token):
        lattice = np.asarray(self.cell) if self.cell is not None else None
        pos = {k: np.array(v, dtype=float) for k, v in (self.positions or {}).items()}
        return {
            'token': token,
            'lattice': lattice,
            'positions': pos,
            'highlight': self._highlight_letter,
        }

    def _update_plot(self):
        tok = self._next_token()
        with self._worker_lock:
            self._latest = self._snapshot(tok)
        self._worker_event.set()

    def _worker_loop(self):
        while not self._worker_stop.is_set():
            self._worker_event.wait()
            if self._worker_stop.is_set():
                break
            with self._worker_lock:
                snap = self._latest
                self._latest = None
                self._worker_event.clear()
            if not snap:
                continue
            token = snap['token']
            lattice = snap['lattice']
            positions = snap['positions']
            highlight = snap['highlight']

            # render on UI thread
            def _apply():
                if token != self._draw_counter:
                    return
                self.ax.clear()
                if lattice is not None and lattice is not False:
                    plot_lattice(self.ax, lattice)
                # plot points by letter; highlight selected
                import matplotlib.pyplot as _plt
                cmap = _plt.get_cmap('Set1')
                idx = 0
                for letter in sorted(positions.keys()):
                    pts = positions[letter]
                    if lattice is not False and lattice is not None:
                        pts = np.dot(pts, lattice)
                    color = cmap(idx % 12)
                    size = 25
                    zorder = 2
                    if letter == highlight:
                        size = 60
                        zorder = 3
                    self.ax.scatter(*pts.T, color=color, s=size, depthshade=False, zorder=zorder, edgecolors='k' if letter == highlight else None)
                    idx += 1
                self.after_idle(lambda: self.canvas.draw())

            try:
                self.after(0, _apply)
            except Exception:
                pass

    def _highlight(self, letter):
        self._highlight_letter = letter
        self._update_plot()

    # ---- lifecycle ----
    def destroy(self):
        try:
            self._worker_stop.set()
            self._worker_event.set()
        except Exception:
            pass
        return super().destroy()

    # ---- result ----
    def _on_ok(self):
        # Validate all
        for letter, arr in self.site_elements.items():
            total = 0.0
            for item in arr:
                sym = item.get('var_sym').get().strip()
                occ = 0.0
                try:
                    occ = float(item.get('var_occ').get())
                except Exception:
                    occ = -1
                if sym and not self._is_symbol_valid(sym):
                    self.warning_label.config(text=f"Invalid element '{sym}' in {letter}")
                    return
                if occ < 0 or occ > 1:
                    self.warning_label.config(text=f"Invalid occupancy in {letter}")
                    return
                total += occ
            if total > 1.0000001:
                self.warning_label.config(text=f"Occupancy for {letter} exceeds 1.0 ({total:.3f})")
                return

        self.result = {
            'spacegroup': self.sg_number,
            'cell': Cell(self.cell) if self.cell is not None else None,
            'wyckoff_positions': self.positions,
            'site_elements': {
                L: [
                    {'symbol': item.get('var_sym').get().strip(), 'occupancy': float(item.get('var_occ').get() or 0.0)}
                    for item in arr if item.get('var_sym').get().strip()
                ]
                for L, arr in self.site_elements.items()
            }
        }
        # hide instead of destroy; signal completion
        self.withdraw()
        self._done.set(True)

    def _on_cancel(self):
        self.result = None
        self.withdraw()
        self._done.set(True)

    def _on_back(self):
        # Return a sentinel value so the caller can go back to spacegroup selector
        self.result = 'back'
        self.withdraw()
        self._done.set(True)

    # --- setup API to (re)initialize the dialog without recreating it ---
    def setup(self, spacegroup=None, cell=None, wyckoff_positions=None, back: bool = False):
        """Configure dialog state and UI for a new or repeated use.

        - If any of spacegroup/cell/wyckoff_positions is None, clear related UI/data.
        - If provided, initialize from values (accepts int or pyxtal Group for spacegroup,
          ASE Cell-like for cell, and a dict mapping letter -> list of fractional positions).
        - back toggles whether Back button should be presented for this session.
        """
        self._allow_back = bool(back)
        self._toggle_back_cancel()
        self._done.set(False)
        self.result = None

        # Clear if any core input missing
        if spacegroup is None or cell is None or wyckoff_positions is None:
            self.sg_number = None
            self.group = None
            self.cell = None
            self.positions = {}
            self.site_elements = {}
            # refresh UI
            self._populate_letters()
            self._update_plot()
            return

        # Initialize from provided data
        self.sg_number = int(spacegroup) if not isinstance(spacegroup, Group) else int(spacegroup.number)
        self.group = spacegroup if isinstance(spacegroup, Group) else Group(int(spacegroup))
        self.cell = np.asarray(cell) if cell is not None else None
        self.positions = wyckoff_positions or {}
        # reset site elements per letter
        self.site_elements = {letter: [] for letter in sorted(self.positions.keys())}
        # rebuild UI
        self._populate_letters()
        self._update_plot()


# --- public API ---

def select_site_elements(spacegroup, cell, wyckoff_positions, master=None, back: bool = False):
    """Open the element-assignment dialog.

    Accepts either separate (spacegroup, cell, positions) arguments or a 'selection'
    dict returned by select_spacegroup.

    Returns a dict mirroring select_spacegroup's with an extra 'site_elements' mapping.
    Returns None if canceled.
    """
    # reuse or create one instance per master
    key = master if master is not None else _EA_DEFAULT_KEY
    dlg = _EA_SELECTOR_INSTANCES.get(key)
    if dlg is None or not int(dlg.winfo_exists()):
        dlg = ElementAssignmentDialog(master=master, back=back)
        _EA_SELECTOR_INSTANCES[key] = dlg
    # (Re)setup state and show dialog
    dlg.setup(spacegroup=spacegroup, cell=cell, wyckoff_positions=wyckoff_positions, back=back)
    try:
        dlg.deiconify()
        dlg.lift()
        dlg.focus_set()
    except Exception:
        pass
    if master is None:
        dlg.wait_variable(dlg._done)
    else:
        master.wait_variable(dlg._done)
    return getattr(dlg, 'result', None)
