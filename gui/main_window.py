from __future__ import annotations

from typing import Optional, TYPE_CHECKING, Any, Dict, Sequence
from pathlib import Path

from PyQt6.QtCore import Qt

if TYPE_CHECKING:
    from ase import Atoms

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QGroupBox, QPushButton, QLabel, QTableWidget, QTableWidgetItem,
    QMenuBar, QMenu, QFileDialog, QMessageBox, QGridLayout, QHeaderView
)
from PyQt6.QtGui import QAction, QColor
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib import cm
from matplotlib.colors import to_hex
import numpy as np

try:
    from ase import Atoms
    from ase.io import read as ase_read, write as ase_write
except ImportError:
    Atoms = None
    ase_read = None
    ase_write = None

from .lattice import plot_lattice, plot_sites_in_lattice
from .common import chain_dialogs
from .spacegroup_selector import select_spacegroup
from .element_assignment import select_site_elements


class MainWindow(QMainWindow):
    """Main application window for structure creation, loading, and manipulation."""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Guy4ASE - Structure Manager")
        self.resize(1400, 800)
        
        self.atoms: Optional[Any] = None  # ASE Atoms object
        self._site_colors: Dict[str, str] = {}
        
        self._build_ui()
        self._update_structure_view()
        
    def _build_ui(self) -> None:
        """Build the main UI layout."""
        # Menu bar
        menubar = self.menuBar()
        
        # Structure menu
        structure_menu = menubar.addMenu("&Structure")
        
        create_action = QAction("&Create New...", self)
        create_action.setShortcut("Ctrl+N")
        create_action.triggered.connect(self._on_create_structure)
        structure_menu.addAction(create_action)
        
        load_action = QAction("&Load from File...", self)
        load_action.setShortcut("Ctrl+O")
        load_action.triggered.connect(self._on_load_structure)
        structure_menu.addAction(load_action)
        
        download_action = QAction("&Download from Materials Project...", self)
        download_action.triggered.connect(self._on_download_structure)
        structure_menu.addAction(download_action)
        
        structure_menu.addSeparator()
        
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        structure_menu.addAction(exit_action)
        
        # Help menu
        help_menu = menubar.addMenu("&Help")
        about_action = QAction("&About", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)
        
        # Central widget with splitter
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)
        
        # Left/center panel: structure viewer
        viewer_widget = QWidget()
        viewer_layout = QVBoxLayout(viewer_widget)
        
        # 3D visualization - will contain either plot or welcome screen
        vis_group = QGroupBox("Structure Visualization")
        self.vis_layout = QVBoxLayout(vis_group)
        
        # Welcome screen (shown when no structure loaded)
        self.welcome_widget = QWidget()
        welcome_layout = QVBoxLayout(self.welcome_widget)
        welcome_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        welcome_label = QLabel("No Structure Loaded")
        welcome_label.setStyleSheet("font-size: 18pt; font-weight: bold; color: #666;")
        welcome_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_layout.addWidget(welcome_label)
        
        welcome_layout.addSpacing(20)
        
        subtitle = QLabel("Choose an option to get started:")
        subtitle.setStyleSheet("font-size: 11pt; color: #888;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_layout.addWidget(subtitle)
        
        welcome_layout.addSpacing(30)
        
        # Action buttons
        btn_width = 250
        
        create_btn = QPushButton("Create New Structure")
        create_btn.setMinimumWidth(btn_width)
        create_btn.setMinimumHeight(45)
        create_btn.setStyleSheet("font-size: 11pt; padding: 8px;")
        create_btn.clicked.connect(self._on_create_structure)
        welcome_layout.addWidget(create_btn, 0, Qt.AlignmentFlag.AlignCenter)
        
        welcome_layout.addSpacing(15)
        
        load_btn = QPushButton("Load from File...")
        load_btn.setMinimumWidth(btn_width)
        load_btn.setMinimumHeight(45)
        load_btn.setStyleSheet("font-size: 11pt; padding: 8px;")
        load_btn.clicked.connect(self._on_load_structure)
        welcome_layout.addWidget(load_btn, 0, Qt.AlignmentFlag.AlignCenter)
        
        welcome_layout.addSpacing(15)
        
        download_btn = QPushButton("Download from Materials Project...")
        download_btn.setMinimumWidth(btn_width)
        download_btn.setMinimumHeight(45)
        download_btn.setStyleSheet("font-size: 11pt; padding: 8px;")
        download_btn.clicked.connect(self._on_download_structure)
        welcome_layout.addWidget(download_btn, 0, Qt.AlignmentFlag.AlignCenter)
        
        welcome_layout.addStretch(1)
        
        self.vis_layout.addWidget(self.welcome_widget)
        
        # Canvas (shown when structure is loaded)
        self.fig = Figure(figsize=(6, 6))
        self.ax = self.fig.add_subplot(111, projection='3d')
        self.canvas = FigureCanvas(self.fig)
        self.vis_layout.addWidget(self.canvas)
        self.canvas.hide()  # Initially hidden
        
        viewer_layout.addWidget(vis_group, 2)
        
        # Lattice parameters
        lattice_group = QGroupBox("Lattice Parameters")
        lattice_layout = QGridLayout(lattice_group)
        
        self.lattice_labels = {}
        params = ['a', 'b', 'c', 'α', 'β', 'γ']
        for i, param in enumerate(params):
            label = QLabel(f"{param}:")
            value = QLabel("–")
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lattice_layout.addWidget(label, i // 3, (i % 3) * 2)
            lattice_layout.addWidget(value, i // 3, (i % 3) * 2 + 1)
            self.lattice_labels[param] = value
        
        lattice_layout.addWidget(QLabel("Lattice vectors (Å):"), 2, 0, 1, 6)
        self.lattice_matrix_labels = []
        for i in range(3):
            row_labels = []
            for j in range(3):
                lbl = QLabel("–")
                lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                lattice_layout.addWidget(lbl, 3 + i, j * 2, 1, 2)
                row_labels.append(lbl)
            self.lattice_matrix_labels.append(row_labels)
        
        viewer_layout.addWidget(lattice_group, 0)
        
        # Atomic positions table
        positions_group = QGroupBox("Atomic Positions")
        positions_layout = QVBoxLayout(positions_group)
        self.positions_table = QTableWidget(0, 6)
        self.positions_table.setHorizontalHeaderLabels(["Site", "Composition", "Color", "x (Å)", "y (Å)", "z (Å)"])
        self.positions_table.horizontalHeader().setStretchLastSection(True)
        self.positions_table.verticalHeader().setVisible(False)
        self.positions_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        positions_layout.addWidget(self.positions_table)
        viewer_layout.addWidget(positions_group, 1)
        
        splitter.addWidget(viewer_widget)
        
        # Right panel: actions
        actions_widget = QWidget()
        actions_layout = QVBoxLayout(actions_widget)
        actions_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        actions_group = QGroupBox("Structure Actions")
        actions_group_layout = QVBoxLayout(actions_group)
        
        # Action buttons
        self.save_btn = QPushButton("Save Structure...")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._on_save_structure)
        actions_group_layout.addWidget(self.save_btn)
        
        actions_group_layout.addSpacing(20)
        
        sprkkr_label = QLabel("SPRKKR Tools:")
        sprkkr_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        actions_group_layout.addWidget(sprkkr_label)
        
        self.create_input_btn = QPushButton("Create SPRKKR Input File...")
        self.create_input_btn.setEnabled(False)
        self.create_input_btn.clicked.connect(self._on_create_sprkkr_input)
        actions_group_layout.addWidget(self.create_input_btn)
        
        self.run_calc_btn = QPushButton("Run SPRKKR Calculation...")
        self.run_calc_btn.setEnabled(False)
        self.run_calc_btn.clicked.connect(self._on_run_sprkkr_calculation)
        actions_group_layout.addWidget(self.run_calc_btn)
        
        actions_group_layout.addStretch(1)
        actions_layout.addWidget(actions_group)
        
        # Info panel
        info_group = QGroupBox("Structure Information")
        info_layout = QVBoxLayout(info_group)
        self.info_label = QLabel("No structure loaded.\n\nUse Structure menu to create, load, or download a structure.")
        self.info_label.setWordWrap(True)
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        info_layout.addWidget(self.info_label)
        actions_layout.addWidget(info_group)
        
        actions_widget.setMaximumWidth(350)
        splitter.addWidget(actions_widget)
        
        # Set splitter sizes
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        try:
            splitter.setSizes([1000, 350])
        except Exception:
            pass
    
    def _on_create_structure(self) -> None:
        """Create a new structure using the dialog chain."""
        result = chain_dialogs(
            select_spacegroup,
            select_site_elements,
            back=True
        )
        # chain_dialogs now returns the actual result from the last dialog
        # select_site_elements returns an Atoms object or None
        if result is not None:
            self.set_structure(result)
    
    def _on_load_structure(self) -> None:
        """Load structure from file."""
        if ase_read is None:
            QMessageBox.warning(self, "Import Error", "ASE library not available. Cannot load structure files.")
            return
        
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Structure File",
            "",
            "Structure Files (*.cif *.xyz *.vasp *.POSCAR *.pdb);;All Files (*)"
        )
        
        if file_path:
            try:
                atoms = ase_read(file_path)
                self.set_structure(atoms)
                QMessageBox.information(self, "Success", f"Structure loaded from:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Load Error", f"Failed to load structure:\n{str(e)}")
    
    def _on_download_structure(self) -> None:
        """Download structure from Materials Project."""
        QMessageBox.information(
            self,
            "Materials Project",
            "Materials Project integration not yet implemented.\n\n"
            "This feature will allow downloading structures by material ID or searching the database."
        )
        # TODO: Implement Materials Project API integration
    
    def _on_save_structure(self) -> None:
        """Save current structure to file."""
        if self.atoms is None:
            return
        
        if ase_write is None:
            QMessageBox.warning(self, "Import Error", "ASE library not available. Cannot save structure files.")
            return
        
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save Structure File",
            "",
            "CIF Files (*.cif);;XYZ Files (*.xyz);;VASP POSCAR (*.vasp *.POSCAR);;PDB Files (*.pdb);;All Files (*)"
        )
        
        if file_path:
            try:
                ase_write(file_path, self.atoms)
                QMessageBox.information(self, "Success", f"Structure saved to:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Save Error", f"Failed to save structure:\n{str(e)}")
    
    def _on_create_sprkkr_input(self) -> None:
        """Create SPRKKR input file."""
        if self.atoms is None:
            return
        
        QMessageBox.information(
            self,
            "SPRKKR Input",
            "SPRKKR input file generation not yet implemented.\n\n"
            "This will create input files for SPRKKR calculations."
        )
        # TODO: Implement SPRKKR input generation
    
    def _on_run_sprkkr_calculation(self) -> None:
        """Run SPRKKR calculation."""
        if self.atoms is None:
            return
        
        QMessageBox.information(
            self,
            "Run Calculation",
            "SPRKKR calculation execution not yet implemented.\n\n"
            "This will submit and monitor SPRKKR calculations."
        )
        # TODO: Implement SPRKKR calculation execution
    
    def _on_about(self) -> None:
        """Show about dialog."""
        QMessageBox.about(
            self,
            "About Guy4ASE",
            "Guy4ASE - Structure Manager\n\n"
            "A tool for creating, loading, and manipulating atomic structures\n"
            "with integration for SPRKKR calculations.\n\n"
            "Built with ASE and PyQt6."
        )
    
    def set_structure(self, atoms: Any) -> None:  # atoms is ASE Atoms object
        """Set the current structure and update all views."""
        self.atoms = atoms
        self._update_structure_view()
        self._enable_actions(True)
    
    def _enable_actions(self, enabled: bool) -> None:
        """Enable or disable action buttons based on structure availability."""
        self.save_btn.setEnabled(enabled)
        self.create_input_btn.setEnabled(enabled)
        self.run_calc_btn.setEnabled(enabled)
    
    def _update_structure_view(self) -> None:
        """Update all structure visualization and information panels."""
        if self.atoms is None:
            self._clear_view()
            return
        
        self._update_visualization()
        self._update_lattice_params()
        self._update_positions_table()
        self._update_info_label()
    
    def _clear_view(self) -> None:
        """Clear all visualization panels."""
        # Show welcome screen, hide canvas
        self.welcome_widget.show()
        self.canvas.hide()
        self._site_colors = {}
        
        for lbl in self.lattice_labels.values():
            lbl.setText("–")
        
        for row in self.lattice_matrix_labels:
            for lbl in row:
                lbl.setText("–")
        
        self.positions_table.setRowCount(0)
        self.info_label.setText("No structure loaded.\n\nUse Structure menu to create, load, or download a structure.")
    
    def _update_visualization(self) -> None:
        """Update 3D visualization of the structure."""
        if self.atoms is None:
            return
        
        # Hide welcome screen, show canvas
        self.welcome_widget.hide()
        self.canvas.show()
        
        self.ax.clear()
        
        try:
            arrays = getattr(self.atoms, 'arrays', {})
            kinds = arrays.get('spacegroup_kinds')
            letters = list(self.atoms.info.get('kind_letters', [])) if self.atoms.info.get('kind_letters') else []
            lattice = np.array(self.atoms.get_cell(), dtype=float)
            has_lattice = lattice.shape == (3, 3) and np.linalg.norm(lattice) > 0

            if has_lattice:
                plot_lattice(self.ax, lattice)

            plotted = False
            if has_lattice and kinds is not None and letters:
                scaled = self.atoms.get_scaled_positions()
                color_map = self._compute_site_colors(letters)
                self._site_colors = color_map
                for idx, letter in enumerate(letters):
                    mask = kinds == idx
                    if not np.any(mask):
                        continue
                    pts = scaled[mask]
                    if pts.size == 0:
                        continue
                    plot_sites_in_lattice(
                        self.ax,
                        lattice,
                        pts,
                        color=color_map.get(letter, '#1f77b4'),
                        edgecolor='black',
                        linewidths=0.9,
                        s=80
                    )
                    plotted = True
            else:
                self._site_colors = {}

            if not plotted:
                positions = self.atoms.get_positions()
                if len(positions) > 0:
                    self.ax.scatter(
                        positions[:, 0], positions[:, 1], positions[:, 2],
                        c='#1f77b4', s=80, edgecolor='black', linewidths=1.0, depthshade=False
                    )

            self.canvas.draw()
        except Exception as e:
            print(f"Visualization error: {e}")
    
    def _update_lattice_params(self) -> None:
        """Update lattice parameters display."""
        if self.atoms is None:
            return
        
        try:
            cell = self.atoms.get_cell()
            lengths = cell.lengths()
            angles = cell.angles()
            
            self.lattice_labels['a'].setText(f"{lengths[0]:.4f} Å")
            self.lattice_labels['b'].setText(f"{lengths[1]:.4f} Å")
            self.lattice_labels['c'].setText(f"{lengths[2]:.4f} Å")
            self.lattice_labels['α'].setText(f"{angles[0]:.2f}°")
            self.lattice_labels['β'].setText(f"{angles[1]:.2f}°")
            self.lattice_labels['γ'].setText(f"{angles[2]:.2f}°")
            
            # Update matrix
            for i in range(3):
                for j in range(3):
                    self.lattice_matrix_labels[i][j].setText(f"{cell[i, j]:8.4f}")
        except Exception as e:
            print(f"Lattice params error: {e}")
    
    def _update_positions_table(self) -> None:
        """Update atomic positions table."""
        if self.atoms is None:
            self.positions_table.setRowCount(0)
            return
        
        try:
            positions = self.atoms.get_positions()
            symbols = self.atoms.get_chemical_symbols()
            arrays = getattr(self.atoms, 'arrays', {})
            kinds = arrays.get('spacegroup_kinds')
            occs = arrays.get('occupancy') if 'occupancy' in arrays else None
            site_letters = arrays.get('site_letters') if 'site_letters' in arrays else None
            letters = list(self.atoms.info.get('kind_letters', [])) if self.atoms.info.get('kind_letters') else []
            letter_lookup = {idx: letter for idx, letter in enumerate(letters)} if letters else {}
            color_lookup = self._site_colors if self._site_colors else {}
            
            self.positions_table.setRowCount(len(positions))
            
            for i, (sym, pos) in enumerate(zip(symbols, positions)):
                letter = None
                if site_letters is not None and i < len(site_letters):
                    raw_letter = site_letters[i]
                    if raw_letter not in (None, ""):
                        letter = str(raw_letter)
                elif kinds is not None and i < len(kinds):
                    letter = letter_lookup.get(int(kinds[i]))

                site_label = f"{letter} ({i + 1})" if letter else str(i + 1)
                comp_text = sym
                if occs is not None and i < len(occs):
                    comp_text = self._format_site_composition(occs[i])
                    if comp_text == "—":
                        comp_text = sym
                item_site = QTableWidgetItem(site_label)
                item_comp = QTableWidgetItem(comp_text)

                color_hex = None
                if letter and letter in color_lookup:
                    color_hex = color_lookup[letter]
                item_color = QTableWidgetItem(color_hex or "—")
                if color_hex:
                    qcolor = QColor(color_hex)
                    item_color.setBackground(qcolor)
                    item_color.setToolTip(color_hex)
                    r, g, b, _ = qcolor.getRgb()
                    luminance = 0.299 * r + 0.587 * g + 0.114 * b
                    if luminance < 140:
                        item_color.setForeground(QColor("white"))

                self.positions_table.setItem(i, 0, item_site)
                self.positions_table.setItem(i, 1, item_comp)
                self.positions_table.setItem(i, 2, item_color)
                self.positions_table.setItem(i, 3, QTableWidgetItem(f"{pos[0]:.4f}"))
                self.positions_table.setItem(i, 4, QTableWidgetItem(f"{pos[1]:.4f}"))
                self.positions_table.setItem(i, 5, QTableWidgetItem(f"{pos[2]:.4f}"))
            
            # Resize columns
            header = self.positions_table.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
            self.positions_table.setColumnWidth(0, 80)
            self.positions_table.setColumnWidth(1, 160)
            self.positions_table.setColumnWidth(2, 90)
        except Exception as e:
            print(f"Positions table error: {e}")
    
    def _update_info_label(self) -> None:
        """Update structure information label."""
        if self.atoms is None:
            return
        
        try:
            n_atoms = len(self.atoms)
            formula_raw = self.atoms.get_chemical_formula()
            assigned_counts = self._collect_assigned_counts()

            if assigned_counts:
                formula_text = self._format_formula_from_counts(assigned_counts)
                info_text = f"Assigned formula: {formula_text}\n"
            else:
                info_text = f"Formula: {formula_raw}\n"

            info_text += f"Number of atoms: {n_atoms}\n"

            info_text += "\nComposition:\n"
            if assigned_counts:
                for element, count in sorted(assigned_counts.items()):
                    info_text += f"  {element}: {count:.2f}\n"
            else:
                from collections import Counter
                symbols = self.atoms.get_chemical_symbols()
                species_count = Counter(symbols)
                for element, count in sorted(species_count.items()):
                    info_text += f"  {element}: {count}\n"

            self.info_label.setText(info_text)
        except Exception as e:
            print(f"Info label error: {e}")

    def _compute_site_colors(self, letters: Sequence[str]) -> Dict[str, str]:
        if not letters:
            return {}
        unique_letters = list(dict.fromkeys(letters))
        cmap = cm.get_cmap('tab20', max(len(unique_letters), 1))
        base_colors = list(getattr(cmap, 'colors', []))
        if not base_colors:
            steps = max(len(unique_letters), 1)
            base_colors = [cmap(i / max(steps - 1, 1)) for i in range(steps)]
        colors: Dict[str, str] = {}
        n = len(base_colors)
        for idx, letter in enumerate(unique_letters):
            rgba = base_colors[idx % n]
            colors[letter] = to_hex(rgba)
        return colors

    def _format_site_composition(self, occ_dict: Any) -> str:
        if not isinstance(occ_dict, dict) or not occ_dict:
            return "—"
        parts = []
        for species, value in sorted(occ_dict.items(), key=lambda kv: (-float(kv[1]), str(kv[0]))):
            try:
                val = float(value)
            except Exception:
                continue
            if val <= 0.0:
                continue
            sym = getattr(species, 'symbol', str(species))
            if abs(val - 1.0) < 1e-3:
                parts.append(sym)
            else:
                parts.append(f"{sym}{val:.2f}")
        return " + ".join(parts) if parts else "—"

    def _collect_assigned_counts(self) -> Dict[str, float]:
        arrays = getattr(self.atoms, 'arrays', {}) if self.atoms is not None else {}
        occs = arrays.get('occupancy') if 'occupancy' in arrays else None
        counts: Dict[str, float] = {}
        if occs is None or len(occs) == 0:
            return counts
        for entry in occs:
            if not isinstance(entry, dict):
                continue
            for species, value in entry.items():
                sym = getattr(species, 'symbol', str(species))
                try:
                    counts[sym] = counts.get(sym, 0.0) + float(value)
                except Exception:
                    continue
        return counts

    def _format_formula_from_counts(self, counts: Dict[str, float]) -> str:
        if not counts:
            return "—"
        positives = [v for v in counts.values() if v > 1e-6]
        if not positives:
            return "—"
        min_val = min(positives)
        normalized = {sym: value / min_val for sym, value in counts.items() if value > 1e-6}
        parts = []
        for sym, val in sorted(normalized.items()):
            if abs(val - 1.0) < 1e-2:
                suffix = ""
            elif abs(val - round(val)) < 1e-2:
                whole = int(round(val))
                suffix = "" if whole == 1 else str(whole)
            else:
                suffix = f"{val:.2f}"
            parts.append(f"{sym}{suffix}")
        return "".join(parts) if parts else "—"
