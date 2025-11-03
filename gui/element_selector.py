import tkinter as tk
from tkinter import ttk
import threading
import weakref
from collections import deque
import re

# try to import mendeleev for element data; fall back gracefully
try:
    from mendeleev import element as mendeleev_element
except Exception:
    mendeleev_element = None

# Simple periodic table layout: (Z, symbol, row, col)
_TABLE = [
    (1, "H", 0, 0), (2, "He", 0, 17),
    (3, "Li", 1, 0), (4, "Be", 1, 1), (5, "B", 1, 12), (6, "C", 1, 13), (7, "N", 1, 14), (8, "O", 1, 15), (9, "F", 1, 16), (10, "Ne", 1, 17),
    (11, "Na", 2, 0), (12, "Mg", 2, 1), (13, "Al", 2, 12), (14, "Si", 2, 13), (15, "P", 2, 14), (16, "S", 2, 15), (17, "Cl", 2, 16), (18, "Ar", 2, 17),
    (19, "K", 3, 0), (20, "Ca", 3, 1), (21, "Sc", 3, 2), (22, "Ti", 3, 3), (23, "V", 3, 4), (24, "Cr", 3, 5), (25, "Mn", 3, 6), (26, "Fe", 3, 7),
    (27, "Co", 3, 8), (28, "Ni", 3, 9), (29, "Cu", 3, 10), (30, "Zn", 3, 11), (31, "Ga", 3, 12), (32, "Ge", 3, 13), (33, "As", 3, 14), (34, "Se", 3, 15),
    (35, "Br", 3, 16), (36, "Kr", 3, 17),
    (37, "Rb", 4, 0), (38, "Sr", 4, 1), (39, "Y", 4, 2), (40, "Zr", 4, 3), (41, "Nb", 4, 4), (42, "Mo", 4, 5), (43, "Tc", 4, 6), (44, "Ru", 4, 7),
    (45, "Rh", 4, 8), (46, "Pd", 4, 9), (47, "Ag", 4, 10), (48, "Cd", 4, 11), (49, "In", 4, 12), (50, "Sn", 4, 13), (51, "Sb", 4, 14), (52, "Te", 4, 15),
    (53, "I", 4, 16), (54, "Xe", 4, 17),
    (55, "Cs", 5, 0), (56, "Ba", 5, 1), (57, "La", 8, 2), (58, "Ce", 8, 3), (59, "Pr", 8, 4), (60, "Nd", 8, 5), (61, "Pm", 8, 6), (62, "Sm", 8, 7),
    (63, "Eu", 8, 8), (64, "Gd", 8, 9), (65, "Tb", 8, 10), (66, "Dy", 8, 11), (67, "Ho", 8, 12), (68, "Er", 8, 13), (69, "Tm", 8, 14), (70, "Yb", 8, 15),
    (71, "Lu", 8, 16),
    (72, "Hf", 5, 3), (73, "Ta", 5, 4), (74, "W", 5, 5), (75, "Re", 5, 6), (76, "Os", 5, 7), (77, "Ir", 5, 8), (78, "Pt", 5, 9), (79, "Au", 5, 10),
    (80, "Hg", 5, 11), (81, "Tl", 5, 12), (82, "Pb", 5, 13), (83, "Bi", 5, 14), (84, "Po", 5, 15), (85, "At", 5, 16), (86, "Rn", 5, 17),
    (87, "Fr", 6, 0), (88, "Ra", 6, 1), (89, "Ac", 9, 2), (90, "Th", 9, 3), (91, "Pa", 9, 4), (92, "U", 9, 5), (93, "Np", 9, 6), (94, "Pu", 9, 7),
    (95, "Am", 9, 8), (96, "Cm", 9, 9), (97, "Bk", 9, 10), (98, "Cf", 9, 11), (99, "Es", 9, 12), (100, "Fm", 9, 13), (101, "Md", 9, 14), (102, "No", 9, 15),
    (103, "Lr", 9, 16),
    (104, "Rf", 6, 3), (105, "Db", 6, 4), (106, "Sg", 6, 5), (107, "Bh", 6, 6), (108, "Hs", 6, 7), (109, "Mt", 6, 8), (110, "Ds", 6, 9), (111, "Rg", 6, 10),
    (112, "Cn", 6, 11), (113, "Nh", 6, 12), (114, "Fl", 6, 13), (115, "Mc", 6, 14), (116, "Lv", 6, 15), (117, "Ts", 6, 16), (118, "Og", 6, 17),
]

