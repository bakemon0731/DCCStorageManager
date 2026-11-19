"""UI for reviewing and registering DCC location discovery results."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from core.dcc_discovery import DccLocationDiscovery, DiscoveryCandidate
from core.settings_store import (
    DuplicateLocationError,
    SettingsError,
    SettingsStore,
)


_CATEGORY_LABELS = {
    "cache": "キャッシュ候補",
    "backup": "バックアップ候補",
}


class DccDiscoveryDialog(QDialog):
    """Show detected paths and let the user explicitly register a candidate."""

    def __init__(self, store: SettingsStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._candidates: tuple[DiscoveryCandidate, ...] = ()
        self.setWindowTitle("DCC保存先の自動検出")
        self.resize(980, 560)
        self.setMinimumSize(760, 440)
        self._build_ui()
        self._apply_style()
        self.refresh_results()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        title = QLabel("DCC保存先の自動検出")
        title.setObjectName("dialogTitle")
        description = QLabel(
            "各ソフトの設定ファイルや公式APIから確認できる保存先を調査します。"
            "検出結果は自動登録されません。内容を確認してから登録してください。"
        )
        description.setWordWrap(True)
        description.setObjectName("mutedText")
        root.addWidget(title)
        root.addWidget(description)

        self.status_label = QLabel("検出を準備しています...")
        self.status_label.setObjectName("statusLabel")
        root.addWidget(self.status_label)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ("ソフト", "データ種類", "検出した保存先", "状態", "情報源")
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        for column in (0, 1, 3, 4):
            self.table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        root.addWidget(self.table, 1)

        note = QLabel(
            "注意：検出は読み取り専用です。設定ファイルやDCCデータは変更しません。"
            "After Effectsは設定ファイルの非公開キーを解析せず、アプリ内での確認を案内します。"
            "登録した場所は分類に使われるだけで、削除・移動は行いません。"
        )
        note.setObjectName("footerText")
        note.setWordWrap(True)
        root.addWidget(note)

        actions = QHBoxLayout()
        self.refresh_button = QPushButton("再検出")
        self.refresh_button.clicked.connect(self.refresh_results)
        self.register_button = QPushButton("選択した保存先を登録")
        self.register_button.setObjectName("primaryButton")
        self.register_button.clicked.connect(self.register_selected)
        close_button = QPushButton("閉じる")
        close_button.clicked.connect(self.accept)
        actions.addWidget(self.refresh_button)
        actions.addWidget(self.register_button)
        actions.addStretch(1)
        actions.addWidget(close_button)
        root.addLayout(actions)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            "QDialog { background: #F4F6FA; color: #202938; }"
            "QLabel#dialogTitle { color: #172033; font-size: 20px; font-weight: 700; }"
            "QLabel#mutedText, QLabel#footerText { color: #687386; font-size: 12px; }"
            "QLabel#statusLabel { color: #46546A; font-size: 13px; font-weight: 600; }"
            "QPushButton { background: #E7EDF6; color: #315B9B; border: 1px solid #D5DEEA; border-radius: 7px; padding: 8px 13px; font-weight: 600; }"
            "QPushButton:hover { background: #DCE6F3; }"
            "QPushButton#primaryButton { background: #315B9B; color: white; border: none; }"
            "QPushButton#primaryButton:hover { background: #274B82; }"
            "QTableWidget { background: white; alternate-background-color: #F7F9FC; border: none; gridline-color: #E8ECF2; }"
            "QHeaderView::section { background: #F0F3F8; color: #46546A; border: none; padding: 7px; font-weight: 600; }"
        )

    def refresh_results(self) -> None:
        self._candidates = DccLocationDiscovery().discover()
        self.table.setRowCount(len(self._candidates))
        registerable_count = 0

        for row, candidate in enumerate(self._candidates):
            category_text = _CATEGORY_LABELS.get(candidate.category, "要確認")
            path_text = candidate.path or "アプリ内で確認してください"
            source_text = candidate.source
            values = (
                candidate.application,
                category_text,
                path_text,
                candidate.status,
                source_text,
            )
            tooltip = (
                f"情報源：{candidate.source}\n"
                f"状態：{candidate.status}\n"
                f"説明：{candidate.explanation}"
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(tooltip)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, row)
                self.table.setItem(row, column, item)
            if candidate.registerable and candidate.category and candidate.path:
                registerable_count += 1

        self.status_label.setText(
            f"検出情報：{len(self._candidates)} 件　|　登録可能な保存先：{registerable_count} 件"
        )
        self.register_button.setEnabled(registerable_count > 0)

    def register_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._candidates):
            QMessageBox.information(self, "未選択", "登録する保存先を選択してください。")
            return

        candidate = self._candidates[row]
        if not candidate.registerable or not candidate.category or not candidate.path:
            QMessageBox.information(
                self,
                "自動登録できません",
                "この項目は保存先パスを確定できていません。説明欄を確認し、ソフト側で保存先を確認してください。",
            )
            return

        if candidate.path_exists is False:
            answer = QMessageBox.question(
                self,
                "保存先にアクセスできません",
                "登録されたパスは現在存在しないか、ドライブが未接続です。"
                "外付けドライブの設定を保持する目的で登録しますか？\n\n"
                f"{candidate.path}",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        try:
            self._store.add_custom_location(
                application=candidate.application,
                category=candidate.category,
                path=candidate.path,
            )
        except DuplicateLocationError:
            QMessageBox.information(
                self,
                "登録済み",
                "同じ保存先はすでにカスタムルールに登録されています。",
            )
            return
        except (SettingsError, ValueError) as exc:
            QMessageBox.warning(self, "登録できません", str(exc))
            return

        QMessageBox.information(
            self,
            "登録完了",
            "検出した保存先をカスタムルールに登録しました。\n"
            "次回のフォルダ分析から分類に使用されます。",
        )
        self.accept()
