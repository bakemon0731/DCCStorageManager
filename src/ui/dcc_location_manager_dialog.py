"""Unified UI for discovered and manually registered DCC locations."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.dcc_location_manager import DccLocationManager, ManagedCandidate
from core.settings_store import DuplicateLocationError, SettingsError


_CATEGORY_LABELS = {"cache": "キャッシュ", "backup": "バックアップ"}
_ORIGIN_LABELS = {"manual": "手動登録", "discovered": "自動検出"}


class DccLocationManagerDialog(QDialog):
    """Manage detected candidates and saved rules from one place.

    Detection is read-only. A candidate is persisted only after the user
    explicitly selects it and confirms any offline-path warning.
    """

    def __init__(self, manager: DccLocationManager | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._manager = manager or DccLocationManager()
        self._snapshot = None
        self._managed_candidates: tuple[ManagedCandidate, ...] = ()
        self.setWindowTitle("DCC保存先の管理")
        self.resize(1020, 650)
        self.setMinimumSize(800, 540)
        self._build_ui()
        self._apply_style()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        title = QLabel("DCC保存先の管理")
        title.setObjectName("dialogTitle")
        description = QLabel(
            "自動検出した保存先と、手動登録した保存先をまとめて管理します。"
            "検出しただけでは登録されず、ファイルの削除・移動・変更も行いません。"
        )
        description.setWordWrap(True)
        description.setObjectName("mutedText")
        root.addWidget(title)
        root.addWidget(description)

        self.status_label = QLabel("保存先情報を読み込んでいます...")
        self.status_label.setObjectName("statusLabel")
        root.addWidget(self.status_label)

        self.tabs = QTabWidget()
        self.discovery_tab = QWidget()
        self.registered_tab = QWidget()
        self.tabs.addTab(self.discovery_tab, "自動検出")
        self.tabs.addTab(self.registered_tab, "登録済みルール・手動登録")
        root.addWidget(self.tabs, 1)

        self._build_discovery_tab()
        self._build_registered_tab()

        footer = QHBoxLayout()
        footer.addStretch(1)
        close_button = QPushButton("閉じる")
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        root.addLayout(footer)

    def _build_discovery_tab(self) -> None:
        layout = QVBoxLayout(self.discovery_tab)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(10)

        note = QLabel(
            "アプリケーションの公式API・設定ファイルから確認できた候補です。"
            "「登録可能」と表示されたものだけ登録できます。After Effectsなど、"
            "保存先を確定できない項目は手動登録してください。"
        )
        note.setWordWrap(True)
        note.setObjectName("mutedText")
        layout.addWidget(note)

        self.discovery_table = self._create_table(
            ("ソフト", "種類", "検出した保存先", "検出状態", "登録状態", "情報源")
        )
        self.discovery_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.discovery_table, 1)

        actions = QHBoxLayout()
        self.refresh_button = QPushButton("再検出")
        self.refresh_button.clicked.connect(self.refresh)
        self.register_discovered_button = QPushButton("選択した候補を登録")
        self.register_discovered_button.setObjectName("primaryButton")
        self.register_discovered_button.clicked.connect(self.register_selected_discovery)
        actions.addWidget(self.refresh_button)
        actions.addWidget(self.register_discovered_button)
        actions.addStretch(1)
        layout.addLayout(actions)

    def _build_registered_tab(self) -> None:
        layout = QVBoxLayout(self.registered_tab)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(10)

        form_title = QLabel("保存先を手動登録")
        form_title.setObjectName("sectionTitle")
        layout.addWidget(form_title)

        form = QFormLayout()
        self.application_combo = QComboBox()
        self.application_combo.addItems(("Maya", "After Effects", "ZBrush"))

        self.category_combo = QComboBox()
        self.category_combo.addItem("キャッシュ", "cache")
        self.category_combo.addItem("バックアップ", "backup")

        path_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText(r"例：E:\ScratchDisk01")
        self.browse_button = QPushButton("参照...")
        self.browse_button.clicked.connect(self.choose_manual_path)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(self.browse_button)

        form.addRow("対象ソフト", self.application_combo)
        form.addRow("データの種類", self.category_combo)
        form.addRow("保存先", path_row)
        layout.addLayout(form)

        add_row = QHBoxLayout()
        self.add_manual_button = QPushButton("手動登録")
        self.add_manual_button.setObjectName("primaryButton")
        self.add_manual_button.clicked.connect(self.register_manual)
        self.remove_button = QPushButton("選択したルールを削除")
        self.remove_button.clicked.connect(self.remove_selected)
        add_row.addWidget(self.add_manual_button)
        add_row.addWidget(self.remove_button)
        add_row.addStretch(1)
        layout.addLayout(add_row)

        self.registered_table = self._create_table(
            ("ソフト", "種類", "登録パス", "登録元", "接続状態", "登録ID")
        )
        self.registered_table.setColumnHidden(5, True)
        self.registered_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.registered_table, 1)

        self.settings_path_label = QLabel(f"設定ファイル：{self._manager.store.path}")
        self.settings_path_label.setObjectName("footerText")
        self.settings_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.settings_path_label.setWordWrap(True)
        layout.addWidget(self.settings_path_label)

    @staticmethod
    def _create_table(headers: tuple[str, ...]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(list(headers))
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        for column in range(len(headers)):
            if column not in {2}:
                table.horizontalHeader().setSectionResizeMode(
                    column, QHeaderView.ResizeMode.ResizeToContents
                )
        return table

    def _apply_style(self) -> None:
        self.setStyleSheet(
            "QDialog { background: #F4F6FA; color: #202938; }"
            "QLabel#dialogTitle { color: #172033; font-size: 20px; font-weight: 700; }"
            "QLabel#sectionTitle { color: #202938; font-size: 14px; font-weight: 700; }"
            "QLabel#mutedText, QLabel#footerText { color: #687386; font-size: 12px; }"
            "QLabel#statusLabel { color: #46546A; font-size: 13px; font-weight: 600; }"
            "QLineEdit, QComboBox { background: white; border: 1px solid #D5DEEA; border-radius: 7px; padding: 8px; }"
            "QPushButton { background: #E7EDF6; color: #315B9B; border: 1px solid #D5DEEA; border-radius: 7px; padding: 8px 13px; font-weight: 600; }"
            "QPushButton:hover { background: #DCE6F3; }"
            "QPushButton:disabled { color: #8994A5; background: #EDF0F5; }"
            "QPushButton#primaryButton { background: #315B9B; color: white; border: none; }"
            "QPushButton#primaryButton:hover { background: #274B82; }"
            "QTabWidget::pane { background: white; border: 1px solid #E1E6EE; border-radius: 7px; }"
            "QTabBar::tab { background: #E7EDF6; color: #46546A; padding: 8px 15px; margin-right: 4px; border-top-left-radius: 6px; border-top-right-radius: 6px; }"
            "QTabBar::tab:selected { background: white; color: #315B9B; font-weight: 600; }"
            "QTableWidget { background: white; alternate-background-color: #F7F9FC; border: none; gridline-color: #E8ECF2; }"
            "QHeaderView::section { background: #F0F3F8; color: #46546A; border: none; padding: 7px; font-weight: 600; }"
        )

    def refresh(self) -> None:
        try:
            self._snapshot = self._manager.get_snapshot()
        except SettingsError as exc:
            self._snapshot = None
            self.status_label.setText("設定ファイルを読み込めません。設定を保護するため編集を停止しました。")
            self.status_label.setToolTip(str(exc))
            self.discovery_table.setRowCount(0)
            self.registered_table.setRowCount(0)
            self.register_discovered_button.setEnabled(False)
            self.add_manual_button.setEnabled(False)
            self.remove_button.setEnabled(False)
            return

        self._managed_candidates = self._snapshot.candidates
        registerable_count = sum(item.can_register for item in self._managed_candidates)
        self.status_label.setText(
            f"自動検出：{len(self._managed_candidates)} 件　|　"
            f"新規登録可能：{registerable_count} 件　|　"
            f"登録済み：{len(self._snapshot.registered_locations)} 件"
        )
        self.status_label.setToolTip("")
        self._populate_discovery_table()
        self._populate_registered_table()
        self.register_discovered_button.setEnabled(registerable_count > 0)
        self.add_manual_button.setEnabled(True)
        self.remove_button.setEnabled(bool(self._snapshot.registered_locations))

    def _populate_discovery_table(self) -> None:
        self.discovery_table.setRowCount(len(self._managed_candidates))
        for row, managed in enumerate(self._managed_candidates):
            candidate = managed.candidate
            values = (
                candidate.application,
                _CATEGORY_LABELS.get(candidate.category, "要確認"),
                candidate.path or "アプリ内で確認してください",
                candidate.status,
                managed.registration_status,
                candidate.source,
            )
            tooltip = (
                f"情報源：{candidate.source}\n"
                f"検出状態：{candidate.status}\n"
                f"説明：{candidate.explanation}"
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(tooltip)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, row)
                self.discovery_table.setItem(row, column, item)

    def _populate_registered_table(self) -> None:
        assert self._snapshot is not None
        locations = self._snapshot.registered_locations
        self.registered_table.setRowCount(len(locations))
        for row, location in enumerate(locations):
            exists = Path(location.path).is_dir()
            values = (
                location.application,
                _CATEGORY_LABELS[location.category],
                location.path,
                _ORIGIN_LABELS.get(location.origin, location.origin),
                "接続済み" if exists else "未接続・未確認",
                location.id,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(
                    f"登録元：{location.source}\n"
                    f"パス：{location.path}\n"
                    "登録解除しても実際のフォルダやファイルは削除されません。"
                )
                self.registered_table.setItem(row, column, item)

    def register_selected_discovery(self) -> None:
        row = self.discovery_table.currentRow()
        if row < 0 or row >= len(self._managed_candidates):
            QMessageBox.information(self, "未選択", "登録する検出結果を選択してください。")
            return

        managed = self._managed_candidates[row]
        if not managed.can_register:
            QMessageBox.information(
                self,
                "登録できません",
                f"この候補は登録できません。現在の状態：{managed.registration_status}",
            )
            return

        candidate = managed.candidate
        if candidate.path_exists is False:
            answer = QMessageBox.question(
                self,
                "保存先にアクセスできません",
                "検出した保存先は現在アクセスできません。外付けドライブなどの"
                "設定を保持する目的で登録しますか？\n\n"
                f"{candidate.path}",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        try:
            self._manager.register_discovered(managed)
        except (DuplicateLocationError, SettingsError, ValueError) as exc:
            QMessageBox.warning(self, "登録できません", str(exc))
            self.refresh()
            return

        QMessageBox.information(self, "登録完了", "自動検出した保存先を登録しました。")
        self.refresh()
        self.tabs.setCurrentWidget(self.registered_tab)

    def choose_manual_path(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "手動登録する保存先を選択",
            self.path_edit.text().strip(),
        )
        if selected:
            self.path_edit.setText(selected)

    def register_manual(self) -> None:
        path = self.path_edit.text().strip()
        if not path:
            QMessageBox.information(self, "保存先未入力", "登録するフォルダを指定してください。")
            return

        try:
            self._manager.register_manual(
                application=self.application_combo.currentText(),
                category=str(self.category_combo.currentData()),
                path=path,
            )
        except (DuplicateLocationError, SettingsError, ValueError) as exc:
            QMessageBox.warning(self, "登録できません", str(exc))
            return

        self.path_edit.clear()
        QMessageBox.information(self, "登録完了", "手動登録した保存先を追加しました。")
        self.refresh()

    def remove_selected(self) -> None:
        row = self.registered_table.currentRow()
        if row < 0 or self._snapshot is None:
            QMessageBox.information(self, "未選択", "解除するルールを選択してください。")
            return

        id_item = self.registered_table.item(row, 5)
        location_id = id_item.text() if id_item is not None else ""
        answer = QMessageBox.question(
            self,
            "登録ルールの解除",
            "選択した分類ルールを解除しますか？\n"
            "実際のフォルダやファイルは削除・変更されません。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            removed = self._manager.remove_registered(location_id)
        except SettingsError as exc:
            QMessageBox.warning(self, "解除できません", str(exc))
            return

        if removed:
            self.refresh()

