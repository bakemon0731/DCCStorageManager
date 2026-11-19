from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(PROJECT_SRC))

from core.settings_store import (  # noqa: E402
    AppSettings,
    DuplicateLocationError,
    SettingsFormatError,
    SettingsStore,
)


class SettingsStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.temp_dir.name) / "config" / "settings.json"
        self.store = SettingsStore(self.settings_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_missing_settings_file_returns_defaults(self) -> None:
        settings = self.store.load()
        self.assertEqual(settings, AppSettings())
        self.assertFalse(self.settings_path.exists())

    def test_custom_location_survives_reload(self) -> None:
        added = self.store.add_custom_location(
            application="After Effects",
            category="cache",
            path=r"E:\ScratchDisk01",
        )

        reloaded = SettingsStore(self.settings_path).load()
        self.assertEqual(len(reloaded.custom_locations), 1)
        self.assertEqual(reloaded.custom_locations[0].id, added.id)
        self.assertEqual(reloaded.custom_locations[0].application, "After Effects")
        self.assertEqual(reloaded.custom_locations[0].category, "cache")
        self.assertEqual(reloaded.custom_locations[0].path, r"E:\ScratchDisk01")

    def test_duplicate_windows_path_is_rejected_case_insensitively(self) -> None:
        self.store.add_custom_location(
            application="After Effects", category="cache", path=r"E:\ScratchDisk01"
        )
        with self.assertRaises(DuplicateLocationError):
            self.store.add_custom_location(
                application="Maya", category="backup", path="e:\\scratchdisk01\\"
            )

    def test_relative_path_is_rejected(self) -> None:
        with self.assertRaises(SettingsFormatError):
            self.store.add_custom_location(
                application="Maya", category="cache", path="ScratchDisk01"
            )

    def test_drive_root_is_rejected(self) -> None:
        with self.assertRaises(SettingsFormatError):
            self.store.add_custom_location(
                application="After Effects", category="cache", path='E:\\'
            )

    def test_unsupported_application_is_rejected(self) -> None:
        with self.assertRaises(SettingsFormatError):
            self.store.add_custom_location(
                application="Blender", category="cache", path=r"E:\BlenderCache"
            )

    def test_remove_location_persists(self) -> None:
        added = self.store.add_custom_location(
            application="ZBrush", category="backup", path=r"E:\ZBrushSave"
        )
        self.assertTrue(self.store.remove_custom_location(added.id))
        self.assertEqual(self.store.load().custom_locations, ())
        self.assertFalse(self.store.remove_custom_location(added.id))

    def test_invalid_json_is_not_silently_replaced(self) -> None:
        self.settings_path.parent.mkdir(parents=True)
        original = "{broken json"
        self.settings_path.write_text(original, encoding="utf-8")
        with self.assertRaises(SettingsFormatError):
            self.store.load()
        self.assertEqual(self.settings_path.read_text(encoding="utf-8"), original)

    def test_unknown_settings_version_is_rejected(self) -> None:
        self.settings_path.parent.mkdir(parents=True)
        self.settings_path.write_text(
            json.dumps({"version": 99, "custom_locations": []}), encoding="utf-8"
        )
        with self.assertRaises(SettingsFormatError):
            self.store.load()


if __name__ == "__main__":
    unittest.main(verbosity=2)
