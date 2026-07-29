"""Compact guided editors for common SPR-KKR post-SCF tasks."""
from __future__ import annotations

import ast
from typing import Any, Optional
from pathlib import Path

import numpy as np
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from ase2sprkkr.input_parameters.input_parameters import InputParameters

from .input_parameters_dialog import edit_input_parameters


def number(section, option, label, minimum, maximum, step, default=None):
    return section, option, label, "number", (minimum, maximum, step, default)


def text(section, option, label, default=""):
    return section, option, label, "text", default


def array(section, option, label, default):
    return section, option, label, "array", default


def literal(section, option, label, default=None):
    return section, option, label, "literal", default


def choice(section, option, label, choices):
    return section, option, label, "choice", choices


def boolean(section, option, label):
    return section, option, label, "boolean", None


_TASK_FIELDS = {
    "dos": (
        ("Energy mesh", (number("ENERGY", "EMINEV", "Minimum energy (eV):", -1000., 1000., .1, -12.),
                         number("ENERGY", "EMAXEV", "Maximum energy (eV):", -1000., 1000., .1, 7.),
                         number("ENERGY", "NE", "Energy points:", 1, 10000, 1))),
        ("Numerical accuracy", (number("TAU", "NKTAB", "Special k-points:", 1, 1000000, 50),
                                number("ENERGY", "ImE", "Imaginary broadening (Ry):", 0., 10., .001),
                                number("SITES", "NL", "Angular-momentum cutoff:", 1, 8, 1))),
    ),
    "xas": (
        ("Absorption edge", (number("TASK", "IT", "Atomic type:", 1, 999, 1),
                             text("TASK", "CL", "Core level:", "2P"))),
        ("Light orientation", (number("TASK", "FRAMETET", "Electric-field polar angle (deg):", -360., 360., 1., 0.),
                               number("TASK", "FRAMEPHI", "Electric-field azimuth (deg):", -360., 360., 1., 0.))),
        ("Energy mesh", (number("ENERGY", "EMAX", "Maximum energy (Ry):", -20., 100., .1),
                         number("ENERGY", "NE", "Energy points:", 1, 10000, 1),
                         number("ENERGY", "GRID", "Energy contour grid:", 1, 10, 1),
                         number("ENERGY", "ImE", "Broadening (Ry):", 0., 10., .001))),
        ("Numerical accuracy", (number("TAU", "NKTAB", "Special k-points:", 1, 1000000, 50),
                                number("SITES", "NL", "Angular-momentum cutoff:", 1, 8, 1))),
    ),
    "arpes": (
        ("Photon", (number("SPEC_PH", "EPHOT", "Photon energy (eV):", 0., 100000., 1.),
                    number("SPEC_PH", "THETA", "Incidence theta (deg):", -360., 360., 1.),
                    number("SPEC_PH", "PHI", "Incidence phi (deg):", -360., 360., 1.),
                    choice("SPEC_PH", "POL_P", "Light polarization:", ("P", "S", "C+", "C-")))),
        ("Electron detector", (array("SPEC_EL", "THETA", "Theta scan [start, end] (deg):", [-20., 20.]),
                               number("SPEC_EL", "NT", "Theta samples:", 1, 100000, 1, 200),
                               array("SPEC_EL", "PHI", "Phi scan [start, end] (deg):", [0., 0.]),
                               number("SPEC_EL", "NP", "Phi samples:", 1, 100000, 1, 1),
                               number("SPEC_EL", "SPOL", "Spin-polarization mode:", 0, 10, 1, 4))),
        ("Energy mesh", (number("ENERGY", "EMINEV", "Minimum energy (eV):", -10000., 10000., .1),
                         number("ENERGY", "EMAXEV", "Maximum energy (eV):", -10000., 10000., .1),
                         number("ENERGY", "NE", "Energy points:", 1, 10000, 1),
                         number("ENERGY", "EWORK_EV", "Work function (eV):", 0., 100., .1),
                         number("ENERGY", "IMV_INI_EV", "Initial-state broadening (eV):", 0., 100., .01),
                         number("ENERGY", "IMV_FIN_EV", "Final-state broadening (eV):", 0., 100., .1))),
        ("Surface geometry", (array("TASK", "MILLER_HKL", "Surface Miller indices [h, k, l]:", [0, 0, 1]),
                              number("TASK", "IQ_AT_SURF", "Surface site:", 1, 999999, 1),
                              array("SPEC_STR", "N_LAYDBL", "Principal layers [left, right]:", [10, 10]),
                              number("SPEC_STR", "N_LAYER", "Surface layers:", 1, 10000, 1))),
        ("Momentum map (optional)", (literal("SPEC_EL", "KA", "Map origin [kx, ky]:"),
                                     literal("SPEC_EL", "K1", "First map vector [kx, ky]:"),
                                     literal("SPEC_EL", "K2", "Second map vector [kx, ky]:"),
                                     literal("SPEC_EL", "NK1", "Points along first vector:"),
                                     literal("SPEC_EL", "NK2", "Points along second vector:"),
                                     literal("SPEC_EL", "PSPIN", "Spin projection [x, y, z]:"))),
        ("Numerical accuracy", (number("TAU", "NKTAB", "Special k-points:", 1, 1000000, 50),
                                number("SITES", "NL", "Angular-momentum cutoff:", 1, 8, 1))),
    ),
    "bsf": (
        ("Energy mesh", (number("ENERGY", "EMINEV", "Minimum energy (eV):", -1000., 1000., .1, -4.),
                         number("ENERGY", "EMAXEV", "Maximum energy (eV):", -1000., 1000., .1, 2.),
                         number("ENERGY", "NE", "Energy points:", 1, 10000, 1, 400),
                         number("ENERGY", "ImE", "Imaginary broadening (Ry):", 0., 10., .001))),
        ("K-space path", (number("TASK", "NK", "Total points along path:", 2, 100000, 10),)),
        ("Numerical accuracy", (number("TAU", "NKTAB2D", "2D special k-points:", 1, 1000000, 10),
                                number("TAU", "NKTAB3D", "3D special k-points:", 1, 1000000, 50),
                                number("TAU", "CLURAD", "Cluster radius:", 0., 100., .1, 2.7),
                                number("SITES", "NL", "Angular-momentum cutoff:", 1, 8, 1))),
    ),
    "jxc": (
        ("Exchange interactions", (number("TASK", "CLURAD", "Interaction cluster radius:", 0., 100., .1),
                                   boolean("TASK", "DMI", "Calculate Dzyaloshinskii–Moriya interaction"))),
        ("Energy and accuracy", (number("ENERGY", "NE", "Energy points:", 1, 10000, 1),
                                 number("TAU", "NKTAB", "Special k-points:", 1, 1000000, 50),
                                 number("SITES", "NL", "Angular-momentum cutoff:", 1, 8, 1),
                                 boolean("MODE", "LLOYD", "Use Lloyd formula"),
                                 choice("MODE", "MODE", "Relativity and spin mode:",
                                        ("SP-SREL", "SP-REL", "SREL", "NREL")))),
    ),
}


