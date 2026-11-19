"""Main window for DCC Storage Manager - Step 02.

This UI only displays drive capacity information. It does not delete, move,
or modify any user files.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.storage_scanner import DriveInfo, scan_drives
from ui.folder_analyzer_dialog import FolderAnalyzerDialog


class DriveScanWorker(QThread):
    """Run the drive scan outside the UI thread to keep the window responsive."""

    scan_completed = Signal(list)
    scan_failed = Signal(str)

    def run(self) -> None:
        try:
            drives = scan_drives()
        except Exception as exc:  # Surface unexpected scan errors in the UI.
            self.scan_failed.emit(str(exc))
            return

        self.scan_completed.emit(drives)


class DriveCard(QFrame):
    """A visual summary of one mounted drive."""

    def __init__(self, drive: DriveInfo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("driveCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        card_layout = QVBoxLayout(self)
        card_layout.setContentsMargins(18, 15, 18, 15)
        card_layout.setSpacing(10)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)

        drive_letter = QLabel(drive.drive_letter)
        drive_letter.setObjectName("driveLetter")
        drive_letter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drive_letter.setFixedSize(54, 42)

        volume_name = drive.volume_label or "ボリューム名なし"
        name_label = QLabel(volume_name)
        name_label.setObjectName("driveName")
        name_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        details_text = f"{drive.drive_type_label}  |  {drive.filesystem or 'ファイルシステム不明'}"
        details_label = QLabel(details_text)
        details_label.setObjectName("mutedText")
        details_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        name_layout = QVBoxLayout()
        name_layout.setSpacing(3)
        name_layout.addWidget(name_label)
        name_layout.addWidget(details_label)

        usage_label = QLabel(f"{drive.usage_percent:.1f}% 使用")
        usage_label.setObjectName("usageLabel")
        usage_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        header_layout.addWidget(drive_letter)
        header_layout.addLayout(name_layout, 1)
        header_layout.addWidget(usage_label)
        card_layout.addLayout(header_layout)

        progress = QProgressBar()
        progress.setObjectName("capacityBar")
        progress.setRange(0, 100)
        progress.setValue(max(0, min(100, round(drive.usage_percent))))
        progress.setTextVisible(False)
        progress.setFixedHeight(12)

        if drive.usage_percent >= 90:
            bar_color = "#D95F59"
        elif drive.usage_percent >= 75:
            bar_color = "#D99A35"
        else:
            bar_color = "#399B78"

        progress.setStyleSheet(
            "QProgressBar {"
            " background-color: #E8ECF2; border: none; border-radius: 6px;"
            "}"
            f"QProgressBar::chunk {{ background-color: {bar_color}; border-radius: 6px; }}"
        )
        card_layout.addWidget(progress)

        capacity_layout = QHBoxLayout()
        used_text = f"使用中 {drive.used_gib:,.2f} GiB / {drive.total_gib:,.2f} GiB"
        free_text = f"空き {drive.free_gib:,.2f} GiB"

        used_label = QLabel(used_text)
        used_label.setObjectName("mutedText")
        used_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        free_label = QLabel(free_text)
        free_label.setObjectName("freeSpaceLabel")
        free_label.setAlignment(Qt.AlignmentFlag.AlignRight)

        capacity_layout.addWidget(used_label)
        capacity_layout.addStretch(1)
        capacity_layout.addWidget(free_label)
        card_layout.addLayout(capacity_layout)


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("DCC Storage Manager")
        self.resize(850, 700)
        self.setMinimumSize(640, 480)

        self._scan_worker: DriveScanWorker | None = None
        self._build_ui()
        self._apply_style()
        self.start_scan()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(26, 22, 26, 20)
        root_layout.setSpacing(15)

        header_layout = QHBoxLayout()
        title_layout = QVBoxLayout()
        title_layout.setSpacing(4)

        title = QLabel("DCC Storage Manager")
        title.setObjectName("appTitle")
        subtitle = QLabel("PCと外付けストレージの使用状況を確認します")
        subtitle.setObjectName("mutedText")

        title_layout.addWidget(title)
        title_layout.addWidget(subtitle)

        self.folder_analyzer_button = QPushButton("フォルダ分析")
        self.folder_analyzer_button.setObjectName("secondaryButton")
        self.folder_analyzer_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.folder_analyzer_button.clicked.connect(self.open_folder_analyzer)

        self.refresh_button = QPushButton("再スキャン")
        self.refresh_button.setObjectName("refreshButton")
        self.refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_button.clicked.connect(self.start_scan)

        header_layout.addLayout(title_layout, 1)
        header_layout.addWidget(self.folder_analyzer_button, 0, Qt.AlignmentFlag.AlignVCenter)
        header_layout.addWidget(self.refresh_button, 0, Qt.AlignmentFlag.AlignVCenter)
        root_layout.addLayout(header_layout)

        self.status_label = QLabel("ドライブを調査しています...")
        self.status_label.setObjectName("statusLabel")
        root_layout.addWidget(self.status_label)

        self.summary_label = QLabel("検出結果を待っています")
        self.summary_label.setObjectName("summaryLabel")
        root_layout.addWidget(self.summary_label)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setObjectName("driveScrollArea")

        self.drive_list_widget = QWidget()
        self.drive_list_layout = QVBoxLayout(self.drive_list_widget)
        self.drive_list_layout.setContentsMargins(2, 2, 8, 2)
        self.drive_list_layout.setSpacing(12)
        self.drive_list_layout.addStretch(1)

        self.scroll_area.setWidget(self.drive_list_widget)
        root_layout.addWidget(self.scroll_area, 1)

        footer = QLabel(
            "この画面は容量情報を表示するだけです。ファイルの削除・移動・変更は行いません。"
        )
        footer.setObjectName("footerText")
        footer.setWordWrap(True)
        root_layout.addWidget(footer)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            "QMainWindow, QWidget { background-color: #F4F6FA; color: #202938; }"
            "QLabel#appTitle { font-size: 23px; font-weight: 700; color: #172033; }"
            "QLabel#mutedText { color: #687386; font-size: 12px; }"
            "QLabel#statusLabel { color: #46546A; font-size: 13px; }"
            "QLabel#summaryLabel { color: #202938; font-size: 14px; font-weight: 600; }"
            "QLabel#footerText { color: #738096; font-size: 11px; padding-top: 4px; }"
            "QFrame#driveCard { background: #FFFFFF; border: 1px solid #E1E6EE; border-radius: 12px; }"
            "QLabel#driveLetter { background: #EAF0FA; color: #315B9B; border-radius: 9px; font-size: 16px; font-weight: 700; }"
            "QLabel#driveName { color: #202938; font-size: 15px; font-weight: 600; }"
            "QLabel#usageLabel { color: #46546A; font-size: 13px; font-weight: 600; }"
            "QLabel#freeSpaceLabel { color: #34445C; font-size: 12px; font-weight: 600; }"
            "QPushButton#secondaryButton { background: #E7EDF6; color: #315B9B; border: 1px solid #D5DEEA; border-radius: 8px; padding: 10px 18px; font-weight: 600; }"
            "QPushButton#secondaryButton:hover { background: #DCE6F3; }"
            "QPushButton#refreshButton { background: #315B9B; color: white; border: none; border-radius: 8px; padding: 10px 18px; font-weight: 600; }"
            "QPushButton#refreshButton:hover { background: #274B82; }"
            "QPushButton#refreshButton:disabled { background: #AAB6C8; color: #F5F7FA; }"
            "QScrollArea#driveScrollArea { background: transparent; }"
        )

    def open_folder_analyzer(self) -> None:
        """Open the folder-size analyzer without mixing it into drive scanning."""
        dialog = FolderAnalyzerDialog(self)
        dialog.exec()

    def start_scan(self) -> None:
        if self._scan_worker is not None and self._scan_worker.isRunning():
            return

        self.refresh_button.setEnabled(False)
        self.refresh_button.setText("調査中...")
        self.status_label.setText("接続中のドライブを調査しています...")

        worker = DriveScanWorker(self)
        worker.scan_completed.connect(self._on_scan_completed)
        worker.scan_failed.connect(self._on_scan_failed)
        worker.finished.connect(self._on_worker_finished)
        worker.finished.connect(worker.deleteLater)
        self._scan_worker = worker
        worker.start()

    def _clear_drive_cards(self) -> None:
        while self.drive_list_layout.count():
            item = self.drive_list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _on_scan_completed(self, drives: list[DriveInfo]) -> None:
        self._clear_drive_cards()

        if not drives:
            empty_label = QLabel("利用可能なドライブが見つかりませんでした。")
            empty_label.setObjectName("mutedText")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_label.setMinimumHeight(120)
            self.drive_list_layout.addWidget(empty_label)
            self.drive_list_layout.addStretch(1)
            self.summary_label.setText("検出ドライブ数：0")
            self.status_label.setText("調査が完了しました。")
            return

        for drive in drives:
            self.drive_list_layout.addWidget(DriveCard(drive, self.drive_list_widget))

        self.drive_list_layout.addStretch(1)
        self.summary_label.setText(f"検出ドライブ数：{len(drives)} 台")
        self.status_label.setText("調査が完了しました。")

    def _on_scan_failed(self, message: str) -> None:
        self.status_label.setText(f"調査に失敗しました：{message}")
        self.summary_label.setText("ドライブ情報を取得できませんでした")

    def _on_worker_finished(self) -> None:
        self.refresh_button.setEnabled(True)
        self.refresh_button.setText("再スキャン")
        self._scan_worker = None
