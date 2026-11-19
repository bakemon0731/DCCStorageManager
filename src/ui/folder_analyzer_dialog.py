"""Folder analysis dialog for DCC Storage Manager.

The dialog owns presentation. FolderScanWorker runs the scan outside the UI
thread, while core.folder_scanner remains independent from Qt.
"""

from __future__ import annotations

from pathlib import Path
from threading import Event

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.dcc_classifier import ClassificationResult, classify_path
from core.folder_scanner import (
    FolderScanResult,
    ScanProgress,
    format_bytes,
    scan_folder,
)


class FolderScanWorker(QThread):
    """Execute scan_folder in a worker thread and forward progress by signals."""

    progress_updated = Signal(object)
    scan_completed = Signal(object)
    scan_failed = Signal(str)

    def __init__(self, root_path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._root_path = root_path
        self._cancel_event = Event()

    def cancel(self) -> None:
        """Request cooperative cancellation of the current scan."""
        self._cancel_event.set()

    def run(self) -> None:
        try:
            result = scan_folder(
                self._root_path,
                progress_callback=self.progress_updated.emit,
                cancel_event=self._cancel_event,
                progress_interval=100,
            )
        except Exception as exc:
            self.scan_failed.emit(str(exc))
            return

        self.scan_completed.emit(result)


class FolderAnalyzerDialog(QDialog):
    """Choose a directory and display its largest child folders and files."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("フォルダ容量分析")
        self.resize(900, 650)
        self.setMinimumSize(720, 520)

        self._worker: FolderScanWorker | None = None
        self._close_requested = False

        self._build_ui()
        self._apply_style()

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(22, 20, 22, 18)
        root_layout.setSpacing(12)

        title = QLabel("フォルダ容量分析")
        title.setObjectName("dialogTitle")
        description = QLabel(
            "指定したフォルダを読み取り専用で調査し、容量の大きい項目と"
            "DCCデータの分類候補を表示します。"
        )
        description.setObjectName("mutedText")
        description.setWordWrap(True)
        root_layout.addWidget(title)
        root_layout.addWidget(description)

        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        self.folder_path_edit = QLineEdit()
        self.folder_path_edit.setPlaceholderText("調査するフォルダを選択、またはパスを入力")
        self.folder_path_edit.setClearButtonEnabled(True)

        self.browse_button = QPushButton("参照...")
        self.browse_button.clicked.connect(self.choose_folder)
        folder_row.addWidget(self.folder_path_edit, 1)
        folder_row.addWidget(self.browse_button)
        root_layout.addLayout(folder_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.start_button = QPushButton("調査開始")
        self.start_button.setObjectName("primaryButton")
        self.start_button.clicked.connect(self.start_scan)

        self.cancel_button = QPushButton("キャンセル")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_scan)

        self.close_button = QPushButton("閉じる")
        self.close_button.clicked.connect(self.close)

        action_row.addWidget(self.start_button)
        action_row.addWidget(self.cancel_button)
        action_row.addStretch(1)
        action_row.addWidget(self.close_button)
        root_layout.addLayout(action_row)

        self.status_label = QLabel("調査するフォルダを選択してください。")
        self.status_label.setObjectName("statusLabel")
        root_layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("scanProgress")
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(9)
        root_layout.addWidget(self.progress_bar)

        self.summary_label = QLabel("調査結果はここに表示されます。")
        self.summary_label.setObjectName("summaryLabel")
        self.summary_label.setWordWrap(True)
        root_layout.addWidget(self.summary_label)

        self.results_tabs = QTabWidget()
        self.directory_table = self._create_table(
            ("フォルダ", "容量", "分類", "対象ソフト")
        )
        self.file_table = self._create_table(
            ("ファイル", "容量", "分類", "対象ソフト")
        )
        self.results_tabs.addTab(self.directory_table, "直下のフォルダ")
        self.results_tabs.addTab(self.file_table, "大きいファイル TOP 20")
        root_layout.addWidget(self.results_tabs, 1)

        footer = QLabel(
            "分類は名前・パスに基づく候補です。削除して安全という意味ではありません。"
            "この機能はファイルの削除・移動・変更を行いません。"
        )
        footer.setObjectName("footerText")
        footer.setWordWrap(True)
        root_layout.addWidget(footer)

    def _create_table(self, headers: tuple[str, ...]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(list(headers))
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)

        # The path/name column gets the remaining width. Metadata columns
        # stay compact so the table remains readable.
        table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        for column in range(1, len(headers)):
            table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )

        table.setSortingEnabled(False)
        return table

    def _apply_style(self) -> None:
        self.setStyleSheet(
            "QDialog { background: #F4F6FA; color: #202938; }"
            "QLabel#dialogTitle { color: #172033; font-size: 21px; font-weight: 700; }"
            "QLabel#mutedText { color: #687386; font-size: 12px; }"
            "QLabel#statusLabel { color: #46546A; font-size: 13px; }"
            "QLabel#summaryLabel { color: #202938; font-size: 13px; font-weight: 600; }"
            "QLabel#footerText { color: #738096; font-size: 11px; }"
            "QLineEdit { background: white; border: 1px solid #D5DEEA; border-radius: 7px; padding: 9px; }"
            "QPushButton { background: #E7EDF6; color: #315B9B; border: 1px solid #D5DEEA; border-radius: 7px; padding: 9px 15px; font-weight: 600; }"
            "QPushButton:hover { background: #DCE6F3; }"
            "QPushButton:disabled { color: #8994A5; background: #EDF0F5; }"
            "QPushButton#primaryButton { background: #315B9B; color: white; border: none; }"
            "QPushButton#primaryButton:hover { background: #274B82; }"
            "QProgressBar#scanProgress { background: #E1E7F0; border: none; border-radius: 4px; }"
            "QProgressBar#scanProgress::chunk { background: #399B78; border-radius: 4px; }"
            "QTabWidget::pane { background: white; border: 1px solid #E1E6EE; border-radius: 7px; }"
            "QTabBar::tab { background: #E7EDF6; color: #46546A; padding: 8px 15px; margin-right: 4px; border-top-left-radius: 6px; border-top-right-radius: 6px; }"
            "QTabBar::tab:selected { background: white; color: #315B9B; font-weight: 600; }"
            "QTableWidget { background: white; alternate-background-color: #F7F9FC; border: none; gridline-color: #E8ECF2; }"
            "QHeaderView::section { background: #F0F3F8; color: #46546A; border: none; padding: 7px; font-weight: 600; }"
        )

    def choose_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "調査するフォルダを選択",
            self.folder_path_edit.text().strip(),
        )
        if selected:
            self.folder_path_edit.setText(selected)

    def start_scan(self) -> None:
        root_path = self.folder_path_edit.text().strip()
        if not root_path:
            QMessageBox.information(self, "フォルダ未選択", "調査するフォルダを選択してください。")
            return

        self._clear_results()
        self.start_button.setEnabled(False)
        self.browse_button.setEnabled(False)
        self.folder_path_edit.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate: total file count is unknown.
        self.status_label.setText("フォルダを調査しています...")
        self.summary_label.setText("ファイルとフォルダの情報を収集中です。")

        worker = FolderScanWorker(root_path, self)
        worker.progress_updated.connect(self._on_progress_updated)
        worker.scan_completed.connect(self._on_scan_completed)
        worker.scan_failed.connect(self._on_scan_failed)
        worker.finished.connect(self._on_worker_finished)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    def cancel_scan(self) -> None:
        if self._worker is None or not self._worker.isRunning():
            return
        self.cancel_button.setEnabled(False)
        self.status_label.setText("調査を停止しています...")
        self._worker.cancel()

    def _on_progress_updated(self, progress: ScanProgress) -> None:
        self.status_label.setText(
            f"調査中：ファイル {progress.files_scanned:,} 件 / "
            f"フォルダ {progress.directories_scanned:,} 件"
        )
        self.summary_label.setText(
            f"現在確認できた容量：{format_bytes(progress.total_bytes)}"
        )

    def _on_scan_completed(self, result: FolderScanResult) -> None:
        self._populate_directory_table(result)
        self._populate_file_table(result)

        summary = (
            f"合計容量：{format_bytes(result.total_bytes)}　 |　 "
            f"ファイル：{result.files_scanned:,} 件　 |　 "
            f"フォルダ：{result.directories_scanned:,} 件　 |　 "
            f"スキップ：{result.skipped_entries:,} 件"
        )
        self.summary_label.setText(summary)

        if result.cancelled:
            self.status_label.setText("調査をキャンセルしました。表示内容はキャンセル時点までの結果です。")
        elif result.skipped_entries:
            self.status_label.setText("調査が完了しました。一部の項目はスキップされています。")
        else:
            self.status_label.setText("調査が完了しました。")

        if result.sample_errors:
            self.summary_label.setToolTip("\n".join(result.sample_errors))

    @staticmethod
    def _classification_tooltip(result: ClassificationResult) -> str:
        """Explain the matched rule without implying that deletion is safe."""
        return (
            f"判定理由：{result.reason}\n"
            f"ルール：{result.rule_id}\n"
            f"一致スコア：{result.match_score}（確率ではありません）\n"
            f"注意：{result.safety_note}"
        )

    def _populate_directory_table(self, result: FolderScanResult) -> None:
        self.directory_table.setRowCount(len(result.largest_directories))
        for row, entry in enumerate(result.largest_directories):
            classification = classify_path(entry.path)
            tooltip = self._classification_tooltip(classification)

            name = Path(entry.path).name or entry.path
            name_item = QTableWidgetItem(name)
            name_item.setToolTip(f"{entry.path}\n\n{tooltip}")

            size_item = QTableWidgetItem(format_bytes(entry.size_bytes))
            size_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )

            category_item = QTableWidgetItem(classification.category.value)
            category_item.setToolTip(tooltip)
            application_item = QTableWidgetItem(classification.application)
            application_item.setToolTip(tooltip)

            self.directory_table.setItem(row, 0, name_item)
            self.directory_table.setItem(row, 1, size_item)
            self.directory_table.setItem(row, 2, category_item)
            self.directory_table.setItem(row, 3, application_item)

    def _populate_file_table(self, result: FolderScanResult) -> None:
        root = Path(result.root_path)
        self.file_table.setRowCount(len(result.largest_files))
        for row, entry in enumerate(result.largest_files):
            classification = classify_path(entry.path)
            tooltip = self._classification_tooltip(classification)

            try:
                display_path = str(Path(entry.path).relative_to(root))
            except ValueError:
                display_path = entry.path

            path_item = QTableWidgetItem(display_path)
            path_item.setToolTip(f"{entry.path}\n\n{tooltip}")

            size_item = QTableWidgetItem(format_bytes(entry.size_bytes))
            size_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )

            category_item = QTableWidgetItem(classification.category.value)
            category_item.setToolTip(tooltip)
            application_item = QTableWidgetItem(classification.application)
            application_item.setToolTip(tooltip)

            self.file_table.setItem(row, 0, path_item)
            self.file_table.setItem(row, 1, size_item)
            self.file_table.setItem(row, 2, category_item)
            self.file_table.setItem(row, 3, application_item)

    def _on_scan_failed(self, message: str) -> None:
        self.status_label.setText("調査に失敗しました。フォルダの場所やアクセス権限を確認してください。")
        self.summary_label.setText(message)

    def _on_worker_finished(self) -> None:
        self._worker = None
        self.start_button.setEnabled(True)
        self.browse_button.setEnabled(True)
        self.folder_path_edit.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)

        if self._close_requested:
            self.accept()

    def _clear_results(self) -> None:
        self.directory_table.setRowCount(0)
        self.file_table.setRowCount(0)
        self.summary_label.setToolTip("")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if self._worker is not None and self._worker.isRunning():
            self._close_requested = True
            self.cancel_scan()
            event.ignore()
            return
        super().closeEvent(event)
