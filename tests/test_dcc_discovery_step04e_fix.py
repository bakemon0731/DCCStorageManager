from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(PROJECT_SRC))

from core.dcc_discovery import DccLocationDiscovery  # noqa: E402


class Step04EDiscoveryRegressionTests(unittest.TestCase):
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

    def test_maya_environment_variable_is_only_provisional(self) -> None:
        destination = self.root / "MayaEnvAutosave"
        destination.mkdir()
        env = dict(self.environment)
        env["MAYA_AUTOSAVE_FOLDER"] = str(destination)

        maya = next(
            item
            for item in DccLocationDiscovery(
                appdata=self.appdata,
                public_documents=self.public_documents,
                documents=self.documents,
                user_profile=self.user_profile,
                environment=env,
            ).discover()
            if item.application == "Maya"
        )

        self.assertFalse(maya.registerable)
        self.assertIn("確認が必要", maya.status)
        self.assertEqual(maya.category, "backup")
        self.assertEqual(Path(maya.path), destination)

    def test_zbrush_custom_quicksave_path_suppresses_adjacent_default_guess(self) -> None:
        asset_dir = self.appdata / "Maxon" / "ZBrush_ab12cd34"
        default_quicksave = asset_dir / "QuickSave"
        default_quicksave.mkdir(parents=True)
        configured_quicksave = self.root / "External" / "ArtistQuickSaves"
        configured_quicksave.mkdir(parents=True)
        (asset_dir / "ZBrushQuickSavePath.txt").write_text(
            str(configured_quicksave), encoding="utf-8"
        )

        results = DccLocationDiscovery(
            appdata=self.appdata,
            public_documents=self.public_documents,
            documents=self.documents,
            user_profile=self.user_profile,
            environment=self.environment,
        ).discover()
        zbrush_paths = {
            item.path for item in results if item.application == "ZBrush" and item.path
        }

        self.assertIn(str(configured_quicksave), zbrush_paths)
        self.assertNotIn(str(default_quicksave), zbrush_paths)


if __name__ == "__main__":
    unittest.main(verbosity=2)