# Build a categorized view of the table (dictionary of category -> list of entries)
# Each entry is (Z, symbol, row, col). We keep this explicit dictionary to
# allow grouping and styling per category.
CATEGORIES = {
    'alkali': [],
    'alkaline': [],
    'lanthanoid': [],
    'actinoid': [],
    'transition': [],
    'post': [],
    'metalloid': [],
    'nonmetal': [],
    'halogen': [],
    'noble': [],
    'unknown': [],
}

# helper: assign category by atomic number (keeps categorization explicit)
for z, sym, r, c in _TABLE:
    if z in (3, 11, 19, 37, 55, 87):
        CATEGORIES['alkali'].append((z, sym, r, c))
    elif z in (4, 12, 20, 38, 56, 88):
        CATEGORIES['alkaline'].append((z, sym, r, c))
    elif 57 <= z <= 71:
        CATEGORIES['lanthanoid'].append((z, sym, r, c))
    elif 89 <= z <= 103:
        CATEGORIES['actinoid'].append((z, sym, r, c))
    elif z in (2, 10, 18, 36, 54, 86, 118):
        CATEGORIES['noble'].append((z, sym, r, c))
    elif z in (1, 6, 7, 8, 15, 16, 34):
        CATEGORIES['nonmetal'].append((z, sym, r, c))
    elif z in (5, 14, 32, 33, 51, 52):
        CATEGORIES['metalloid'].append((z, sym, r, c))
    elif z in (9, 17, 35, 53, 85):
        CATEGORIES['halogen'].append((z, sym, r, c))
    elif (21 <= z <= 30) or (39 <= z <= 48) or (72 <= z <= 80) or (104 <= z <= 112):
        CATEGORIES['transition'].append((z, sym, r, c))
    elif z in (13, 31, 49, 50, 81, 82, 83, 113, 114, 115, 116):
        CATEGORIES['post'].append((z, sym, r, c))
    else:
        CATEGORIES['unknown'].append((z, sym, r, c))

# Lightweight cache of element data to avoid repeated slow lookups.
# We populate basic info from _TABLE synchronously and load detailed
# mendeleev data in a background thread (if available).
ELEMENT_DATA = {z: {'symbol': sym, 'z': z} for z, sym, *_ in _TABLE}
MENDELEEV_QUEUE = deque()
MENDELEEV_COND = threading.Condition()
MENDELEEV_THREAD = None
MENDELEEV_PENDING = set()
EVENT_NAME = '<<MENDELEEV_READY>>'
MAIN_LOOP_WIDGET = None   

def _ensure_mendeleev_worker():
    """Start the background loader thread if needed."""
    global MENDELEEV_THREAD
    if mendeleev_element is None:
        return
    if MENDELEEV_THREAD is None:
        MENDELEEV_THREAD = threading.Thread(target=_mendeleev_worker, daemon=True)
        MENDELEEV_THREAD.start()


def _get_attr_value(obj, *names):
    """Return the first non-None attribute value, calling it if callable."""
    for name in names:
        if not hasattr(obj, name):
            continue
        value = getattr(obj, name)
        if callable(value):
            try:
                value = value()
            except TypeError:
                continue
            except Exception:
                continue
        if value is not None:
            return value
    return None


