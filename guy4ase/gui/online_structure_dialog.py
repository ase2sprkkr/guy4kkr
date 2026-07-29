from __future__ import annotations

import re
from typing import Callable, Optional, Sequence

from ase.data import atomic_numbers
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt6.QtCore import QObject, QRunnable, Qt, QThreadPool, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from guy4ase.online_databases import (
    CodOptimadeProvider,
    DownloadedStructure,
    SearchPage,
    StructureDatabaseProvider,
    StructureSearchQuery,
    StructureSummary,
)

from .lattice import plot_atoms_preview


class _WorkerSignals(QObject):
    succeeded = pyqtSignal(int, object)
    failed = pyqtSignal(int, str)


class _ProviderWorker(QRunnable):
    def __init__(self, token: int, operation: Callable[[], object]):
        super().__init__()
        self.token = token
        self.operation = operation
        self.signals = _WorkerSignals()

    def run(self) -> None:
        try:
            result = self.operation()
        except Exception as exc:
            self.signals.failed.emit(self.token, str(exc))
        else:
            self.signals.succeeded.emit(self.token, result)


class OnlineStructureDialog(QDialog):
    """Search an online provider and return a fully downloaded ASE structure."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        providers: Optional[Sequence[StructureDatabaseProvider]] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Download Structure from Online Database")
        self.resize(1100, 720)

        available = tuple(providers) if providers is not None else (
            CodOptimadeProvider(),
        )
        if not available:
            raise ValueError("At least one online structure provider is required.")
        self._providers = {provider.id: provider for provider in available}
        self._thread_pool = QThreadPool.globalInstance()
        self._search_token = 0
        self._fetch_token = 0
        self._last_query: Optional[StructureSearchQuery] = None
        self._current_page: Optional[SearchPage] = None
        self._selected_summary: Optional[StructureSummary] = None
        self._downloaded: Optional[DownloadedStructure] = None

        self._build_ui(available)
        self._update_provider_capabilities()
        self._clear_detail()

    @property
    def selected_atoms(self):
        return self._downloaded.atoms if self._downloaded is not None else None

    def _build_ui(
        self, providers: Sequence[StructureDatabaseProvider]
    ) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)
        root.addWidget(splitter, 1)

        filters = QFrame(splitter)
        filters.setFrameShape(QFrame.Shape.StyledPanel)
        filters.setMinimumWidth(280)
        filters.setMaximumWidth(440)
        filters_layout = QVBoxLayout(filters)
        filters_layout.setContentsMargins(14, 14, 14, 14)

        heading = QLabel("Search", filters)
        heading.setStyleSheet("font-size: 14pt; font-weight: 600;")
        filters_layout.addWidget(heading)

        form = QFormLayout()
        self._provider_combo = QComboBox(filters)
        for provider in providers:
            self._provider_combo.addItem(provider.name, provider.id)
        self._provider_combo.currentIndexChanged.connect(
            self._provider_changed
        )
        form.addRow("Provider:", self._provider_combo)

        self._text_edit = QLineEdit(filters)
        self._text_edit.setPlaceholderText("Formula, name, or database ID")
        self._text_edit.returnPressed.connect(self._start_new_search)
        form.addRow("Query:", self._text_edit)

        self._elements_edit = QLineEdit(filters)
        self._elements_edit.setPlaceholderText("Fe, O")
        self._elements_edit.returnPressed.connect(self._start_new_search)
        form.addRow("Elements:", self._elements_edit)

        self._element_match = QComboBox(filters)
        self._element_match.addItem("Exactly these elements", True)
        self._element_match.addItem("Contains these elements", False)
        form.addRow("Element match:", self._element_match)

        self._space_group_spin = QSpinBox(filters)
        self._space_group_spin.setRange(0, 230)
        self._space_group_spin.setSpecialValueText("Any")
        form.addRow("Space group:", self._space_group_spin)

        self._max_sites_spin = QSpinBox(filters)
        self._max_sites_spin.setRange(0, 10000)
        self._max_sites_spin.setSpecialValueText("Any")
        form.addRow("Maximum sites:", self._max_sites_spin)
        filters_layout.addLayout(form)

        self._hide_duplicates = QCheckBox("Hide duplicate entries", filters)
        self._hide_duplicates.setChecked(True)
        filters_layout.addWidget(self._hide_duplicates)
        self._hide_invalid = QCheckBox("Hide invalid or retracted entries", filters)
        self._hide_invalid.setChecked(True)
        filters_layout.addWidget(self._hide_invalid)
        self._ordered_only = QCheckBox("Ordered structures only", filters)
        filters_layout.addWidget(self._ordered_only)
        filters_layout.addStretch(1)

        search_buttons = QHBoxLayout()
        clear_button = QPushButton("Clear", filters)
        clear_button.clicked.connect(self._clear_filters)
        search_buttons.addWidget(clear_button)
        self._search_button = QPushButton("Search", filters)
        self._search_button.setDefault(True)
        self._search_button.clicked.connect(self._start_new_search)
        search_buttons.addWidget(self._search_button)
        filters_layout.addLayout(search_buttons)
        splitter.addWidget(filters)

        results = QWidget(splitter)
        results_layout = QVBoxLayout(results)
        results_layout.setContentsMargins(8, 0, 0, 0)

        self._search_status = QLabel(
            "Set filters and press Search.", results
        )
        self._search_status.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        results_layout.addWidget(self._search_status)

        result_splitter = QSplitter(Qt.Orientation.Vertical, results)
        result_splitter.setChildrenCollapsible(False)
        result_splitter.setHandleWidth(7)
        results_layout.addWidget(result_splitter, 1)

        table_panel = QWidget(result_splitter)
        table_layout = QVBoxLayout(table_panel)
        table_layout.setContentsMargins(0, 0, 0, 0)
        self._table = QTableWidget(0, 8, table_panel)
        self._table.setHorizontalHeaderLabels(
            ("Formula", "Name", "SG", "Sites", "Method", "Year", "ID", "Warnings")
        )
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self._table.itemSelectionChanged.connect(self._selection_changed)
        self._table.itemDoubleClicked.connect(self._open_if_ready)
        table_layout.addWidget(self._table, 1)

        navigation = QHBoxLayout()
        self._previous_button = QPushButton("Previous", table_panel)
        self._previous_button.clicked.connect(self._previous_page)
        navigation.addWidget(self._previous_button)
        navigation.addStretch(1)
        self._next_button = QPushButton("Next", table_panel)
        self._next_button.clicked.connect(self._next_page)
        navigation.addWidget(self._next_button)
        table_layout.addLayout(navigation)
        result_splitter.addWidget(table_panel)

        detail_panel = QWidget(result_splitter)
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(0, 4, 0, 0)
        detail_heading = QLabel("Selected structure", detail_panel)
        detail_heading.setStyleSheet("font-weight: 600;")
        detail_layout.addWidget(detail_heading)
        self._detail_status = QLabel(detail_panel)
        self._detail_status.setWordWrap(True)
        self._detail_status.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        detail_layout.addWidget(self._detail_status)

        detail_content = QSplitter(Qt.Orientation.Horizontal, detail_panel)
        detail_content.setChildrenCollapsible(False)
        self._figure = Figure(figsize=(4, 3))
        self._axes = self._figure.add_subplot(111, projection="3d")
        self._canvas = FigureCanvas(self._figure)
        self._canvas.setMinimumSize(280, 190)
        self._canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        detail_content.addWidget(self._canvas)
        self._metadata = QTextBrowser(detail_content)
        self._metadata.setOpenExternalLinks(False)
        self._metadata.setMinimumWidth(280)
        detail_content.addWidget(self._metadata)
        detail_content.setStretchFactor(0, 1)
        detail_content.setStretchFactor(1, 1)
        detail_layout.addWidget(detail_content, 1)
        result_splitter.addWidget(detail_panel)
        result_splitter.setStretchFactor(0, 3)
        result_splitter.setStretchFactor(1, 2)
        result_splitter.setSizes([390, 260])

        splitter.addWidget(results)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([330, 750])

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel, parent=self
        )
        self._open_button = buttons.addButton(
            "Open Structure", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._open_button.setEnabled(False)
        buttons.accepted.connect(self._accept_downloaded)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _provider(self) -> StructureDatabaseProvider:
        provider_id = self._provider_combo.currentData()
        return self._providers[str(provider_id)]

    def _update_provider_capabilities(self) -> None:
        capabilities = self._provider().capabilities
        self._text_edit.setEnabled(capabilities.formula_or_name)
        self._elements_edit.setEnabled(capabilities.elements)
        self._element_match.setEnabled(capabilities.elements)
        self._space_group_spin.setEnabled(capabilities.space_group)
        self._max_sites_spin.setEnabled(capabilities.max_sites)
        self._hide_duplicates.setEnabled(capabilities.duplicate_filter)
        self._hide_invalid.setEnabled(capabilities.validity_filter)
        self._ordered_only.setEnabled(capabilities.disorder_filter)
        unsupported = "The selected provider does not support this filter."
        self._max_sites_spin.setToolTip(
            "" if capabilities.max_sites else unsupported
        )
        self._ordered_only.setToolTip(
            "" if capabilities.disorder_filter else unsupported
        )

    def _provider_changed(self) -> None:
        self._search_token += 1
        self._fetch_token += 1
        self._last_query = None
        self._current_page = None
        self._selected_summary = None
        self._table.setRowCount(0)
        self._previous_button.setEnabled(False)
        self._next_button.setEnabled(False)
        self._set_search_status("Set filters and press Search.")
        self._update_provider_capabilities()
        self._clear_detail()

    def _clear_filters(self) -> None:
        self._text_edit.clear()
        self._elements_edit.clear()
        self._element_match.setCurrentIndex(0)
        self._space_group_spin.setValue(0)
        self._max_sites_spin.setValue(0)
        self._hide_duplicates.setChecked(True)
        self._hide_invalid.setChecked(True)
        self._ordered_only.setChecked(False)
        self._text_edit.setFocus()

    def _query(self) -> StructureSearchQuery:
        elements = []
        invalid = []
        for item in re.split(r"[\s,;]+", self._elements_edit.text().strip()):
            if not item:
                continue
            symbol = item[:1].upper() + item[1:].lower()
            if symbol not in atomic_numbers:
                invalid.append(item)
            elif symbol not in elements:
                elements.append(symbol)
        if invalid:
            raise ValueError(
                "Unknown element symbol(s): " + ", ".join(invalid)
            )
        return StructureSearchQuery(
            text=self._text_edit.text().strip(),
            elements=tuple(elements),
            exact_elements=bool(self._element_match.currentData()),
            space_group=self._space_group_spin.value() or None,
            max_sites=self._max_sites_spin.value() or None,
            hide_duplicates=self._hide_duplicates.isChecked(),
            hide_invalid=self._hide_invalid.isChecked(),
            ordered_only=self._ordered_only.isChecked(),
        )

    def _start_new_search(self) -> None:
        try:
            query = self._query()
        except ValueError as exc:
            self._set_search_status(str(exc), error=True)
            return
        self._last_query = query
        self._start_search(query)

    def _start_search(
        self,
        query: StructureSearchQuery,
        page_url: Optional[str] = None,
    ) -> None:
        provider = self._provider()
        self._search_token += 1
        token = self._search_token
        self._fetch_token += 1
        self._downloaded = None
        self._selected_summary = None
        self._open_button.setEnabled(False)
        self._search_button.setEnabled(False)
        self._previous_button.setEnabled(False)
        self._next_button.setEnabled(False)
        self._set_search_status("Searching…")
        if page_url is None:
            self._current_page = None
            self._table.setRowCount(0)
            self._clear_detail()

        worker = _ProviderWorker(
            token,
            lambda: provider.search(query, page_url=page_url),
        )
        worker.signals.succeeded.connect(self._search_succeeded)
        worker.signals.failed.connect(self._search_failed)
        self._thread_pool.start(worker)

    def _search_succeeded(self, token: int, result: object) -> None:
        if token != self._search_token:
            return
        self._search_button.setEnabled(True)
        if not isinstance(result, SearchPage):
            self._search_failed(token, "The provider returned an invalid search page.")
            return
        self._current_page = result
        self._fill_table(result)
        self._previous_button.setEnabled(bool(result.previous_url))
        self._next_button.setEnabled(bool(result.next_url))
        count = len(result.results)
        if result.total is None:
            message = f"{count} result{'s' if count != 1 else ''} on this page."
        else:
            message = (
                f"{count} result{'s' if count != 1 else ''} on this page; "
                f"{result.total} matching entries."
            )
        self._set_search_status(message)

    def _search_failed(self, token: int, message: str) -> None:
        if token != self._search_token:
            return
        self._search_button.setEnabled(True)
        self._previous_button.setEnabled(
            bool(self._current_page and self._current_page.previous_url)
        )
        self._next_button.setEnabled(
            bool(self._current_page and self._current_page.next_url)
        )
        self._set_search_status(message or "The database request failed.", error=True)

    def _fill_table(self, page: SearchPage) -> None:
        self._table.blockSignals(True)
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(page.results))
        for row, summary in enumerate(page.results):
            values = (
                summary.formula,
                summary.name,
                summary.space_group
                or (
                    str(summary.space_group_number)
                    if summary.space_group_number is not None
                    else ""
                ),
                "" if summary.site_count is None else str(summary.site_count),
                summary.method,
                "" if summary.year is None else str(summary.year),
                summary.entry_id,
                "; ".join(summary.warnings),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, summary)
                self._table.setItem(row, column, item)
        self._table.setSortingEnabled(True)
        self._table.blockSignals(False)
        self._clear_detail()

    def _selection_changed(self) -> None:
        selected = self._table.selectedItems()
        if not selected:
            self._selected_summary = None
            self._fetch_token += 1
            self._clear_detail()
            return
        item = self._table.item(selected[0].row(), 0)
        summary = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(summary, StructureSummary):
            return
        self._selected_summary = summary
        self._downloaded = None
        self._open_button.setEnabled(False)
        self._show_summary(summary)
        self._start_fetch(summary)

    def _start_fetch(self, summary: StructureSummary) -> None:
        provider = self._providers[summary.provider_id]
        self._fetch_token += 1
        token = self._fetch_token
        self._set_detail_status("Downloading structure…")
        worker = _ProviderWorker(token, lambda: provider.fetch(summary))
        worker.signals.succeeded.connect(self._fetch_succeeded)
        worker.signals.failed.connect(self._fetch_failed)
        self._thread_pool.start(worker)

    def _fetch_succeeded(self, token: int, result: object) -> None:
        if token != self._fetch_token:
            return
        if not isinstance(result, DownloadedStructure):
            self._fetch_failed(
                token, "The provider returned an invalid structure."
            )
            return
        if (
            self._selected_summary is None
            or result.summary.entry_id != self._selected_summary.entry_id
        ):
            return
        self._downloaded = result
        self._open_button.setEnabled(True)
        self._show_downloaded(result)

    def _fetch_failed(self, token: int, message: str) -> None:
        if token != self._fetch_token:
            return
        self._downloaded = None
        self._open_button.setEnabled(False)
        self._set_detail_status(
            message or "The selected structure could not be downloaded.",
            error=True,
        )

    def _show_summary(self, summary: StructureSummary) -> None:
        lines = [
            summary.formula or summary.entry_id,
            f"Provider ID: {summary.entry_id}",
        ]
        if summary.name:
            lines.append(f"Name: {summary.name}")
        if summary.space_group:
            lines.append(f"Space group: {summary.space_group}")
        if summary.space_group_number is not None:
            lines.append(f"Space-group number: {summary.space_group_number}")
        if summary.site_count is not None:
            lines.append(f"Sites: {summary.site_count}")
        if summary.method:
            lines.append(f"Method: {summary.method}")
        if summary.year is not None:
            lines.append(f"Year: {summary.year}")
        if summary.doi:
            lines.append(f"DOI: {summary.doi}")
        self._metadata.setPlainText("\n".join(lines))
        self._axes.clear()
        self._canvas.draw_idle()

    def _show_downloaded(self, result: DownloadedStructure) -> None:
        plot_atoms_preview(
            self._axes,
            result.atoms,
            canvas=self._canvas,
        )
        provenance = result.provenance
        lines = [
            result.summary.formula or result.summary.entry_id,
            f"Provider: {provenance.provider_name}",
            f"Entry ID: {provenance.entry_id}",
            f"Atoms/sites: {len(result.atoms)}",
            f"License: {provenance.license_name}",
        ]
        if result.summary.name:
            lines.insert(1, f"Name: {result.summary.name}")
        if result.summary.space_group:
            lines.append(f"Space group: {result.summary.space_group}")
        if provenance.method:
            lines.append(f"Method: {provenance.method}")
        if provenance.doi:
            lines.append(f"DOI: {provenance.doi}")
        if provenance.temperature_kelvin is not None:
            lines.append(
                f"Cell temperature: {provenance.temperature_kelvin:g} K"
            )
        if provenance.pressure_kpa is not None:
            lines.append(f"Cell pressure: {provenance.pressure_kpa:g} kPa")
        lines.append(f"Source: {provenance.entry_url}")
        self._metadata.setPlainText("\n".join(lines))
        if result.warnings:
            self._set_detail_status(
                "Warning: " + " ".join(result.warnings), warning=True
            )
        else:
            self._set_detail_status("Structure downloaded and ready to open.")

    def _clear_detail(self) -> None:
        self._downloaded = None
        self._open_button.setEnabled(False)
        self._detail_status.setText("Select a result to download its structure.")
        self._detail_status.setStyleSheet("")
        self._metadata.clear()
        self._axes.clear()
        self._canvas.draw_idle()

    def _set_search_status(self, message: str, *, error: bool = False) -> None:
        self._search_status.setText(message)
        self._search_status.setStyleSheet(
            "color: #b00020;" if error else ""
        )

    def _set_detail_status(
        self,
        message: str,
        *,
        error: bool = False,
        warning: bool = False,
    ) -> None:
        self._detail_status.setText(message)
        if error:
            color = "#b00020"
        elif warning:
            color = "#a15c00"
        else:
            color = ""
        self._detail_status.setStyleSheet(f"color: {color};" if color else "")

    def _previous_page(self) -> None:
        if (
            self._last_query is not None
            and self._current_page is not None
            and self._current_page.previous_url
        ):
            self._start_search(
                self._last_query, self._current_page.previous_url
            )

    def _next_page(self) -> None:
        if (
            self._last_query is not None
            and self._current_page is not None
            and self._current_page.next_url
        ):
            self._start_search(self._last_query, self._current_page.next_url)

    def _open_if_ready(self) -> None:
        if self._downloaded is not None:
            self.accept()

    def _accept_downloaded(self) -> None:
        if self._downloaded is not None:
            self.accept()

    def reject(self) -> None:
        self._search_token += 1
        self._fetch_token += 1
        super().reject()


def select_online_structure(parent: Optional[QWidget] = None):
    dialog = OnlineStructureDialog(parent)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.selected_atoms
    return None
