from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from threading import Event

# The project keeps application code under src/ and does not install it as a
# package. Add src/ so tests can import the same module used by the GUI.
PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(PROJECT_SRC))

from core.folder_scanner import format_bytes, scan_folder  # noqa: E402


class FolderScannerTests(unittest.TestCase):
    def _write_file(self, path: Path, size: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)

    def test_totals_and_first_level_directory_ranking(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_file(root / "root.bin", 11)
            self._write_file(root / "Maya" / "scene.ma", 100)
            self._write_file(root / "Maya" / "cache" / "sim.abc", 200)
            self._write_file(root / "AfterEffects" / "cache.bin", 50)

            result = scan_folder(root, top_file_limit=2)

            self.assertEqual(result.total_bytes, 361)
            self.assertEqual(result.files_scanned, 4)
            self.assertEqual(result.directories_scanned, 4)
            self.assertEqual(
                [(Path(item.path).name, item.size_bytes) for item in result.largest_directories],
                [("Maya", 300), ("AfterEffects", 50)],
            )
            self.assertEqual(
                [item.size_bytes for item in result.largest_files],
                [200, 100],
            )
            self.assertFalse(result.cancelled)

    def test_empty_child_directory_is_reported_with_zero_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "EmptyFolder").mkdir()

            result = scan_folder(root)

            self.assertEqual(result.total_bytes, 0)
            self.assertEqual(len(result.largest_directories), 1)
            self.assertEqual(result.largest_directories[0].size_bytes, 0)

    def test_cancel_event_stops_before_scanning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_file(root / "large.bin", 100)
            cancel_event = Event()
            cancel_event.set()

            result = scan_folder(root, cancel_event=cancel_event)

            self.assertTrue(result.cancelled)
            self.assertEqual(result.files_scanned, 0)
            self.assertEqual(result.total_bytes, 0)

    def test_invalid_top_file_limit_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ValueError):
                scan_folder(temp_dir, top_file_limit=0)

    def test_missing_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "does_not_exist"
            with self.assertRaises(FileNotFoundError):
                scan_folder(missing)

    def test_format_bytes(self) -> None:
        self.assertEqual(format_bytes(1024), "1.00 KiB")
        self.assertEqual(format_bytes(1024 * 1024), "1.00 MiB")


if __name__ == "__main__":
    unittest.main(verbosity=2)