# Map noble gas shorthand to their full core electron configuration tokens
_NOBLE_CORE_TOKENS = {
    'He': [
        '1s2',
    ],
    'Ne': [
        '1s2', '2s2', '2p6',
    ],
    'Ar': [
        '1s2', '2s2', '2p6', '3s2', '3p6',
    ],
    'Kr': [
        '1s2', '2s2', '2p6', '3s2', '3p6', '3d10', '4s2', '4p6',
    ],
    'Xe': [
        '1s2', '2s2', '2p6', '3s2', '3p6', '3d10', '4s2', '4p6', '4d10', '5s2', '5p6',
    ],
    'Rn': [
        '1s2', '2s2', '2p6', '3s2', '3p6', '3d10', '4s2', '4p6', '4d10', '5s2', '5p6',
        '4f14', '5d10', '6s2', '6p6',
    ],
}

def _tokens_from_econf(config_str):
    """Return a list of configuration tokens like ['1s2','2s2','2p6',...].
    Expands noble gas shorthand if present, so the returned list is full.
    """
    if not isinstance(config_str, str) or not config_str.strip():
        return []

    tokens = []
    # expand core if present
    m = re.search(r"\[(\w+)\]", config_str)
    rest = config_str
    if m:
        core_sym = m.group(1)
        tokens.extend(_NOBLE_CORE_TOKENS.get(core_sym, []))
        rest = re.sub(r"\[\w+\]", "", rest)
    tokens.extend(rest.split())
    return tokens


def _compress_to_noble_shorthand(config_str):
    """Compress a full configuration to noble-gas shorthand if possible.
    If the string already contains a shorthand, return it as-is (normalized).
    """
    if not isinstance(config_str, str) or not config_str.strip():
        return config_str

    # If already has a bracket, keep it (strip extra spaces)
    if re.search(r"\[\w+\]", config_str):
        return re.sub(r"\s+", " ", config_str).strip()

    tokens = _tokens_from_econf(config_str)
    if not tokens:
        return config_str

    # try longest core match first
    core_order = ['Rn', 'Xe', 'Kr', 'Ar', 'Ne', 'He']
    for sym in core_order:
        core = _NOBLE_CORE_TOKENS.get(sym, [])
        if core and len(tokens) >= len(core) and tokens[:len(core)] == core:
            tail = tokens[len(core):]
            return (f"[{sym}] " + " ".join(tail)).strip()

    return config_str


def _mendeleev_worker():
    while True:
        with MENDELEEV_COND:
            while not MENDELEEV_QUEUE:
                MENDELEEV_COND.wait()
            atomic_number = MENDELEEV_QUEUE.popleft()
            MENDELEEV_PENDING.discard(atomic_number)

        if ELEMENT_DATA.get(atomic_number, {}).get('mendeleev') is None and mendeleev_element is not None:
            try:
                el = mendeleev_element(atomic_number)
            except Exception:
                data = None
            else:
                data = {
                    'name': _get_attr_value(el, 'name'),
                    'symbol': _get_attr_value(el, 'symbol'),
                    'atomic_weight': _get_attr_value(el, 'atomic_weight', 'atomic_mass'),
                    'valence': _get_attr_value(el, 'nvalence', 'valence'),
                    'en': _get_attr_value(el, 'en_pauling', 'electronegativity'),
                    'ea': _get_attr_value(el, 'electron_affinity'),
                    'ox': _get_attr_value(el, 'oxistates', 'oxidation_states'),
                    'orbitals': _get_attr_value(el, 'electronic_configuration', 'econf', 'ec', 'electron_configuration')
                }
            ELEMENT_DATA.setdefault(atomic_number, {'symbol': str(atomic_number), 'z': atomic_number})['mendeleev'] = data
                    
        # Notify the main/UI thread by generating a virtual event on the
        # registered mainloop widget. The event carries the atomic number in
        # its "data" field so bound handlers can update safely on the UI thread.
        mw = MAIN_LOOP_WIDGET
        if mw is not None:
            try:
                mw.top.after_idle(lambda *,atomic_number=atomic_number: mw._handle_mendeleev_result(atomic_number) )
            except Exception as exc:
                pass

