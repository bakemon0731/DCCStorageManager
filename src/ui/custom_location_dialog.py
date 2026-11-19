"""Dialog for managing user-defined DCC cache/backup locations."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QAbstractItemView,
    QHeaderView,
)

from core.settings_store import (
    DuplicateLocationError,
    SettingsError,
    SettingsStore,
    CustomLocation,
)


_APPLICATIONS = ("Maya", "After Effects", "ZBrush")
_CATEGORY_LABELS = {
    "cache": "キャッシュ",
    "backup": "バックアップ",
}


class CustomLocationDialog(QDialog):
    """Add and remove persistent custom classification locations."""

    def __init__(self, store: SettingsStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self.setWindowTitle("カスタム保存先の管理")
        self.resize(760, 460)
        self.setMinimumSize(620, 400)

        self._build_ui()
        self._apply_style()
        self._refresh_locations()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        title = QLabel("カスタム保存先の管理")
        title.setObjectName("dialogTitle")
        description = QLabel(
            "ソフト側で保存先を変更している場合、実際のフォルダを登録してください。"
            "登録した場所とその配下を指定した分類として扱います。"
            "登録パスが入れ子の場合は、より深い登録が優先されます。"
        )
        description.setWordWrap(True)
        description.setObjectName("mutedText")
        root.addWidget(title)
        root.addWidget(description)

        form = QFormLayout()
        self.application_combo = QComboBox()
        self.application_combo.addItems(list(_APPLICATIONS))

        self.category_combo = QComboBox()
        self.category_combo.addItem("キャッシュ", "cache")
        self.category_combo.addItem("バックアップ", "backup")

        path_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText(r"例：E:\ScratchDisk01")
        self.browse_button = QPushButton("参照...")
        self.browse_button.clicked.connect(self._choose_folder)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(self.browse_button)

        form.addRow("対象ソフト", self.application_combo)
        form.addRow("データの種類", self.category_combo)
        form.addRow("保存先", path_row)
        root.addLayout(form)

        add_row = QHBoxLayout()
        self.add_button = QPushButton("保存先を登録")
        self.add_button.setObjectName("primaryButton")
        self.add_button.clicked.connect(self._add_location)
        self.remove_button = QPushButton("選択した登録を削除")
        self.remove_button.clicked.connect(self._remove_selected)
        add_row.addWidget(self.add_button)
        add_row.addWidget(self.remove_button)
        add_row.addStretch(1)
        root.addLayout(add_row)

        self.location_table = QTableWidget(0, 4)
        self.location_table.setHorizontalHeaderLabels(
            ("対象ソフト", "種類", "登録パス", "登録ID")
        )
        self.location_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.location_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.location_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.location_table.setAlternatingRowColors(True)
        self.location_table.verticalHeader().setVisible(False)
        self.location_table.setColumnHidden(3, True)
        self.location_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.location_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.location_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        root.addWidget(self.location_table, 1)

        note = QLabel(
            "注意：登録は分類ルールを追加するだけです。保存先の中身を削除・移動・変更しません。"
            "登録した外付けドライブが未接続でも設定は保持されます。"
        )
        note.setObjectName("footerText")
        note.setWordWrap(True)
        root.addWidget(note)

        settings_path_label = QLabel(f"設定ファイル：{self._store.path}")
        settings_path_label.setObjectName("footerText")
        settings_path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        settings_path_label.setWordWrap(True)
        root.addWidget(settings_path_label)

        footer = QHBoxLayout()
        footer.addStretch(1)
        close_button = QPushButton("閉じる")
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        root.addLayout(footer)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            "QDialog { background: #F4F6FA; color: #202938; }"
            "QLabel#dialogTitle { color: #172033; font-size: 20px; font-weight: 700; }"
            "QLabel#mutedText, QLabel#footerText { color: #687386; font-size: 12px; }"
            "QLineEdit, QComboBox { background: white; border: 1px solid #D5DEEA; border-radius: 7px; padding: 8px; }"
            "QPushButton { background: #E7EDF6; color: #315B9B; border: 1px solid #D5DEEA; border-radius: 7px; padding: 8px 13px; font-weight: 600; }"
            "QPushButton:hover { background: #DCE6F3; }"
            "QPushButton#primaryButton { background: #315B9B; color: white; border: none; }"
            "QTableWidget { background: white; alternate-background-color: #F7F9FC; border: none; gridline-color: #E8ECF2; }"
            "QHeaderView::section { background: #F0F3F8; color: #46546A; border: none; padding: 7px; font-weight: 600; }"
        )

    def _choose_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "カスタム保存先を選択",
            self.path_edit.text().strip(),
        )
        if selected:
            self.path_edit.setText(selected)

    def _add_location(self) -> None:
        path = self.path_edit.text().strip()
        if not path:
            QMessageBox.information(self, "保存先未入力", "登録するフォルダを指定してください。")
            return

        try:
            self._store.add_custom_location(
                application=self.application_combo.currentText(),
                category=str(self.category_combo.currentData()),
                path=path,
            )
        except DuplicateLocationError as exc:
            QMessageBox.information(self, "登録済み", str(exc))
            return
        except (SettingsError, ValueError) as exc:
            QMessageBox.warning(self, "登録できません", str(exc))
            return

        self.path_edit.clear()
        self._refresh_locations()
        QMessageBox.information(self, "登録完了", "カスタム保存先を登録しました。")

    def _remove_selected(self) -> None:
        row = self.location_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "未選択", "削除する登録を選択してください。")
            return

        id_item = self.location_table.item(row, 3)
        location_id = id_item.text() if id_item is not None else ""
        answer = QMessageBox.question(
            self,
            "登録の削除",
            "選択したカスタム分類ルールを削除しますか？\n"
            "実際のフォルダやファイルは削除されません。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            removed = self._store.remove_custom_location(location_id)
        except SettingsError as exc:
            QMessageBox.warning(self, "削除できません", str(exc))
            return

        if removed:
            self._refresh_locations()

    def _refresh_locations(self) -> None:
        try:
            settings = self._store.load()
        except SettingsError as exc:
            QMessageBox.critical(self, "設定を読み込めません", str(exc))
            self.add_button.setEnabled(False)
            self.remove_button.setEnabled(False)
            return

        locations: tuple[CustomLocation, ...] = settings.custom_locations
        self.location_table.setRowCount(len(locations))
        for row, location in enumerate(locations):
            values = (
                location.application,
                _CATEGORY_LABELS[location.category],
                location.path,
                location.id,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.location_table.setItem(row, column, item)
