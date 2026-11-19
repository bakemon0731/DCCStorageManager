"""Read-only recursive folder size scanner for DCC Storage Manager.

This module scans one user-selected directory. It never deletes, moves, or
modifies files. Symbolic links are skipped to avoid leaving the selected tree
or following directory cycles.
"""

from __future__ import annotations

import heapq
import os
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable


@dataclass(frozen=True, slots=True)
class FileSizeEntry:
    """A file path and its size in bytes."""

    path: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class DirectorySizeEntry:
    """A first-level child directory and the size of all files beneath it."""

    path: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class ScanProgress:
    """A lightweight progress snapshot emitted during a scan."""

    files_scanned: int
    directories_scanned: int
    total_bytes: int


@dataclass(frozen=True, slots=True)
class FolderScanResult:
    """Summary and size rankings for one scanned directory."""

    root_path: str
    total_bytes: int
    files_scanned: int
    directories_scanned: int
    skipped_entries: int
    largest_files: tuple[FileSizeEntry, ...]
    largest_directories: tuple[DirectorySizeEntry, ...]
    cancelled: bool
    sample_errors: tuple[str, ...]


ProgressCallback = Callable[[ScanProgress], None]


def scan_folder(
    root_path: str | Path,
    *,
    top_file_limit: int = 20,
    progress_callback: ProgressCallback | None = None,
    cancel_event: Event | None = None,
    progress_interval: int = 100,
) -> FolderScanResult:
    """Recursively measure files under ``root_path`` without modifying them.

    Directory rankings represent the immediate child directories of the root;
    their sizes include all files in their descendants. Files directly inside
    the root are included in the total and file ranking, but not in a child
    directory ranking.

    Errors for individual entries are counted and scanning continues. Up to
    ten error messages are retained as examples to avoid unbounded memory use.
    """
    if top_file_limit < 1:
        raise ValueError("top_file_limit must be at least 1")
    if progress_interval < 1:
        raise ValueError("progress_interval must be at least 1")

    requested_root = Path(root_path).expanduser()
    if not requested_root.exists():
        raise FileNotFoundError(f"調査対象のフォルダが見つかりません: {requested_root}")
    if not requested_root.is_dir():
        raise NotADirectoryError(f"調査対象はフォルダではありません: {requested_root}")

    root = requested_root.resolve(strict=True)

    total_bytes = 0
    files_scanned = 0
    directories_scanned = 0
    skipped_entries = 0
    cancelled = False
    sample_errors: list[str] = []

    # Keep only the N largest files instead of retaining every file in memory.
    largest_file_heap: list[tuple[int, str]] = []

    # Aggregate the total size of each immediate child directory.
    first_level_directory_sizes: dict[Path, int] = {}

    # A stack avoids Python recursion-depth limits for deeply nested folders.
    pending_directories: list[Path] = [root]

    def record_error(path: str, error: OSError) -> None:
        nonlocal skipped_entries
        skipped_entries += 1
        if len(sample_errors) < 10:
            sample_errors.append(f"{path}: {error}")

    def emit_progress() -> None:
        if progress_callback is not None:
            progress_callback(
                ScanProgress(
                    files_scanned=files_scanned,
                    directories_scanned=directories_scanned,
                    total_bytes=total_bytes,
                )
            )

    while pending_directories:
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            break

        current_directory = pending_directories.pop()
        directories_scanned += 1

        try:
            with os.scandir(current_directory) as entries:
                for entry in entries:
                    if cancel_event is not None and cancel_event.is_set():
                        cancelled = True
                        break

                    try:
                        # Never follow symbolic links. They may point outside
                        # the selected folder or create directory cycles.
                        if entry.is_symlink():
                            skipped_entries += 1
                            continue

                        if entry.is_dir(follow_symlinks=False):
                            child_directory = Path(entry.path)
                            if current_directory == root:
                                first_level_directory_sizes.setdefault(child_directory, 0)
                            pending_directories.append(child_directory)
                            continue

                        if not entry.is_file(follow_symlinks=False):
                            continue

                        file_stat = entry.stat(follow_symlinks=False)
                        file_size = max(0, int(file_stat.st_size))
                        file_path = Path(entry.path)

                        total_bytes += file_size
                        files_scanned += 1

                        heap_item = (file_size, str(file_path))
                        if len(largest_file_heap) < top_file_limit:
                            heapq.heappush(largest_file_heap, heap_item)
                        elif heap_item > largest_file_heap[0]:
                            heapq.heapreplace(largest_file_heap, heap_item)

                        relative_parts = file_path.relative_to(root).parts
                        if len(relative_parts) >= 2:
                            first_level_directory = root / relative_parts[0]
                            first_level_directory_sizes[first_level_directory] = (
                                first_level_directory_sizes.get(first_level_directory, 0)
                                + file_size
                            )

                        if files_scanned % progress_interval == 0:
                            emit_progress()

                    except OSError as exc:
                        record_error(entry.path, exc)

            if cancelled:
                break

        except OSError as exc:
            record_error(str(current_directory), exc)

    # Always emit a final snapshot, including for small scans and cancellation.
    emit_progress()

    largest_files = tuple(
        FileSizeEntry(path=path, size_bytes=size)
        for size, path in sorted(largest_file_heap, reverse=True)
    )
    largest_directories = tuple(
        DirectorySizeEntry(path=str(path), size_bytes=size)
        for path, size in sorted(
            first_level_directory_sizes.items(),
            key=lambda item: (item[1], str(item[0])),
            reverse=True,
        )
    )

    return FolderScanResult(
        root_path=str(root),
        total_bytes=total_bytes,
        files_scanned=files_scanned,
        directories_scanned=directories_scanned,
        skipped_entries=skipped_entries,
        largest_files=largest_files,
        largest_directories=largest_directories,
        cancelled=cancelled,
        sample_errors=tuple(sample_errors),
    )


def format_bytes(size_bytes: int) -> str:
    """Format a byte count using binary units (KiB, MiB, GiB, TiB)."""
    value = float(size_bytes)
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:,.2f} {unit}"
        value /= 1024
    return f"{value:,.2f} TiB"
