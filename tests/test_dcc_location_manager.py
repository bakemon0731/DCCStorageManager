from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(PROJECT_SRC))

from core.dcc_discovery import DiscoveryCandidate  # noqa: E402
from core.dcc_location_manager import DccLocationManager  # noqa: E402
from core.settings_store import DuplicateLocationError, SettingsStore  # noqa: E402


class FakeDiscovery:
    def __init__(self, candidates: tuple[DiscoveryCandidate, ...]) -> None:
        self._candidates = candidates

    def discover(self) -> tuple[DiscoveryCandidate, ...]:
        return self._candidates


class DccLocationManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.settings_path = self.root / "settings.json"
        self.store = SettingsStore(self.settings_path)
        self.discovery_path = self.root / "ZBrush" / "QuickSave"
        self.discovery_path.mkdir(parents=True)
        self.candidate = DiscoveryCandidate(
            application="ZBrush",
            category="backup",
            path=str(self.discovery_path),
            status="設定から検出・フォルダ確認済み",
            source="ZBRUSH_USER_ASSETS_DIR",
            explanation="テスト用の自動検出結果です。",
            registerable=True,
            path_exists=True,
        )
        self.manager = DccLocationManager(
            store=self.store,
            discovery=FakeDiscovery((self.candidate,)),
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_discovery_candidate_is_available_before_registration(self) -> None:
        snapshot = self.manager.get_snapshot()
        self.assertEqual(len(snapshot.candidates), 1)
        self.assertEqual(snapshot.candidates[0].registration_status, "登録可能")
        self.assertTrue(snapshot.candidates[0].can_register)
        self.assertEqual(snapshot.registered_locations, ())

    def test_register_discovered_candidate_records_provenance(self) -> None:
        managed = self.manager.get_snapshot().candidates[0]
        location = self.manager.register_discovered(managed)

        self.assertEqual(location.origin, "discovered")
        self.assertEqual(location.source, "ZBRUSH_USER_ASSETS_DIR")
        reloaded = self.store.load().custom_locations[0]
        self.assertEqual(reloaded.origin, "discovered")
        self.assertEqual(reloaded.source, "ZBRUSH_USER_ASSETS_DIR")

    def test_registered_candidate_is_marked_as_already_registered(self) -> None:
        self.manager.register_discovered(self.manager.get_snapshot().candidates[0])
        managed = self.manager.get_snapshot().candidates[0]

        self.assertEqual(managed.registration_status, "登録済み")
        self.assertFalse(managed.can_register)

    def test_same_path_with_different_category_is_marked_as_conflict(self) -> None:
        self.store.add_custom_location(
            application="ZBrush",
            category="cache",
            path=str(self.discovery_path),
        )
        managed = self.manager.get_snapshot().candidates[0]

        self.assertEqual(managed.registration_status, "別の分類で登録済み")
        self.assertFalse(managed.can_register)

    def test_manual_registration_records_manual_origin(self) -> None:
        path = self.root / "AfterEffectsCache"
        path.mkdir()
        location = self.manager.register_manual(
            application="After Effects",
            category="cache",
            path=str(path),
        )
        self.assertEqual(location.origin, "manual")
        self.assertEqual(location.source, "手動登録")

    def test_remove_registered_rule_does_not_remove_target_folder(self) -> None:
        location = self.manager.register_manual(
            application="After Effects",
            category="cache",
            path=str(self.discovery_path),
        )
        self.assertTrue(self.manager.remove_registered(location.id))
        self.assertTrue(self.discovery_path.is_dir())
        self.assertEqual(self.store.load().custom_locations, ())

    def test_unregistrable_candidate_cannot_be_registered(self) -> None:
        unregistrable = DiscoveryCandidate(
            application="After Effects",
            category=None,
            path=None,
            status="アプリ内で確認してください",
            source="Adobe preferences",
            explanation="設定画面で確認が必要です。",
            registerable=False,
            path_exists=None,
        )
        manager = DccLocationManager(
            store=self.store,
            discovery=FakeDiscovery((unregistrable,)),
        )
        managed = manager.get_snapshot().candidates[0]
        self.assertFalse(managed.can_register)
        with self.assertRaises(ValueError):
            manager.register_discovered(managed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