class ElementSelectorDialog:
    """Modal periodic-table selector implemented as a Tk dialog."""

    CATEGORY_COLORS = {
        'alkali': '#FF6666',
        'alkaline': '#FFDEAD',
        'lanthanoid': '#FFB3FF',
        'actinoid': '#FF99CC',
        'transition': '#FFD27F',
        'post': '#C0C0C0',
        'metalloid': '#C0E0C0',
        'nonmetal': '#99FF99',
        'halogen': '#66FFCC',
        'noble': '#66CCFF',
        'unknown': '#FFFFFF'
    }

    def __init__(self, master=None):
        self.master = master
        self.created_root = False
        self.use_root = None
        self.selected_symbol = None
        self.info_label = None
        self.active_z = None
        self.pending_requests = set()

        self._resolve_parent()
        # register the mainloop widget (so background worker can schedule
        # a main-thread callback) and register this dialog for notifications
        self._build_dialog()
         
        global MAIN_LOOP_WIDGET
        # Just register where the worker should generate the event; nothing else.
        MAIN_LOOP_WIDGET = self

    def _resolve_parent(self):
        try:
            master_viewable = self.master is not None and bool(self.master.winfo_viewable())
        except Exception:
            master_viewable = False

        if master_viewable:
            self.use_root = self.master
            return

        if tk._default_root is not None:
            self.use_root = tk._default_root
            return

        root = tk.Tk()
        root.withdraw()
        self.use_root = root
        self.created_root = True

    def _build_dialog(self):
        self.top = tk.Toplevel(self.use_root)
        self.top.withdraw()
        self.top.title("Select element")
        self.top.resizable(False, False)
        # Bind the MENDELEEV event so this window processes notifications
        # from the worker thread. Do this unconditionally during construction.
        
        try:
            if self.use_root is not None and bool(self.use_root.winfo_viewable()):
                self.top.transient(self.use_root)
        except Exception:
            pass

        self.top.protocol("WM_DELETE_WINDOW", self._on_cancel)

        container = ttk.Frame(self.top, padding=6)
        container.grid(sticky="nsew")

        table_frame = ttk.Frame(container)
        table_frame.grid(row=0, column=0, sticky="nsew")
        info_frame = ttk.Frame(container, padding=(8, 4), relief='groove', borderwidth=1)
        info_frame.grid(row=0, column=1, sticky="nsew")

        container.columnconfigure(0, weight=1)
        container.columnconfigure(1, weight=0, minsize=300)
        container.rowconfigure(0, weight=1)

        # Canvas-based grid for fast, square cells (no Button widgets)
        max_rows = 12
        max_cols = 18
        cellsize = 36  # slightly smaller to reduce overall height
        margin = 2
        spacing = 2
        gap_y = 8  # smaller gap for a shorter dialog

        total_width = margin * 2 + max_cols * cellsize + (max_cols - 1) * spacing
        total_height = margin * 2 + max_rows * cellsize + (max_rows - 1) * spacing + gap_y

        canvas = tk.Canvas(table_frame, width=total_width, height=total_height, highlightthickness=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas = canvas
        # map rect id -> original fill color for hover/unhover
        self._rect_to_color = {}
        self._highlighted_rect = None

        # Build category map for colors
        z_to_category = {}
        for cat, items in CATEGORIES.items():
            for z0, s0, r0, c0 in items:
                z_to_category[z0] = cat

        # Helper to compute contrasting text color
        def _text_color(bg_hex):
            try:
                hexcol = bg_hex.lstrip('#')
                rv = int(hexcol[0:2], 16)
                gv = int(hexcol[2:4], 16)
                bv = int(hexcol[4:6], 16)
                lum = 0.2126 * rv + 0.7152 * gv + 0.0722 * bv
                return '#FFFFFF' if lum < 128 else '#000000'
            except Exception:
                return '#000000'

        # Draw cells
        for z, sym, r, c in _TABLE:
            y_gap = gap_y if r >= 8 else 0
            x0 = margin + c * (cellsize + spacing)
            y0 = margin + r * (cellsize + spacing) + y_gap
            x1 = x0 + cellsize
            y1 = y0 + cellsize

            cat = z_to_category.get(z, 'unknown')
            bg = self.CATEGORY_COLORS.get(cat, self.CATEGORY_COLORS['unknown'])
            fg = _text_color(bg)
            display_sym = ELEMENT_DATA.get(z, {}).get('symbol', sym)

            rect = canvas.create_rectangle(x0, y0, x1, y1, fill=bg, outline='#888888', width=1)
            text = canvas.create_text((x0 + x1) // 2, (y0 + y1) // 2, text=display_sym, fill=fg, font=(None, 10, 'bold'))

            # remember original color so we can restore it on leave
            self._rect_to_color[rect] = bg

            # Bind events for hover and click on both rect and text
            def _enter(ev, z0=z, rid=rect):
                try:
                    self.show_element_info(z0)
                finally:
                    self._highlight_cell(rid)

            def _leave(ev, rid=rect):
                try:
                    self.clear_info()
                finally:
                    self._unhighlight_cell(rid)

            for item in (rect, text):
                canvas.tag_bind(item, '<Enter>', _enter)
                canvas.tag_bind(item, '<Leave>', _leave)
                canvas.tag_bind(item, '<Button-1>', lambda e, s=display_sym: self._choose(s))

        # Also clear info when mouse leaves the whole canvas
        canvas.bind('<Leave>', lambda e: self.clear_info())

        cancel = ttk.Button(container, text="Cancel", command=self._on_cancel)
        cancel.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 4), padx=2)

        info_title = ttk.Label(info_frame, text="Element info", font=(None, 10, 'bold'))
        info_title.grid(row=0, column=0, sticky='nw')
        # Make the info text fill the whole info_frame area (below the title)
        info_frame.columnconfigure(0, weight=1)
        info_frame.rowconfigure(1, weight=1)
        self.info_label = tk.Label(
            info_frame,
            text="",
            justify='left',
            anchor='nw',
            bg='#FFFFFF',
            wraplength=280,
        )
        self.info_label.grid(row=1, column=0, sticky='nsew')
        # Pre-compute geometry/layout while hidden so first show is smoother
        try:
            self.top.update_idletasks()
        except Exception:
            pass

    def _highlight_cell(self, rect_id):
        """Set a highlighted color for the given rect, restoring previous."""
        try:
            if self._highlighted_rect == rect_id:
                return
            # restore previous
            if self._highlighted_rect is not None:
                prev = self._highlighted_rect
                orig = self._rect_to_color.get(prev)
                if orig is not None:
                    try:
                        self.canvas.itemconfigure(prev, fill=orig)
                    except Exception:
                        pass
                self._highlighted_rect = None

            orig = self._rect_to_color.get(rect_id)
            if orig is None:
                return
            # simple highlight color: light yellow; keep text color as-is
            try:
                self.canvas.itemconfigure(rect_id, fill='#feffc2')
                self._highlighted_rect = rect_id
            except Exception:
                pass
        except Exception:
            pass

    def _unhighlight_cell(self, rect_id):
        """Restore rect fill to original if it's currently highlighted."""
        try:
            if self._highlighted_rect != rect_id:
                return
            orig = self._rect_to_color.get(rect_id)
            if orig is None:
                return
            try:
                self.canvas.itemconfigure(rect_id, fill=orig)
            except Exception:
                pass
            self._highlighted_rect = None
        except Exception:
            pass

    def _choose(self, symbol):
        self.selected_symbol = symbol
        self.top.destroy()

    def _on_cancel(self):
        self.selected_symbol = None
        self.top.destroy()

    def _request_mendeleev_data(self, atomic_number):
        if mendeleev_element is None:
            return
        if ELEMENT_DATA.get(atomic_number, {}).get('mendeleev') is not None:
            return
        if atomic_number in self.pending_requests:
            return

        self.pending_requests.add(atomic_number)
        _ensure_mendeleev_worker()
        with MENDELEEV_COND:
            if atomic_number not in MENDELEEV_PENDING:
                MENDELEEV_PENDING.add(atomic_number)
                # LIFO: push new requests on the left so the most recent
                # atomic number is processed first by popleft()
                MENDELEEV_QUEUE.appendleft(atomic_number)
                MENDELEEV_COND.notify()

    def show_element_info(self, atomic_number):
        self.active_z = atomic_number
        self._render_info(atomic_number, allow_request=True)

    def clear_info(self):
        self.active_z = None
        
        if self.info_label is not None:
            self.info_label.config(text="")

    def _render_info(self, atomic_number, allow_request):
        data = ELEMENT_DATA.setdefault(atomic_number, {'symbol': str(atomic_number), 'z': atomic_number})
        lines = [f"Symbol: {data.get('symbol', '')}", f"Z: {data.get('z', atomic_number)}"]

        md = data.get('mendeleev')
        if md:
            if md.get('name'):
                lines.insert(0, f"Name: {md.get('name')} ({md.get('symbol')})")
            if md.get('atomic_weight'):
                lines.append(f"Atomic weight: {md.get('atomic_weight')}")
            if md.get('valence'):
                lines.append(f"Valence electrons: {md.get('valence')}")
            if md.get('en'):
                lines.append(f"Electronegativity (Pauling): {md.get('en')}")
            if md.get('ea'):
                lines.append(f"Electron affinity: {md.get('ea')}")
            if md.get('ox'):
                lines.append(f"Oxidation states: {md.get('ox')}")
            if md.get('econf'):
                conf_disp = _compress_to_noble_shorthand(md.get('econf'))
                lines.append(f"Configuration: {conf_disp}")
            spdf = md.get('spdf')
            if isinstance(spdf, dict):
                s = spdf.get('s'); p = spdf.get('p'); d = spdf.get('d'); f = spdf.get('f')
                parts = []
                if isinstance(s, int): parts.append(f"s:{s}")
                if isinstance(p, int): parts.append(f"p:{p}")
                if isinstance(d, int): parts.append(f"d:{d}")
                if isinstance(f, int): parts.append(f"f:{f}")
                if parts:
                    lines.append("Orbitals (s/p/d/f): " + ", ".join(parts))
        elif allow_request and mendeleev_element is not None:
            lines.append("")
            lines.append('Loading more data...')
            self._request_mendeleev_data(atomic_number)

        if self.info_label is not None:
            self.info_label.config(text='\n'.join(lines))

    def _handle_mendeleev_result(self, atomic_number):
        self.pending_requests.discard(atomic_number)
        if not self.top.winfo_exists():
            return
        if self.active_z == atomic_number:
            self._render_info(atomic_number, allow_request=False)

    def _show(self):
        self.top.update_idletasks()
        try:
            sw = self.use_root.winfo_screenwidth()
            sh = self.use_root.winfo_screenheight()
        except Exception:
            sw = self.top.winfo_screenwidth()
            sh = self.top.winfo_screenheight()
        x = (sw - self.top.winfo_reqwidth()) // 2
        y = (sh - self.top.winfo_reqheight()) // 3
        self.top.geometry(f"+{x}+{y}")

        self.top.deiconify()
        self.top.lift()
        try:
            self.top.focus_set()
        except Exception:
            pass

    def show_modal(self):        
        self._show()
        self.top.grab_set()
        self.top.wait_window()        
        global MAIN_LOOP_WIDGET
        if MAIN_LOOP_WIDGET is self:
            MAIN_LOOP_WIDGET = None            
        if self.created_root and self.use_root is not None:
            try:
                self.use_root.destroy()
            except Exception:
                pass
        return self.selected_symbol


def select_element(master=None):
    dialog = ElementSelectorDialog(master=master)
    return dialog.show_modal()