class GuidedTaskParametersDialog(QDialog):
    def __init__(self, task: str, params: InputParameters, parent: Optional[QWidget] = None,
                 *, directory: Optional[str] = None, atoms: Any = None):
        super().__init__(parent)
        self.task, self.params, self.directory, self.atoms = task, params, directory or "", atoms
        self._editors: list[tuple[str, str, QWidget]] = []
        # These options are used by the bundled examples but are intentionally
        # extensible/custom in the corresponding ase2sprkkr definitions.
        if task == "xas" and "EMAX" not in params.ENERGY:
            params.ENERGY.add("EMAX", 4.0)
        if task == "jxc" and "DMI" not in params.TASK:
            params.TASK.add("DMI", False)
        if task == "bsf" and params.TASK.KPATH() is None:
            params.TASK.KPATH.set(1)
        self.setWindowTitle(f"{task.upper()} Calculation Setup")
        self.resize(780, 720)
        root = QVBoxLayout(self)
        intro = QLabel("Configure the main physical and numerical parameters. All remaining options are available in Expert settings.")
        intro.setWordWrap(True); root.addWidget(intro)
        row = QHBoxLayout(); row.addWidget(QLabel("Working directory:"))
        self.directory_edit = QLineEdit(self.directory); row.addWidget(self.directory_edit, 1)
        browse = QPushButton("Browse…"); browse.clicked.connect(self._choose_directory); row.addWidget(browse); root.addLayout(row)
        contents = QWidget(self); contents_layout = QVBoxLayout(contents)
        for title, fields in _TASK_FIELDS[task]:
            box = QGroupBox(title); form = QFormLayout(box)
            for section, option, label, kind, settings in fields:
                opt = getattr(getattr(params, section), option)
                editor = self._create_editor(kind, settings, opt())
                editor.setToolTip(opt.info or "")
                form.addRow(label, editor); self._editors.append((section, option, editor))
            if task == "bsf" and title == "K-space path":
                path_row = QHBoxLayout()
                self._predefined_path = QComboBox()
                self._predefined_path.addItem("Custom", None)
                for path_number in range(1, 6):
                    self._predefined_path.addItem(f"Predefined {path_number}", path_number)
                current_path = self.params.TASK.KPATH()
                self._predefined_path.setCurrentIndex(0 if current_path is None else int(current_path))
                self._predefined_path.currentIndexChanged.connect(self._select_predefined_path)
                self._path_label = QLabel(); self._update_path_label()
                edit_path = QPushButton("Edit K-path…")
                edit_path.clicked.connect(self._edit_k_path)
                path_row.addWidget(self._predefined_path); path_row.addWidget(self._path_label, 1); path_row.addWidget(edit_path)
                form.addRow("Path:", path_row)
            contents_layout.addWidget(box)
        contents_layout.addStretch(1)
        scroll = QScrollArea(self); scroll.setWidgetResizable(True); scroll.setWidget(contents)
        root.addWidget(scroll, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        calculate = QPushButton("Calculate")
        calculate.setIcon(QIcon(str(Path(__file__).resolve().parent.parent / "assets" / "icons" / "system-run.svg")))
        buttons.addButton(calculate, QDialogButtonBox.ButtonRole.AcceptRole)
        load = QPushButton("Load input…"); buttons.addButton(load, QDialogButtonBox.ButtonRole.ActionRole)
        expert = QPushButton("Expert settings…"); buttons.addButton(expert, QDialogButtonBox.ButtonRole.ActionRole)
        calculate.clicked.connect(self._accept); load.clicked.connect(self._load); expert.clicked.connect(self._expert)
        buttons.rejected.connect(self.reject); root.addWidget(buttons)

    @staticmethod
    def _first(value: Any) -> Any:
        if isinstance(value, np.ndarray): return value.flat[0] if value.size else None
        return value

    def _create_editor(self, kind: str, settings: Any, value: Any) -> QWidget:
        if kind == "number":
            minimum, maximum, step, default = settings
            value = self._first(value)
            value = default if value is None else value
            if isinstance(step, int):
                editor = QSpinBox(); editor.setRange(int(minimum), int(maximum)); editor.setSingleStep(step)
                value = 0 if value is None else int(value)
            else:
                editor = QDoubleSpinBox(); editor.setDecimals(6)
                editor.setRange(minimum, maximum); editor.setSingleStep(step)
                value = 0 if value is None else float(value)
            editor.setKeyboardTracking(False); editor.setValue(value)
            return editor
        if kind == "boolean":
            editor = QCheckBox(); editor.setChecked(bool(value)); return editor
        if kind == "choice":
            editor = QComboBox(); editor.addItems(settings)
            index = editor.findText(str(value)); editor.setCurrentIndex(max(0, index)); return editor
        editor = QLineEdit()
        if value is None: value = settings
        if value is None:
            rendered = ""
        elif kind in {"array", "literal"}:
            rendered = repr(value.tolist() if isinstance(value, np.ndarray) else value)
        else:
            rendered = str(value)
        editor.setText(rendered)
        editor.setProperty("value_kind", kind)
        return editor

    def _apply(self) -> None:
        for section, option, editor in self._editors:
            if isinstance(editor, (QSpinBox, QDoubleSpinBox)):
                value = editor.value()
            elif isinstance(editor, QCheckBox):
                value = editor.isChecked()
            elif isinstance(editor, QComboBox):
                value = editor.currentText()
            else:
                value = editor.text().strip()
                if editor.property("value_kind") in {"array", "literal"}:
                    if not value:
                        getattr(getattr(self.params, section), option).clear()
                        continue
                    value = ast.literal_eval(value)
            getattr(getattr(self.params, section), option).set(value)

    def _update_path_label(self) -> None:
        if not hasattr(self, "_path_label"): return
        if self.params.TASK.KPATH() is not None:
            label = f"Predefined path {self.params.TASK.KPATH()}"
        else:
            try: label = f"Custom path, {len(self.params.TASK.KA())} segment(s)"
            except Exception: label = "No path selected"
        self._path_label.setText(label)

    def _edit_k_path(self) -> None:
        if self.atoms is None:
            QMessageBox.warning(self, "K-path", "A structure is required to edit the Brillouin-zone path.")
            return
        try:
            self.params.TASK.k_path_gui(self.atoms)
            self._predefined_path.blockSignals(True)
            self._predefined_path.setCurrentIndex(0)
            self._predefined_path.blockSignals(False)
            self._update_path_label()
        except Exception as exc:
            QMessageBox.critical(self, "K-path Error", str(exc))

    def _select_predefined_path(self) -> None:
        path = self._predefined_path.currentData()
        if path is None:
            return
        self.params.TASK.KPATH.set(path)
        self._update_path_label()

    def _choose_directory(self) -> bool:
        path = QFileDialog.getExistingDirectory(self, "Select Calculation Directory", self.directory_edit.text())
        if not path: return False
        self.directory_edit.setText(path); return True

    def _accept(self) -> None:
        try: self._apply()
        except Exception as exc: QMessageBox.critical(self, "Invalid Settings", str(exc)); return
        if not self.directory_edit.text().strip() and not self._choose_directory(): return
        self.directory = self.directory_edit.text().strip(); self.accept()

    def _expert(self) -> None:
        try:
            self._apply()
            result = edit_input_parameters(self.params.copy(copy_values=True), parent=self,
                calculate_mode=True, directory=self.directory_edit.text().strip(), return_directory=True)
        except Exception as exc: QMessageBox.critical(self, "Settings Error", str(exc)); return
        if result is not None:
            self.params, self.directory = result; self.accept()

    def _load(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load SPRKKR Input File", "", "SPRKKR Input Files (*.inp *.in *.txt);;All Files (*)")
        if not path: return
        try:
            loaded = InputParameters.from_file(path)
            result = edit_input_parameters(loaded, parent=self, show_changed_only=True,
                calculate_mode=True, directory=self.directory_edit.text().strip(), return_directory=True)
        except Exception as exc: QMessageBox.critical(self, "Load Error", str(exc)); return
        if result is not None: self.params, self.directory = result; self.accept()


def select_guided_task_parameters(task: str, parent: Optional[QWidget] = None,
                                  *, directory: Optional[str] = None,
                                  atoms: Any = None) -> Optional[tuple[InputParameters, str]]:
    task = task.lower()
    parameter_task = "bsfek" if task == "bsf" else task
    dialog = GuidedTaskParametersDialog(task, InputParameters.create(parameter_task), parent,
                                        directory=directory, atoms=atoms)
    if dialog.exec() != QDialog.DialogCode.Accepted: return None
    return dialog.params, dialog.directory
