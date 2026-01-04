from __future__ import annotations

from typing import Dict, Any, List, Optional

from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QScrollArea, QDoubleSpinBox, 
    QSizePolicy, QSplitter, QStyle
)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from ase import Atoms
from ase2sprkkr.sprkkr.atomic_types import AtomicType
import numpy as np
from weakref import WeakKeyDictionary
from ase.data import chemical_symbols

from .lattice import plot_lattice, plot_sites_in_lattice
from ..physics.wyckoff_data import wyckoff_data

class _GlobalSentinel:
    pass

_DEFAULT_KEY = _GlobalSentinel()
_DIALOGS = WeakKeyDictionary()
_VALID_SYMBOLS = set(s for s in chemical_symbols if isinstance(s, str))
_VALID_SYMBOLS.add("Vc")

class _LetterRow(QWidget):
    """Container for one Wyckoff letter's element rows."""
    def __init__(self, letter: str, parent: Optional[QWidget] = None,
                 on_activity: Optional[callable] = None,
                 on_break: Optional[callable] = None,
                 can_break: bool = False):
        super().__init__(parent)
        self.letter = letter
        self._on_activity = on_activity
        self._on_break = on_break
        self.rows: List[Dict[str, Any]] = []
        self.vbox = QVBoxLayout(self)

        # Header with title and normalize button
        header = QHBoxLayout()
        self.title_label = QLabel(f"Site {letter}")
        header.addWidget(self.title_label)
        header.addStretch(1)
        self.normalize_btn = QPushButton("Normalize")
        self.normalize_btn.clicked.connect(self._normalize)
        header.addWidget(self.normalize_btn)
        # Break symmetry button (visible only when multiplicity > 1)
        self.break_btn = QPushButton("Break symmetry")
        self.break_btn.setVisible(bool(can_break))
        if can_break and callable(self._on_break):
            self.break_btn.clicked.connect(lambda: self._on_break(self.letter))
        header.addWidget(self.break_btn)
        self.vbox.addLayout(header)

        # Rows area
        self.rows_box = QVBoxLayout()
        self.vbox.addLayout(self.rows_box)

        # Add-row button
        add_row = QHBoxLayout()
        add_row.addStretch(1)
        self.add_btn = QPushButton("＋ Add element")
        self.add_btn.clicked.connect(self.add_row)
        add_row.addWidget(self.add_btn)
        self.vbox.addLayout(add_row)

        # ensure one initial row
        self.add_row()
        glyph_font = QFont()
        glyph_font.setBold(True)
        glyph_font.setPointSize(12)
        self.glyph_font = glyph_font

    def set_title_suffix(self, text: str) -> None:
        self.title_label.setText(f"Site {self.letter}  {text}")

    def add_row(self, element: Optional[str] = "", occ: float = 1.0) -> None:
        from .element_selector import select_element  # local import to avoid cyclic import

        row_w = QWidget(self)
        h = QHBoxLayout(row_w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)

        elem_edit = QLineEdit()
        elem_edit.setPlaceholderText("Element")
        if not isinstance(element, str):
            element = ""
        elem_edit.setText(element)
        elem_edit.setMaxLength(3)
        elem_edit.setFixedWidth(55)
        h.addWidget(QLabel("Element"))
        h.addWidget(elem_edit)

        pick_btn = QPushButton("⚛️")
        pick_btn.setFont(self.glyph_font)
        pick_btn.setToolTip("Pick element")
        pick_btn.setFixedWidth(34)
        h.addWidget(pick_btn)

        occ_spin = QDoubleSpinBox()
        occ_spin.setRange(0.0, 1.0)
        occ_spin.setDecimals(3)
        occ_spin.setSingleStep(0.05)
        occ_spin.setValue(occ)
        label_occ = QLabel("occupation")
        h.addWidget(label_occ)
        occ_spin.setFixedWidth(70)
        h.addWidget(occ_spin)

        del_btn = QPushButton()
        del_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        del_btn.setToolTip("Remove this element row")
        del_btn.setFixedWidth(34)
        h.addWidget(del_btn)

        row = {
            'w': row_w,
            'elem': elem_edit,
            'occ': occ_spin,
            'del': del_btn,
            'pick': pick_btn,
        }
        self.rows.append(row)
        self.rows_box.addWidget(row_w)

        def do_pick():
            sym = select_element(self)
            if sym:
                elem_edit.setText(sym)
        pick_btn.clicked.connect(do_pick)
        del_btn.clicked.connect(lambda: self._remove_row(row))
        # Validation only; no redraw on value changes
        elem_edit.textChanged.connect(lambda _t: self._validate_row(row))
        occ_spin.valueChanged.connect(lambda _v: self._validate_totals())

        # Focus-driven highlighting
        for w in (elem_edit, occ_spin, pick_btn, del_btn):
            w.installEventFilter(self)

        self._validate_controls_state()
        self._validate_row(row)
        self._validate_totals()

    def load_payload(self, payload: List[Dict[str, Any]]) -> None:
        """Replace current element rows with provided payload [{'element':sym,'occupancy':val},...]."""
        # remove existing row widgets
        for r in list(self.rows):
            try:
                r['w'].setParent(None)
            except Exception:
                pass
        self.rows.clear()
        # add rows from payload
        if not payload:
            self.add_row()
        else:
            for item in payload:
                self.add_row(element=item.get('element',''), occ=float(item.get('occupancy',0.0)))

    def _remove_row(self, row: Dict[str, Any]) -> None:
        if len(self.rows) <= 1:
            return
        row['w'].setParent(None)
        try:
            self.rows.remove(row)
        except ValueError:
            pass
        self._validate_controls_state()
        self._validate_totals()

    def _validate_controls_state(self) -> None:
        # disable delete when only one row
        for r in self.rows:
            r['del'].setEnabled(len(self.rows) > 1)

    def _validate_row(self, row: Dict[str, Any]) -> None:
        elem = row['elem'].text().strip()
        ok = elem in _VALID_SYMBOLS
        # Styling: red border when invalid. Keep readable background.
        if ok or elem == "":
            row['elem'].setStyleSheet("")
        else:
            # Use a darker background only if palette seems light; simple heuristic
            row['elem'].setStyleSheet("QLineEdit { border: 1px solid #cc3333; background-color: #330000; color: #ffecec; }")
        self._validate_totals()

    def _normalize(self) -> None:
        total = sum(r['occ'].value() for r in self.rows) or 1.0
        for r in self.rows:
            r['occ'].setValue(r['occ'].value() / total)
        self._validate_totals()

    def _validate_totals(self) -> None:
        total = sum(r['occ'].value() for r in self.rows)
        over = total > 1.0000001
        # red border on all occupancy widgets when overfull
        style_bad = "QDoubleSpinBox { border: 1px solid #cc3333; }"
        for r in self.rows:
            r['occ'].setStyleSheet(style_bad if over else "")
        # bubble up to parent dialog for OK state and error text
        dlg = self.window()
        try:
            if hasattr(dlg, '_update_ok_state'):
                dlg._update_ok_state()
            if hasattr(dlg, '_set_site_error'):
                msg = f"Occupation too large for site {self.letter}" if over else None
                dlg._set_site_error(self.letter, msg)
        except Exception:
            pass

    # Focus event filter to trigger highlighting only when user focuses a widget.
    def eventFilter(self, obj, event):  # type: ignore[override]
        try:
            if event.type() == QEvent.Type.FocusIn:
                if callable(self._on_activity):
                    self._on_activity(self.letter)
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def payload(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for r in self.rows:
            elem = r['elem'].text().strip()
            occ = float(r['occ'].value())
            if not elem:
                continue
            out.append({'element': elem, 'occupancy': occ})
        return out

    def is_valid(self) -> bool:
        # Require at least one valid element symbol and total between 0 and 1.0
        has_valid_element = False
        for r in self.rows:
            elem = r['elem'].text().strip()
            if elem:
                if elem not in _VALID_SYMBOLS:
                    return False
                has_valid_element = True
        
        if not has_valid_element:
            return False
        
        total = sum(r['occ'].value() for r in self.rows)
        # Allow partial occupation: total must be > 0 and <= 1.0
        return 0.0 < total <= 1.0 + 1e-6


class ElementAssignmentDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None, back: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Assign Elements to Wyckoff Sites")
        # Wider default window to accommodate expanded left panel
        self.resize(1200, 650)
        self._allow_back = bool(back)
        self._letter_widgets: Dict[str, _LetterRow] = {}
        self._cell: Optional[np.ndarray] = None
        self._wyckoff: Dict[str, Any] = {}
        self._active_letter: Optional[str] = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        root.addWidget(splitter, 1)

        # Left: Scroll area for letters
        left = QWidget()
        left_v = QVBoxLayout(left)
        self.scroll = QScrollArea(left)
        self.scroll.setWidgetResizable(True)
        self.container = QWidget()
        self.scroll.setWidget(self.container)
        self.container_layout = QVBoxLayout(self.container)
        left_v.addWidget(self.scroll, 1)
        # Keep left column wide enough and stable so headers and inputs fit
        # Widen left panel for better readability of element rows
        left.setFixedWidth(450)
        # Initial splitter sizing (favor left slightly)
        splitter.setSizes([470, 730])
        splitter.addWidget(left)

        # Right: 3D preview
        right = QWidget()
        right_v = QVBoxLayout(right)
        self.fig = Figure(figsize=(4, 4))
        self.ax = self.fig.add_subplot(111, projection='3d')
        self.canvas = FigureCanvas(self.fig)
        right_v.addWidget(self.canvas, 1)
        # Error label at the bottom of right panel (larger, centered)
        self.error_label = QLabel("")
        self.error_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.error_label.setStyleSheet(
            "QLabel { color: #cc3333; font-size: 14px; font-weight: 600; padding: 4px 0; }"
        )
        right_v.addWidget(self.error_label)
        splitter.addWidget(right)

        # Buttons
        btns = QHBoxLayout()
        btns.addStretch(1)
        if self._allow_back:
            self.back_btn = QPushButton("Back")
            self.back_btn.clicked.connect(self._on_back)
            btns.addWidget(self.back_btn)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        btns.addWidget(self.cancel_btn)
        self.ok_btn = QPushButton("OK")
        self.ok_btn.clicked.connect(self._on_ok)
        self.ok_btn.setEnabled(False)
        btns.addWidget(self.ok_btn)
        root.addLayout(btns)

    def setup(self, spacegroup: Optional[int] = None, cell: Any = None,
              wyckoff_positions: Optional[Dict[str, Any]] = None, back: bool = False) -> None:
        # reset state
        self._allow_back = bool(back)
        for child in list(self._letter_widgets.values()):
            child.setParent(None)
        self._wyckoff = wyckoff_positions or {}
        self._cell = np.array(cell, dtype=float) if cell is not None else None
        
        if not wyckoff_positions:
            self.ok_btn.setEnabled(False)
            # still draw empty lattice if cell present
            self._draw_preview()
            return

        self._build_letter_rows(self._wyckoff)

        # Spacer to consume remaining space
        spacer = QWidget(self.container)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.container_layout.addWidget(spacer)

        self._update_ok_state()
        self._draw_preview()

    def _build_letter_rows(self, wyckoff: Dict[str, Any], preserved_payloads: Optional[Dict[str, List[Dict[str, Any]]]] = None) -> None:
        for child in list(self._letter_widgets.values()):
            child.setParent(None)
            child.deleteLater()
        self._letter_widgets.clear()

        for letter, pos_list in wyckoff.items():
            can_break = len(pos_list) > 1
            row = _LetterRow(letter, self.container, on_activity=self._mark_active, on_break=self._break_letter, can_break=can_break)
            # fractional coordinate hint from first position
            p0 = pos_list[0]
            coord = f"({p0[0]:.3f}, {p0[1]:.3f}, {p0[2]:.3f})"
            mult = len(pos_list)
            suffix = f"(multiplicity: {mult})  {coor}"
            row.set_title_suffix(suffix)
            if preserved_payloads and letter in preserved_payloads:
                row.load_payload(preserved_payloads[letter])
            self.container_layout.insertWidget(self.container_layout.count(), row)
            self._letter_widgets[letter] = row

        # Ensure a spacer at end
        spacer = QWidget(self.container)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.container_layout.addWidget(spacer)

    def _capture_payloads(self) -> Dict[str, List[Dict[str, Any]]]:
        return {letter: w.payload() for letter, w in self._letter_widgets.items()}

    def _break_letter(self, letter: str) -> None:
        # Split a multi-position letter into independent subsites letter.1, letter.2, ...
        arr = self._wyckoff[letter]
        n = int(len(arr))
        if n <= 1:
            raise Exception("Cannot break a letter with only one position.")

        preserved = self._capture_payloads()
        base_payload = preserved.pop(letter)
                
        def new_wyckoff():
            for k,v in self._wyckoff.items():
                if k != letter:
                    yield k,v
                else:
                    for i in range(n):
                        sub_letter = f"{letter}.{i+1}"
                        preserved[sub_letter] = base_payload[i:i+1]
                        yield sub_letter, arr[i:i+1]
                    self._active_letter = f"{letter}.1"

        self._wyckoff = dict(new_wyckoff())        
        self._build_letter_rows(self._wyckoff, preserved_payloads=preserved)                
        self._update_ok_state()
        self._draw_preview()

    def _update_ok_state(self) -> None:
        ok = bool(self._letter_widgets) and all(w.is_valid() for w in self._letter_widgets.values())
        self.ok_btn.setEnabled(ok)

    def _on_ok(self) -> None:
        # Validate rows first
        if not all(w.is_valid() for w in self._letter_widgets.values()):
            return

        # Build cartesian positions and per-atom kind indices
        lattice = np.array(self._cell, dtype=float) if self._cell is not None else None

        pos_blocks: List[np.ndarray] = []
        kinds: List[int] = []

        for letter, arr in self._wyckoff:
            arr = self._wyckoff.get(L)
            if arr is None or getattr(arr, 'size', 0) == 0:
                continue
            if lattice is not None:
                cart = np.dot(arr, lattice)
            else:
                cart = np.array(arr, dtype=float)
            pos_blocks.append(cart)
            kinds.extend([letter] * len(cart))
        if pos_blocks:
            positions = np.vstack(pos_blocks)
        else:
            positions = np.empty((0, 3), dtype=float)

        nat = len(positions)
        # Construct an Atoms object with 'X' species (Z=0) for all sites
        atoms = Atoms(numbers=[0] * nat, positions=positions, cell=self._cell, pbc=True)

        # Build occupancy dictionaries per kind from UI rows
        kind_dicts: List[dict] = [dict() for _ in letters]
        for L, widget in self._letter_widgets.items():
            k = letter_to_kind[L]
            occs = widget.payload()  # list of {'element': sym, 'occupancy': val}
            d: Dict[AtomicType, float] = {}
            for it in occs:
                sym = str(it.get('element', '')).strip()
                try:
                    val = float(it.get('occupancy', 0.0))
                except Exception:
                    val = 0.0
                if not sym:
                    continue
                key = AtomicType(sym)
                d[key] = d.get(key, 0.0) + val
            kind_dicts[k] = d

        # Attach arrays
        atoms.set_array('spacegroup_kinds', np.asarray(kinds, dtype=int))
        # Per-atom occupancy dictionary copied from its kind (dtype=object)
        per_atom_occ = np.asarray([kind_dicts[k] for k in kinds], dtype=object) if kinds else np.empty((0,), dtype=object)
        atoms.set_array('occupancy', per_atom_occ)
        site_letters = np.asarray([letters[k] for k in kinds], dtype=object) if kinds else np.empty((0,), dtype=object)
        atoms.set_array('site_letters', site_letters)

        # Extra metadata helpful to downstream tools
        atoms.info['occupancy_by_kind'] = np.asarray(kind_dicts, dtype=object)
        atoms.info['kind_letters'] = letters
        atoms.info['letter_to_kind'] = letter_to_kind

        self._result = atoms
        self.accept()

    def _on_back(self) -> None:
        self._result = 'back'
        self.done(42)

    def result_payload(self) -> Optional[Dict[str, Any]] | str:
        return getattr(self, '_result', None)

    def _mark_active(self, letter: str) -> None:
        # Avoid redraw if the letter stays the same
        if letter == self._active_letter:
            return
        self._active_letter = letter
        self._draw_preview()

    def _draw_preview(self) -> None:
        try:
            self.ax.clear()
        except Exception:
            return
        lattice = self._cell
        if lattice is None:
            self.canvas.draw()
            return
        try:
            plot_lattice(self.ax, lattice)
        except Exception:
            pass
        # collect other vs active positions
        others = []
        active = []
        try:
            for letter, pos_list in (self._wyckoff or {}).items():
                arr = pos_list
                if self._active_letter and letter == self._active_letter:
                    if arr.size:
                        active.append(arr)
                else:
                    if arr.size:
                        others.append(arr)
        except Exception:
            others = []
            active = []
        if others:
            try:
                plot_sites_in_lattice(self.ax, lattice, np.vstack(others), role='inactive')
            except Exception:
                pass
        if active:
            try:
                plot_sites_in_lattice(self.ax, lattice, np.vstack(active), role='active')
            except Exception:
                pass
        try:
            self.canvas.draw()
        except Exception:
            pass

    # ---- error aggregation helpers ----
    def _set_site_error(self, letter: str, message: Optional[str]) -> None:
        if not hasattr(self, '_site_errors'):
            self._site_errors: Dict[str, Optional[str]] = {}
        if message:
            self._site_errors[letter] = message
        else:
            self._site_errors.pop(letter, None)
        self._update_error_label()

    def _update_error_label(self) -> None:
        msgs = []
        try:
            for L, msg in (getattr(self, '_site_errors', {}) or {}).items():
                if msg:
                    msgs.append(msg)
        except Exception:
            msgs = []
        self.error_label.setText("\n".join(msgs))


def select_site_elements(parent: Optional[QWidget] = None, *, spacegroup: Optional[int] = None,
                         cell: Any = None, wyckoff_positions: Optional[Dict[str, Any]] = None,
                         back: bool = False) -> Optional[Atoms] | str:
    """
    PyQt6 element assignment dialog.
    Expects wyckoff_positions as mapping letter->list of positions (to show multiplicity).

        Returns an ase.Atoms instance with:
            - positions in Cartesian coordinates (from wyckoff_positions and cell)
            - array 'spacegroup_kinds' (int per atom; a->0, b->1, ...)
            - array 'occupancy' (object array per atom: dict[AtomicType, float])
            - info['occupancy_by_kind'] (list/dtype=object of dicts per kind)
            - info['kind_letters'] and info['letter_to_kind'] mappings
        Or 'back' or None.
    """
    key = parent if parent is not None else _DEFAULT_KEY
    try:
        dlg = _DIALOGS.get(key)
    except Exception:
        dlg = None
    if dlg is None or not isinstance(dlg, ElementAssignmentDialog):
        dlg = ElementAssignmentDialog(parent, back=back)
        _DIALOGS[key] = dlg
    else:
        dlg._allow_back = bool(back)

    dlg.setup(spacegroup=spacegroup, cell=cell, wyckoff_positions=wyckoff_positions, back=back)
    code = dlg.exec()
    if code == 42:
        return 'back'
    if code == QDialog.DialogCode.Accepted:
        return dlg.result_payload()
    return None
