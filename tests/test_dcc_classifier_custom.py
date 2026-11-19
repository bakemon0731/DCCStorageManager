from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(PROJECT_SRC))

from core.dcc_classifier import DataCategory, classify_path  # noqa: E402
from core.settings_store import CustomLocation  # noqa: E402


class CustomLocationClassifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.after_effects_cache = CustomLocation(
            id="ae-custom-1",
            application="After Effects",
            category="cache",
            path=r"E:\ScratchDisk01",
        )

    def test_custom_cache_location_classifies_unknown_named_folder(self) -> None:
        result = classify_path(
            r"E:\ScratchDisk01\render\frame_0001.bin",
            (self.after_effects_cache,),
        )
        self.assertEqual(result.application, "After Effects")
        self.assertEqual(result.category, DataCategory.CACHE_CANDIDATE)
        self.assertEqual(result.match_score, 100)
        self.assertEqual(result.rule_id, "custom_location:ae-custom-1")

    def test_custom_location_matches_root_itself(self) -> None:
        result = classify_path(r"E:\ScratchDisk01", (self.after_effects_cache,))
        self.assertEqual(result.category, DataCategory.CACHE_CANDIDATE)
        self.assertEqual(result.application, "After Effects")

    def test_custom_location_does_not_match_string_prefix_neighbor(self) -> None:
        result = classify_path(
            r"E:\ScratchDisk010\render.bin", (self.after_effects_cache,)
        )
        self.assertEqual(result.category, DataCategory.UNKNOWN)

    def test_windows_custom_location_comparison_is_case_insensitive(self) -> None:
        result = classify_path(
            r"e:\scratchdisk01\RENDER\FRAME.BIN", (self.after_effects_cache,)
        )
        self.assertEqual(result.category, DataCategory.CACHE_CANDIDATE)
        self.assertEqual(result.application, "After Effects")

    def test_builtin_backup_marker_overrides_custom_cache(self) -> None:
        result = classify_path(
            r"E:\ScratchDisk01\Backup\session.bak",
            (self.after_effects_cache,),
        )
        self.assertEqual(result.category, DataCategory.BACKUP)
        self.assertEqual(result.application, "After Effects")
        self.assertTrue(result.rule_id.startswith("backup_override:"))

    def test_more_specific_nested_registration_wins(self) -> None:
        nested_backup = CustomLocation(
            id="maya-backup-1",
            application="Maya",
            category="backup",
            path=r"E:\ScratchDisk01\MayaRecovery",
        )
        result = classify_path(
            r"E:\ScratchDisk01\MayaRecovery\scene.ma",
            (self.after_effects_cache, nested_backup),
        )
        self.assertEqual(result.category, DataCategory.BACKUP)
        self.assertEqual(result.application, "Maya")
        self.assertEqual(result.rule_id, "custom_location:maya-backup-1")

    def test_custom_backup_location_classifies_unknown_named_folder(self) -> None:
        custom_backup = CustomLocation(
            id="zbrush-backup-1",
            application="ZBrush",
            category="backup",
            path=r"F:\SculptRecovery",
        )
        result = classify_path(
            r"F:\SculptRecovery\tool_01.dat", (custom_backup,)
        )
        self.assertEqual(result.category, DataCategory.BACKUP)
        self.assertEqual(result.application, "ZBrush")


    def test_nested_backup_registration_overrides_parent_cache_registration(self) -> None:
        parent_cache = CustomLocation(
            id="parent-cache",
            application="After Effects",
            category="cache",
            path=r"E:\test",
        )
        nested_backup = CustomLocation(
            id="nested-backup",
            application="After Effects",
            category="backup",
            path=r"E:\test\Backup",
        )

        for path in (
            r"E:\test\Backup",
            r"E:\test\Backup\scene.ma",
            r"E:\test\Backup\nested\scene.ma",
        ):
            with self.subTest(path=path):
                result = classify_path(path, (parent_cache, nested_backup))
                self.assertEqual(result.category, DataCategory.BACKUP)
                self.assertEqual(result.rule_id, "custom_location:nested-backup")

    def test_parent_cache_location_is_mixed_when_it_contains_nested_backup(self) -> None:
        parent_cache = CustomLocation(
            id="parent-cache",
            application="After Effects",
            category="cache",
            path=r"E:\test",
        )
        nested_backup = CustomLocation(
            id="nested-backup",
            application="After Effects",
            category="backup",
            path=r"E:\test\Backup",
        )

        result = classify_path(r"E:\test", (parent_cache, nested_backup))

        self.assertEqual(result.category, DataCategory.MIXED)
        self.assertEqual(result.rule_id, "custom_location:mixed_descendants")
        self.assertIn(r"E:\test\Backup", result.reason)

    def test_parent_cache_remains_cache_when_no_conflicting_nested_registration(self) -> None:
        parent_cache = CustomLocation(
            id="parent-cache",
            application="After Effects",
            category="cache",
            path=r"E:\test",
        )
        result = classify_path(r"E:\test", (parent_cache,))
        self.assertEqual(result.category, DataCategory.CACHE_CANDIDATE)
        self.assertEqual(result.rule_id, "custom_location:parent-cache")

    def test_nested_backup_registration_works_when_custom_locations_are_generator(self) -> None:
        parent_cache = CustomLocation(
            id="parent-cache",
            application="After Effects",
            category="cache",
            path=r"E:\test",
        )
        nested_backup = CustomLocation(
            id="nested-backup",
            application="After Effects",
            category="backup",
            path=r"E:\test\Backup",
        )

        result = classify_path(
            r"E:\test\Backup\scene.ma",
            (item for item in (parent_cache, nested_backup)),
        )
        self.assertEqual(result.category, DataCategory.BACKUP)

    def test_posix_custom_location_is_supported(self) -> None:
        custom = CustomLocation(
            id="posix-cache-1",
            application="Maya",
            category="cache",
            path="/mnt/work/cache-scratch",
        )
        result = classify_path(
            "/mnt/work/cache-scratch/sim/data.abc", (custom,)
        )
        self.assertEqual(result.category, DataCategory.CACHE_CANDIDATE)
        self.assertEqual(result.application, "Maya")


if __name__ == "__main__":
    unittest.main(verbosity=2)
