from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(PROJECT_SRC))

from core.dcc_discovery import DccLocationDiscovery  # noqa: E402


class ZBrushEnvironmentDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.assets_root = self.root / "SharedZBrushAssets"
        self.appdata = self.root / "AppData"
        self.public_documents = self.root / "Public" / "Documents"
        self.documents = self.root / "User" / "Documents"
        self.user_profile = self.root / "User"
        self.appdata.mkdir(parents=True)
        self.public_documents.mkdir(parents=True)
        self.documents.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _discover(self, env_value: str) -> tuple:
        return DccLocationDiscovery(
            appdata=self.appdata,
            public_documents=self.public_documents,
            documents=self.documents,
            user_profile=self.user_profile,
            environment={"ZBRUSH_USER_ASSETS_DIR": env_value},
        ).discover()

    def test_environment_asset_root_and_quicksave_are_discovered(self) -> None:
        quicksave = self.assets_root / "QuickSave"
        quicksave.mkdir(parents=True)

        candidates = [
            candidate
            for candidate in self._discover(str(self.assets_root))
            if candidate.application == "ZBrush"
        ]
        root_candidate = next(item for item in candidates if item.path == str(self.assets_root))
        quicksave_candidate = next(item for item in candidates if item.path == str(quicksave))

        self.assertFalse(root_candidate.registerable)
        self.assertIsNone(root_candidate.category)
        self.assertTrue(quicksave_candidate.registerable)
        self.assertEqual(quicksave_candidate.category, "backup")
        self.assertEqual(quicksave_candidate.source, "ZBRUSH_USER_ASSETS_DIR")

    def test_environment_config_file_discovers_external_scratch_path(self) -> None:
        scratch_path = self.root / "ExternalScratch"
        scratch_path.mkdir()
        self.assets_root.mkdir(parents=True)
        (self.assets_root / "ZBrushScratchDiskPath.txt").write_text(
            str(scratch_path), encoding="utf-8"
        )

        candidates = [
            candidate
            for candidate in self._discover(str(self.assets_root))
            if candidate.application == "ZBrush"
        ]
        scratch_candidate = next(item for item in candidates if item.path == str(scratch_path))

        self.assertEqual(scratch_candidate.category, "cache")
        self.assertTrue(scratch_candidate.registerable)
        self.assertIn("ZBRUSH_USER_ASSETS_DIR", scratch_candidate.source)

    def test_environment_override_does_not_report_default_root_as_active(self) -> None:
        default_quicksave = self.appdata / "Maxon" / "ZBrush_oldhash" / "QuickSave"
        default_quicksave.mkdir(parents=True)
        env_quicksave = self.assets_root / "QuickSave"
        env_quicksave.mkdir(parents=True)

        candidates = [
            candidate
            for candidate in self._discover(str(self.assets_root))
            if candidate.application == "ZBrush"
        ]
        candidate_paths = {candidate.path for candidate in candidates}

        self.assertIn(str(env_quicksave), candidate_paths)
        self.assertNotIn(str(default_quicksave), candidate_paths)

    def test_missing_environment_root_is_not_registerable(self) -> None:
        missing = self.root / "OfflineShare"
        candidates = [
            candidate
            for candidate in self._discover(str(missing))
            if candidate.application == "ZBrush"
        ]
        root_candidate = next(item for item in candidates if item.source == "ZBRUSH_USER_ASSETS_DIR")

        self.assertFalse(root_candidate.registerable)
        self.assertFalse(root_candidate.path_exists)
        self.assertEqual(root_candidate.status, "環境変数の保存先にアクセスできません")


if __name__ == "__main__":
    unittest.main(verbosity=2)
