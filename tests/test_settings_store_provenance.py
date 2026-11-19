from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(PROJECT_SRC))

from core.settings_store import SettingsFormatError, SettingsStore  # noqa: E402


class SettingsStoreProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.temp_dir.name) / "settings.json"
        self.store = SettingsStore(self.settings_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_discovery_origin_and_source_survive_reload(self) -> None:
        location = self.store.add_custom_location(
            application="ZBrush",
            category="backup",
            path=r"E:\ZBrush\QuickSave",
            origin="discovered",
            source="ZBRUSH_USER_ASSETS_DIR",
        )

        loaded = self.store.load().custom_locations[0]
        self.assertEqual(loaded.id, location.id)
        self.assertEqual(loaded.origin, "discovered")
        self.assertEqual(loaded.source, "ZBRUSH_USER_ASSETS_DIR")

    def test_manual_origin_is_recorded_by_default(self) -> None:
        self.store.add_custom_location(
            application="After Effects",
            category="cache",
            path=r"E:\ScratchDisk01",
        )
        loaded = self.store.load().custom_locations[0]
        self.assertEqual(loaded.origin, "manual")
        self.assertEqual(loaded.source, "手動登録")

    def test_legacy_settings_without_provenance_remain_compatible(self) -> None:
        self.settings_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "custom_locations": [
                        {
                            "id": "legacy-1",
                            "application": "Maya",
                            "category": "backup",
                            "path": r"E:\Maya\Autosave",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        loaded = self.store.load().custom_locations[0]
        self.assertEqual(loaded.origin, "manual")
        self.assertEqual(loaded.source, "手動登録（旧形式）")

    def test_invalid_origin_is_rejected(self) -> None:
        with self.assertRaises(SettingsFormatError):
            self.store.add_custom_location(
                application="Maya",
                category="backup",
                path=r"E:\Maya\Autosave",
                origin="guessed",
                source="test",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
