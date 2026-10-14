"""Reusable detached-structure workflows."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ase.io import read as ase_read
from ase.io.formats import ioformats
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QWidget

from guy4ase.gui.application.materialized import Materialized
from guy4ase.gui.application.structure_provenance import (
    StructureProvenance,
    materialize_structure,
)
from guy4ase.gui.dialogs.structures.database import select_structure_prototype
from guy4ase.gui.dialogs.structures.element_assignment import select_site_elements
from guy4ase.gui.dialogs.structures.online_database import select_online_structure
from guy4ase.gui.dialogs.structures.spacegroup_selector import (
    select_spacegroup,
    select_spacegroup_from_prototype,
)
from guy4ase.gui.misc.dialog_flow import chain_dialogs
from guy4ase.gui.misc.modal_task import run_modal_task


@dataclass(frozen=True)
class StructureCandidate:
    """A detached materialized structure and optional UI source path."""

    structure: Materialized[Any, StructureProvenance]
    source_path: Path | None = None

    @property
    def atoms(self) -> Any:
        return self.structure.get()


def structure_open_filter() -> str:
    extensions = sorted(
        f"*.{extension}"
        for file_format in ioformats.values()
        for extension in (file_format.extensions or [])
    )
    return f"Structure Files ({' '.join(extensions)});;All Files (*)"


def choose_structure_file(
    parent: QWidget | None,
    *,
    title: str = "Load Structure File",
    chooser: Callable[..., tuple[str, str]] | None = None,
) -> Path | None:
    choose = chooser or QFileDialog.getOpenFileName
    file_path, _ = choose(parent, title, "", structure_open_filter())
    if not file_path:
        return None
    return Path(file_path).resolve()


def load_structure_candidate(
    file_path: str | Path,
    parent: QWidget | None,
    *,
    reader: Callable[[Path], Any] | None = None,
) -> StructureCandidate | None:
    """Load structure and bind runtime value to provenance before publication."""
    path = Path(file_path).resolve()
    read = reader or ase_read
    try:
        loaded = run_modal_task(
            parent,
            lambda: read(path),
            title="Loading Structure",
            label="Reading structure…",
        )
    except Exception as exc:  # noqa: BLE001 - ASE/backend readers vary
        QMessageBox.critical(
            parent,
            "Load Error",
            f"Failed to load structure:\n{exc}",
        )
        return None
    structure = (
        loaded if isinstance(loaded, Materialized) else materialize_structure(loaded)
    )
    return StructureCandidate(structure=structure, source_path=path)


def choose_structure_candidate(
    parent: QWidget | None,
    *,
    title: str = "Load Structure File",
    chooser: Callable[..., tuple[str, str]] | None = None,
    reader: Callable[[Path], Any] | None = None,
) -> StructureCandidate | None:
    path = choose_structure_file(parent, title=title, chooser=chooser)
    if path is None:
        return None
    return load_structure_candidate(path, parent, reader=reader)


def _candidate(atoms: Any | None) -> StructureCandidate | None:
    return None if atoms is None else StructureCandidate(materialize_structure(atoms))


def create_structure_candidate(
    parent: QWidget | None,
    *,
    chain: Callable[..., Any] | None = None,
    spacegroup_selector: Callable[..., Any] | None = None,
    site_selector: Callable[..., Any] | None = None,
) -> StructureCandidate | None:
    run_chain = chain or chain_dialogs
    select_group = spacegroup_selector or select_spacegroup
    select_sites = site_selector or select_site_elements
    return _candidate(run_chain(select_group, select_sites, parent=parent))


def create_structure_from_database_candidate(
    parent: QWidget | None,
    *,
    chain: Callable[..., Any] | None = None,
    prototype_selector: Callable[..., Any] | None = None,
    spacegroup_selector: Callable[..., Any] | None = None,
    site_selector: Callable[..., Any] | None = None,
) -> StructureCandidate | None:
    run_chain = chain or chain_dialogs
    select_prototype = prototype_selector or select_structure_prototype
    select_group = spacegroup_selector or select_spacegroup_from_prototype
    select_sites = site_selector or select_site_elements
    return _candidate(
        run_chain(
            select_prototype,
            select_group,
            select_sites,
            parent=parent,
        )
    )


def download_structure_candidate(
    parent: QWidget | None,
    *,
    selector: Callable[..., Any] | None = None,
) -> StructureCandidate | None:
    select = selector or select_online_structure
    return _candidate(select(parent=parent))
