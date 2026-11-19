from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(PROJECT_SRC))

from core.dcc_classifier import DataCategory, classify_path  # noqa: E402


class DCCClassifierTests(unittest.TestCase):
    def test_maya_autosave_directory_is_backup(self) -> None:
        result = classify_path(
            r"C:\Users\Artist\Documents\maya\projects\MyProject\autosave\auto-save1.ma"
        )
        self.assertEqual(result.application, "Maya")
        self.assertEqual(result.category, DataCategory.BACKUP)
        self.assertEqual(result.rule_id, "maya_autosave_directory")
        self.assertEqual(result.match_score, 97)

    def test_after_effects_disk_cache_is_cache_candidate(self) -> None:
        result = classify_path(
            r"E:\Adobe\After Effects\Disk Cache\frame_0001.cache"
        )
        self.assertEqual(result.application, "After Effects")
        self.assertEqual(result.category, DataCategory.CACHE_CANDIDATE)
        self.assertEqual(result.rule_id, "after_effects_cache_directory")

    def test_after_effects_versioned_folder_is_detected(self) -> None:
        result = classify_path(
            r"E:\Program Files\Adobe\Adobe After Effects 2025\Disk Cache\frame.cache"
        )
        self.assertEqual(result.application, "After Effects")
        self.assertEqual(result.category, DataCategory.CACHE_CANDIDATE)

    def test_after_effects_media_cache_is_cache_candidate(self) -> None:
        result = classify_path(
            r"E:\Adobe\After Effects\Media Cache Files\audio.cfa"
        )
        self.assertEqual(result.application, "After Effects")
        self.assertEqual(result.category, DataCategory.CACHE_CANDIDATE)

    def test_zbrush_quicksave_is_backup(self) -> None:
        result = classify_path(
            r"C:\Users\Artist\AppData\Roaming\Maxon\ZBrush_abc123\QuickSave\Project.zpr"
        )
        self.assertEqual(result.application, "ZBrush")
        self.assertEqual(result.category, DataCategory.BACKUP)
        self.assertEqual(result.rule_id, "zbrush_quicksave_directory")

    def test_generic_cache_folder_is_only_a_candidate(self) -> None:
        result = classify_path("E:/Work/Cache/simulation.abc")
        self.assertEqual(result.category, DataCategory.CACHE_CANDIDATE)
        self.assertEqual(result.application, "不明")
        self.assertIn("自動削除は行いません", result.safety_note)

    def test_backup_rule_has_priority_over_cache_rule(self) -> None:
        result = classify_path("E:/Work/Cache/Backup/scene.bak")
        self.assertEqual(result.category, DataCategory.BACKUP)
        self.assertEqual(result.rule_id, "generic_backup_directory")

    def test_backup_extension_is_detected(self) -> None:
        result = classify_path("E:/Work/scene.ma.bak")
        self.assertEqual(result.category, DataCategory.BACKUP)
        self.assertEqual(result.rule_id, "backup_filename")

    def test_similarly_named_project_folder_is_not_false_positive(self) -> None:
        result = classify_path("E:/Work/MyCacheProject/texture.exr")
        self.assertEqual(result.category, DataCategory.UNKNOWN)

    def test_temporary_extension_is_cache_candidate(self) -> None:
        result = classify_path("E:/Work/render.tmp")
        self.assertEqual(result.category, DataCategory.CACHE_CANDIDATE)
        self.assertEqual(result.rule_id, "temporary_filename")

    def test_posix_path_is_supported(self) -> None:
        result = classify_path(
            "/Users/artist/Library/Application Support/Maxon/ZBrush_abc123/QuickSave/model.zpr"
        )
        self.assertEqual(result.application, "ZBrush")
        self.assertEqual(result.category, DataCategory.BACKUP)

    def test_path_object_is_supported(self) -> None:
        result = classify_path(Path("E:/Work/Cache/render.bin"))
        self.assertEqual(result.category, DataCategory.CACHE_CANDIDATE)

    def test_empty_path_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            classify_path("   ")


if __name__ == "__main__":
    unittest.main(verbosity=2)
