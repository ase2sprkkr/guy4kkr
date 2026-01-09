from __future__ import annotations

from typing import Dict, Any, List, Optional

from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QScrollArea, QDoubleSpinBox,
    QSizePolicy, QSplitter, QStyle, QTableWidget, QHeaderView, QGroupBox
)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from ase import Atoms
import numpy as np
from weakref import WeakKeyDictionary
from ase.data import chemical_symbols
from ase2sprkkr.sprkkr.atomic_types import AtomicType
from ase2sprkkr import SPRKKRAtoms
from ase import Atoms
from .lattice import plot_lattice, plot_sites_in_lattice
from ..ase.utils import partition_by_kinds, labels_for_partitions


class _GlobalSentinel:
    pass

_DEFAULT_KEY = _GlobalSentinel()
_DIALOGS = WeakKeyDictionary()
_VALID_SYMBOLS = set(s for s in chemical_symbols if isinstance(s, str))
_VALID_SYMBOLS.add("Vc")

class QLetterRow(QWidget):
    """Container for one Wyckoff letter's element rows."""
    glyph_font = QFont()
    glyph_font.setBold(True)
    glyph_font.setPointSize(12)

    def __init__(self, payload: Dict[str, Any],
                 cell: np.ndarray,
                 parent: Optional[QWidget] = None,
                 on_activity: Optional[callable] = None,
                 on_break: Optional[callable] = None):
        super().__init__(parent)
        self.cell = cell
        self._on_activity = on_activity
        self._on_break = on_break
        self.rows: List[Dict[str, Any]] = []
        self.vbox = QVBoxLayout(self)

        # Header with title and normalize button
        header = QHBoxLayout()
        self.title_label = QLabel()
        header.addWidget(self.title_label)
        header.addStretch(1)
        self.normalize_btn = QPushButton("Normalize")
        self.normalize_btn.clicked.connect(self._normalize)
        header.addWidget(self.normalize_btn)
        # Break symmetry button (visible only when multiplicity > 1)
        self.break_btn = QPushButton("Break symmetry")
        can_break = len(payload['positions']) > 1
        self.break_btn.setVisible(bool(can_break))
        if can_break and callable(self._on_break):
            self.break_btn.clicked.connect(lambda: self._on_break(self.payload))
        header.addWidget(self.break_btn)
        self.vbox.addLayout(header)

        # Rows area
        self.rows_box = QVBoxLayout()
        self.vbox.addLayout(self.rows_box)

        # Add-row button
        add_row = QHBoxLayout()
        self.add_btn = QPushButton("＋ Add element")
        self.add_btn.clicked.connect(self.add_row)
        add_row.addWidget(self.add_btn)
        self.vbox.addLayout(add_row)

        self.load_payload(payload)

    @property
    def label(self):
        return self.payload.get('label', '')

    def load_payload(self, payload: Dict[str, Any]) -> None:
        self.payload = payload
        positions = payload['positions']
        p0 = positions[0]
        coord = f"({p0[0]:.3f}, {p0[1]:.3f}, {p0[2]:.3f})"
        mult = len(positions)
        suffix = f"(multiplicity: {mult})  {coord}"
        self.title_label.setText(f"Site {payload.get('label', '')}  {suffix}")

        self.load_occupancy(payload.get('occupancy', {}))
        self._validate_controls_state()
        self._validate_totals()

    def load_occupancy(self, occupancy: Dict[Any, float]) -> None:
        """Replace current element rows with provided payload [{'element':sym,'occupancy':val},...]."""
        # remove existing row widgets
        for r in list(self.rows):
            r['w'].setParent(None)
        self.rows.clear()

        # add rows from payload
        if not occupancy:
            self._add_row()
        else:
            for symbol, occ in occupancy.items():
                self._add_row(element=getattr(symbol, "symbol", str(symbol)), occ=occ)

    def add_row(self) -> None:
        """Add a blank element row."""
        self._add_row()
        self._validate_controls_state()
        self._validate_totals()

    def _add_row(self, element: Optional[str] = "", occ: float = 1.0) -> None:
        from .element_selector import select_element  # local import to avoid cyclic import

        row_w = QWidget(self)
        row_w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
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
        label_elem = QLabel("Element")
        label_elem.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        h.addWidget(label_elem)
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
        label_occ.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        h.addWidget(label_occ)
        occ_spin.setFixedWidth(70)
        h.addWidget(occ_spin)

        # Keep controls left; push only the trash button to the far right.
        h.addStretch(1)

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

        self._validate_row(row)

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
        dlg._update_ok_state()
        msg = f"Occupation too large for site {self.label}" if over else None
        dlg._set_site_error(self.label, msg)

    # Focus event filter to trigger highlighting only when user focuses a widget.
    def eventFilter(self, obj, event):  # type: ignore[override]
        try:
            if event.type() == QEvent.Type.FocusIn:
                if callable(self._on_activity):
                    self._on_activity(self.label)
        except Exception:
            pass
        return super().eventFilter(obj, event)

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

    def resulting_payload(self) -> List[Dict[str, Any]]:
        payload = self.payload
        occs = {}
        for r in self.rows:
            elem = r['elem'].text().strip()
            occ = float(r['occ'].value())
            if not elem:
                continue
            if elem in occs:
                elem = AtomicType.from_symbol(elem)
            occs[elem] = occ
        payload['occupancy'] = occs
        return payload

    @classmethod
    def payload_from_atoms(cls, atoms: Atoms) -> List[Dict[str, Any]]:
        """Extract payload from atoms."""
        payloads: List[Dict[str, Any]] = []
        parts = partition_by_kinds(atoms)
        kinds = atoms.get_array('spacegroup_kinds') if 'spacegroup_kinds' in atoms.arrays else None
        occs = atoms.info.get('occupancy', {})
        labels = labels_for_partitions(atoms, partitions=parts)
        positions = atoms.get_scaled_positions()

        occ_map: Dict[str, float] = {}
        for i, part in enumerate(parts):
            first = part[0]
            label = labels[i]
            sym = atoms[first].symbol
            if occs and kinds is not None:
                kind = kinds[first]
                occ = occs.get(kind, {})
            elif sym!='X':
                occ = {sym: 1.0}
            else:
                occ = {'': 1.0}
            payloads.append({
                'label': label,
                'occupancy': occ,
                'positions': positions[part],
                'index': part,
            })
        return payloads

class ElementAssignmentDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None, back: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Assign Elements to Wyckoff Sites")
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
        )
        # Wider default window to accommodate expanded left panel
        self.resize(1200, 650)
        self._allow_back = bool(back)
        self._letter_widgets: [LetterRow] = []
        self._cell: Optional[np.ndarray] = None
        self._active_letter: Optional[str] = None
        self._site_errors: Dict[str, Optional[str]] = {}
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
        self.container_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        left_v.addWidget(self.scroll, 1)
        # Keep left column wide enough and stable so headers and inputs fit
        # Widen left panel for better readability of element rows
        left.setMinimumWidth(550)
        # Initial splitter sizing (favor left slightly)
        splitter.setSizes([470, 730])
        splitter.addWidget(left)

        # Right: 3D preview
        right = QWidget()
        right_v = QVBoxLayout(right)

        # Lattice vectors table (editable)
        lattice_vectors_group = QGroupBox("Lattice Vectors (Å)")
        lattice_vectors_layout = QVBoxLayout(lattice_vectors_group)
        self.lattice_vectors_table = QTableWidget(3, 3)
        self.lattice_vectors_table.setHorizontalHeaderLabels(["x", "y", "z"])
        self.lattice_vectors_table.setVerticalHeaderLabels(["a", "b", "c"])
        self.lattice_vectors_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.lattice_vectors_table.verticalHeader().setMinimumWidth(40)
        self.lattice_vectors_table.setMaximumHeight(120)

        # Initialize with spinboxes
        self.lattice_spinboxes = []
        for i in range(3):
            row_spinboxes = []
            for j in range(3):
                spinbox = QDoubleSpinBox()
                spinbox.setRange(-1000.0, 1000.0)
                spinbox.setDecimals(4)
                spinbox.setSingleStep(0.1)
                spinbox.setValue(0.0)
                spinbox.setAlignment(Qt.AlignmentFlag.AlignRight)
                spinbox.valueChanged.connect(self._on_lattice_vector_changed)
                self.lattice_vectors_table.setCellWidget(i, j, spinbox)
                row_spinboxes.append(spinbox)
            self.lattice_spinboxes.append(row_spinboxes)

        lattice_vectors_layout.addWidget(self.lattice_vectors_table)
        right_v.addWidget(lattice_vectors_group, 0)

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



    def setup(self, atoms: Atoms, back: bool = False) -> None:
        # reset state
        self._allow_back = bool(back)
        for child in list(self._letter_widgets):
            child.setParent(None)
        self._atoms = atoms
        self._cell = atoms.cell.copy()

        # Update lattice vector spinboxes
        for i in range(3):
            for j in range(3):
                self.lattice_spinboxes[i][j].blockSignals(True)
                self.lattice_spinboxes[i][j].setValue(self._cell[i, j])
                self.lattice_spinboxes[i][j].blockSignals(False)

        payload = QLetterRow.payload_from_atoms(atoms)
        self._build_site_rows(payload)

        # Spacer to consume remaining space
        spacer = QWidget(self.container)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.container_layout.addWidget(spacer)

        self._update_ok_state()
        self._draw_preview()

    def _build_site_rows(self, payloads) -> None:
        for child in list(self._letter_widgets):
            child.setParent(None)
            child.deleteLater()
        self._letter_widgets.clear()

        for i, payload in enumerate(payloads):
            row = QLetterRow(payload, self._atoms.cell, self.container, on_activity=self._mark_active, on_break=self._break_site)
            # fractional coordinate hint from first position
            self.container_layout.insertWidget(self.container_layout.count(), row)
            self._letter_widgets.append(row)

    def _capture_payloads(self) -> Dict[str, List[Dict[str, Any]]]:
        return [ w.resulting_payload() for w in self._letter_widgets ]

    def _break_site(self, payload) -> None:
        # Split a multi-position letter into independent subsites letter.1, letter.2, ...

        payloads = self._capture_payloads()
        labels = {p['label'] for p in payloads}
        out = []

        for idx, p in enumerate(payloads):
            if p is payload:
                out = payloads[:idx]

            for i,pos in enumerate(payload['positions']):
                index = payload.pop('index', None)
                add = payload.copy()
                template = f"{payload['label']}.{i+1}"
                label = template
                j=1
                while label in labels:
                    label = f"{template}.{j}"
                    j+=1
                add['label'] = label
                add['positions'] = pos
                if index is not None:
                    add['origin'] = [ index[i] ]
                out.append( add )
            out.extend( payloads[idx+1:] )
        else:
            raise ValueError("Payload to break not found in current payloads.")

        self._build_site_rows(out)
        self._update_ok_state()
        self._draw_preview()

    def _update_ok_state(self) -> None:
        ok = bool(self._letter_widgets) and all(w.is_valid() for w in self._letter_widgets)
        self.ok_btn.setEnabled(ok)

    def _on_ok(self) -> None:
        # Validate rows first
        if not all(w.is_valid() for w in self._letter_widgets):
            return

        pos_blocks: List[np.ndarray] = []
        kinds: List[int] = []
        symbols = []
        labels = []
        occupancy: Dict[int, Dict[Any, float]] = {}
        payloads = self._capture_payloads()
        start = 0

        changed = False

        atoms = self._atoms
        sprkkr = isinstance(atoms,SPRKKRAtoms)

        regions = []
        if sprkkr:
            for r in atoms.regions:
                regions.append(r, set(r.ids(), []))

        for kind, payload in enumerate(payloads):
            cart = np.dot(payload['positions'], self._cell)
            ln = len(cart)
            pos_blocks.append(cart)
            kinds.extend([kind] * ln)
            occs = payload['occupancy']
            occupancy[kind] = occs
            symbol = next(iter(occs.keys()), 'X')

            o = payload.get('index')
            if not changed:
                if o is not None and np.all( np.arange(start, start+ln) == o ):
                    changed = True

            if regions is not None:
                origins = o if o is not None else payload.get('origin')
                if origins is None:
                    regions = None
                else:
                    for i,origin in enumerate(origins):
                        for r, ids, new in regions:
                            if origin in ids:
                                new.append(start+i)
            start += ln
            occs = payload['occupancy']
            symbols.extend( [symbol] * ln )
            labels.extend( f"{payload['label']}.{i}" for i in range(1,ln+1) )

        if changed:
            piter = iter(payloads)
            p = next(piter)
            if p['index'] is not None:
                new = atoms[p['index']]
            else:
                new = atoms(positions=payloads[0], cell=self._cell, pbc=True)
            for p in piter:
                if p['index'] is not None:
                    new += atoms[p['index']]
                else:
                    new += atoms(positions=p['positions'],)

        if sprkkr:
            if atoms.are_sites_inited():
                del atoms.sites
            if regions:
                for r, ids, new in regions:
                    region.copy_for_atoms(atoms, new)

        atoms.cell = self._cell
        atoms.symbols = symbols
        atoms.set_array('spacegroup_kinds', np.asarray(kinds, dtype=int))
        atoms.set_array('labels', np.asarray(labels, dtype=object))
        atoms.positions = np.vstack(pos_blocks)
        atoms.info['occupancy'] = occupancy
        self._result = atoms
        self.accept()

    def _on_back(self) -> None:
        self._result = 'back'
        self.done(42)

    def _mark_active(self, letter: str) -> None:
        # Avoid redraw if the letter stays the same
        if letter == self._active_letter:
            return
        self._active_letter = letter
        self._draw_preview()

    def _on_lattice_vector_changed(self, value: float) -> None:
        """Handle changes to lattice vector spinboxes."""
        # Build new cell from spinbox values
        for i in range(3):
            for j in range(3):
                self._cell[i, j] = self.lattice_spinboxes[i][j].value()

        # Redraw visualization
        self._draw_preview()

    def _draw_preview(self) -> None:
        self.ax.clear()
        lattice = self._cell
        plot_lattice(self.ax, lattice)

        # collect other vs active positions
        others = []
        active = []

        for w in self._letter_widgets:
            if self._active_letter == w.label:
                to = active
            else:
                to = others
            to.append(w.payload['positions'])
        if others:
            plot_sites_in_lattice(self.ax, lattice, np.vstack(others), role='inactive')
        if active:
            plot_sites_in_lattice(self.ax, lattice, np.vstack(active), role='active')
        self.canvas.draw()

    # ---- error aggregation helpers ----
    def _set_site_error(self, letter: str, message: Optional[str]) -> None:
        if message:
            self._site_errors[letter] = message
        else:
            self._site_errors.pop(letter, None)
        self._update_error_label()

    def _update_error_label(self) -> None:
        self.error_label.setText("\n".join(self._site_errors.values()))


def select_site_elements(atoms:Atoms, parent: Optional[QWidget] = None,
                         back: bool = False) -> Optional[Atoms] | str:
    """
    PyQt6 element assignment dialog.

        Returns an ase.Atoms instance with:
            - positions in Cartesian coordinates
            - symbols
            - array 'spacegroup_kinds' (int per atom; a->0, b->1, ...)
            - array 'occupancy' (object array per atom: dict[AtomicType, float])
            - array 'labels' (str per atom: site labels like 'a', 'b.1', ...)
        Or 'back' or None.
    """
    key = parent if parent is not None else _DEFAULT_KEY
    dlg = _DIALOGS.get(key)
    if dlg is None:
        dlg = ElementAssignmentDialog(parent, back=back)
        _DIALOGS[key] = dlg
    else:
        dlg._allow_back = bool(back)

    dlg.setup(atoms)
    code = dlg.exec()
    if code == 42:
        return 'back'
    if code == QDialog.DialogCode.Accepted:
        return dlg._result
    return None