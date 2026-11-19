from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(PROJECT_SRC))

from core.dcc_discovery import DccLocationDiscovery  # noqa: E402


class DccLocationDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.appdata = self.root / "AppData" / "Roaming"
        self.public_documents = self.root / "Public" / "Documents"
        self.documents = self.root / "User" / "Documents"
        self.user_profile = self.root / "User"
        self.appdata.mkdir(parents=True)
        self.public_documents.mkdir(parents=True)
        self.documents.mkdir(parents=True)
        self.environment = {
            "APPDATA": str(self.appdata),
            "PUBLIC": str(self.root / "Public"),
            "USERPROFILE": str(self.user_profile),
        }

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _discovery(self, **overrides) -> DccLocationDiscovery:
        args = {
            "appdata": self.appdata,
            "public_documents": self.public_documents,
            "documents": self.documents,
            "user_profile": self.user_profile,
            "environment": self.environment,
        }
        args.update(overrides)
        return DccLocationDiscovery(**args)

    def _maya_report(self, path: Path, *, enabled: bool = True, generated_at: str | None = None) -> None:
        report_path = self.appdata / "DCCStorageManager" / "discovery" / "maya_autosave.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "application": "Maya",
                    "enabled": enabled,
                    "path": str(path),
                    "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
                }
            ),
            encoding="utf-8",
        )

    def test_maya_helper_report_discovers_actual_autosave_destination(self) -> None:
        destination = self.root / "MayaAutosave"
        destination.mkdir()
        self._maya_report(destination)

        results = self._discovery().discover()
        maya = next(item for item in results if item.application == "Maya")

        self.assertEqual(maya.category, "backup")
        self.assertEqual(Path(maya.path), destination)
        self.assertTrue(maya.registerable)
        self.assertEqual(maya.status, "設定から検出・フォルダ確認済み")

    def test_maya_disabled_autosave_is_not_registerable(self) -> None:
        destination = self.root / "MayaAutosave"
        destination.mkdir()
        self._maya_report(destination, enabled=False)

        maya = next(item for item in self._discovery().discover() if item.application == "Maya")

        self.assertFalse(maya.registerable)
        self.assertEqual(maya.status, "自動保存は無効")

    def test_stale_maya_report_requires_refresh(self) -> None:
        destination = self.root / "MayaAutosave"
        destination.mkdir()
        stale_date = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        self._maya_report(destination, generated_at=stale_date)

        maya = next(item for item in self._discovery().discover() if item.application == "Maya")

        self.assertFalse(maya.registerable)
        self.assertIn("古い", maya.status)

    def test_maya_environment_variable_is_only_provisional(self) -> None:
        destination = self.root / "MayaEnvAutosave"
        destination.mkdir()
        env = dict(self.environment)
        env["MAYA_AUTOSAVE_FOLDER"] = str(destination)

        maya = next(item for item in self._discovery(environment=env).discover() if item.application == "Maya")

        self.assertFalse(maya.registerable)
        self.assertIn("確認が必要", maya.status)
        self.assertEqual(maya.category, "backup")

    def test_maya_preferences_without_report_request_host_query(self) -> None:
        (self.documents / "maya" / "2026" / "prefs").mkdir(parents=True)

        maya = next(item for item in self._discovery().discover() if item.application == "Maya")

        self.assertIsNone(maya.path)
        self.assertFalse(maya.registerable)
        self.assertIn("Maya内", maya.status)

    def test_after_effects_preferences_are_not_misclassified_as_cache(self) -> None:
        (self.appdata / "Adobe" / "After Effects" / "26.0").mkdir(parents=True)

        ae = next(item for item in self._discovery().discover() if item.application == "After Effects")

        self.assertIsNone(ae.category)
        self.assertIsNone(ae.path)
        self.assertFalse(ae.registerable)
        self.assertIn("手動確認", ae.status)

    def test_zbrush_2026_user_asset_quicksave_folder_is_discovered(self) -> None:
        quicksave = self.appdata / "Maxon" / "ZBrush_ab12cd34" / "QuickSave"
        quicksave.mkdir(parents=True)

        results = self._discovery().discover()
        matches = [item for item in results if item.application == "ZBrush" and item.path == str(quicksave)]

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].category, "backup")
        self.assertTrue(matches[0].registerable)

    def test_zbrush_quicksave_path_text_file_is_discovered(self) -> None:
        configured = self.root / "External" / "ZBrushQuickSaves"
        configured.mkdir(parents=True)
        config_dir = self.appdata / "Maxon" / "ZBrush_ab12cd34"
        config_dir.mkdir(parents=True)
        (config_dir / "ZBrushQuickSavePath.txt").write_text(str(configured), encoding="utf-8")

        zbrush = [item for item in self._discovery().discover() if item.application == "ZBrush"]
        found = next(item for item in zbrush if item.path == str(configured))

        self.assertEqual(found.category, "backup")
        self.assertTrue(found.path_exists)

    def test_zbrush_scratch_disk_path_is_cache_candidate(self) -> None:
        configured = self.root / "External" / "ZBrushScratch"
        configured.mkdir(parents=True)
        config_dir = self.appdata / "Maxon" / "ZBrush_ab12cd34"
        config_dir.mkdir(parents=True)
        (config_dir / "ZBrushScratchDiskPath.txt").write_text(str(configured), encoding="utf-8")

        zbrush = [item for item in self._discovery().discover() if item.application == "ZBrush"]
        found = next(item for item in zbrush if item.path == str(configured))

        self.assertEqual(found.category, "cache")
        self.assertTrue(found.registerable)

    def test_zbrush_legacy_public_documents_quicksaves_are_discovered(self) -> None:
        quicksaves = self.public_documents / "ZBrushData2024" / "QuickSaves"
        quicksaves.mkdir(parents=True)

        zbrush = [item for item in self._discovery().discover() if item.application == "ZBrush"]
        found = next(item for item in zbrush if item.path == str(quicksaves))

        self.assertEqual(found.category, "backup")

    def test_missing_external_zbrush_path_is_retained_as_offline_candidate(self) -> None:
        config_dir = self.appdata / "Maxon" / "ZBrush_ab12cd34"
        config_dir.mkdir(parents=True)
        offline_path = r"R:\ZBrushExternal\QuickSaves"
        (config_dir / "ZBrushQuickSavePath.txt").write_text(offline_path, encoding="utf-8")

        zbrush = [item for item in self._discovery().discover() if item.application == "ZBrush"]
        found = next(item for item in zbrush if item.path == offline_path)

        self.assertEqual(found.category, "backup")
        self.assertFalse(found.path_exists)
        self.assertTrue(found.registerable)


    def test_zbrush_user_assets_environment_variable_is_used(self) -> None:
        custom_assets = self.root / "Network" / "ZBrushAssets"
        quicksave = custom_assets / "QuickSave"
        quicksave.mkdir(parents=True)
        env = dict(self.environment)
        env["ZBRUSH_USER_ASSETS_DIR"] = str(custom_assets)

        results = self._discovery(environment=env).discover()
        found = next(
            item for item in results
            if item.application == "ZBrush" and item.path == str(quicksave)
        )

        self.assertEqual(found.category, "backup")
        self.assertTrue(found.registerable)
        self.assertIn("ZBRUSH_USER_ASSETS_DIR", found.source)

    def test_zbrush_environment_asset_root_overrides_default_user_asset_root(self) -> None:
        default_quicksave = self.appdata / "Maxon" / "ZBrush_default" / "QuickSave"
        default_quicksave.mkdir(parents=True)
        custom_assets = self.root / "Network" / "ZBrushAssets"
        custom_quicksave = custom_assets / "QuickSave"
        custom_quicksave.mkdir(parents=True)
        env = dict(self.environment)
        env["ZBRUSH_USER_ASSETS_DIR"] = str(custom_assets)

        results = self._discovery(environment=env).discover()
        zbrush_paths = {
            item.path for item in results if item.application == "ZBrush" and item.path
        }

        self.assertIn(str(custom_quicksave), zbrush_paths)
        self.assertNotIn(str(default_quicksave), zbrush_paths)

    def test_zbrush_custom_quicksave_path_suppresses_adjacent_default_guess(self) -> None:
        asset_dir = self.appdata / "Maxon" / "ZBrush_ab12cd34"
        default_quicksave = asset_dir / "QuickSave"
        default_quicksave.mkdir(parents=True)
        configured_quicksave = self.root / "External" / "ArtistQuickSaves"
        configured_quicksave.mkdir(parents=True)
        (asset_dir / "ZBrushQuickSavePath.txt").write_text(
            str(configured_quicksave), encoding="utf-8"
        )

        results = self._discovery().discover()
        zbrush_paths = {
            item.path for item in results if item.application == "ZBrush" and item.path
        }

        self.assertIn(str(configured_quicksave), zbrush_paths)
        self.assertNotIn(str(default_quicksave), zbrush_paths)

    def test_identical_zbrush_paths_are_deduplicated(self) -> None:
        asset_dir = self.appdata / "Maxon" / "ZBrush_ab12cd34"
        shared = asset_dir / "QuickSave"
        shared.mkdir(parents=True)
        (asset_dir / "ZBrushQuickSavePath.txt").write_text(str(shared), encoding="utf-8")

        results = self._discovery().discover()
        matches = [item for item in results if item.application == "ZBrush" and item.path == str(shared)]

        self.assertEqual(len(matches), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
