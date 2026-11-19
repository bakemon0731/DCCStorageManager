"""DCC Storage Manager - Step 01: Windows drive discovery and capacity scan.

This module is intentionally read-only. It does not delete, move, or modify files.

Run from Windows PowerShell:
    py -3 src\\core\\storage_scanner.py

External USB SSDs are detected by their mounted drive letter even when Windows
reports them as a fixed disk. Distinguishing internal and external fixed disks
will be handled in a later step using additional Windows storage metadata.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
from dataclasses import asdict, dataclass
from typing import Iterable
from ctypes import wintypes


# GetDriveTypeW values from the Windows API.
_DRIVE_UNKNOWN = 0
_DRIVE_NO_ROOT_DIR = 1
_DRIVE_REMOVABLE = 2
_DRIVE_FIXED = 3
_DRIVE_REMOTE = 4
_DRIVE_CDROM = 5
_DRIVE_RAMDISK = 6


@dataclass(frozen=True, slots=True)
class DriveInfo:
    """Capacity and volume information for one mounted Windows drive."""

    drive_letter: str
    mount_point: str
    volume_label: str
    drive_type_code: int
    drive_type_label: str
    filesystem: str
    total_bytes: int
    used_bytes: int
    free_bytes: int

    @property
    def usage_percent(self) -> float:
        if self.total_bytes <= 0:
            return 0.0
        return (self.used_bytes / self.total_bytes) * 100.0

    @property
    def total_gib(self) -> float:
        return self.total_bytes / (1024 ** 3)

    @property
    def used_gib(self) -> float:
        return self.used_bytes / (1024 ** 3)

    @property
    def free_gib(self) -> float:
        return self.free_bytes / (1024 ** 3)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-friendly representation including calculated values."""
        result = asdict(self)
        result.update(
            usage_percent=round(self.usage_percent, 1),
            total_gib=round(self.total_gib, 2),
            used_gib=round(self.used_gib, 2),
            free_gib=round(self.free_gib, 2),
        )
        return result


def _require_windows() -> None:
    if os.name != "nt":
        raise OSError(
            "DCC Storage Manager Step 01 currently targets Windows. "
            "Run this module on Windows."
        )


def _get_drive_type_label(drive_type: int) -> str:
    """Convert a Windows drive type code to a Japanese display label."""
    labels = {
        _DRIVE_UNKNOWN: "種類不明",
        _DRIVE_NO_ROOT_DIR: "利用不可",
        _DRIVE_REMOVABLE: "リムーバブルドライブ",
        # USB SSDs are sometimes reported as DRIVE_FIXED. They are still
        # discovered; internal/external classification is intentionally deferred.
        _DRIVE_FIXED: "固定ディスク（内蔵・外付けの区別は未判定）",
        _DRIVE_REMOTE: "ネットワークドライブ",
        _DRIVE_CDROM: "光学ドライブ",
        _DRIVE_RAMDISK: "RAMディスク",
    }
    return labels.get(drive_type, "種類不明")


def _get_volume_details(root: str) -> tuple[str, str]:
    """Return (volume label, filesystem) using GetVolumeInformationW."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_volume_info = kernel32.GetVolumeInformationW
    get_volume_info.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPWSTR,
        wintypes.DWORD,
    ]
    get_volume_info.restype = wintypes.BOOL

    volume_buffer = ctypes.create_unicode_buffer(261)
    filesystem_buffer = ctypes.create_unicode_buffer(261)
    serial_number = wintypes.DWORD()
    max_component_length = wintypes.DWORD()
    filesystem_flags = wintypes.DWORD()

    succeeded = get_volume_info(
        root,
        volume_buffer,
        len(volume_buffer),
        ctypes.byref(serial_number),
        ctypes.byref(max_component_length),
        ctypes.byref(filesystem_flags),
        filesystem_buffer,
        len(filesystem_buffer),
    )

    if not succeeded:
        # Capacity information may still be available even if volume metadata
        # cannot be read (for example, due to a transient device issue).
        return "", ""

    return volume_buffer.value, filesystem_buffer.value


def _iter_drive_roots() -> Iterable[str]:
    """Yield ready drive-letter roots currently mounted in Windows."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_logical_drives = kernel32.GetLogicalDrives
    get_logical_drives.restype = wintypes.DWORD

    drive_mask = get_logical_drives()
    if drive_mask == 0:
        error_code = ctypes.get_last_error()
        raise ctypes.WinError(error_code)

    for index in range(26):
        if drive_mask & (1 << index):
            root = f"{chr(ord('A') + index)}:\\"
            # GetLogicalDrives reports assigned letters; disk_usage confirms
            # that the mounted volume is currently ready to be queried.
            yield root


def scan_drives() -> list[DriveInfo]:
    """Discover mounted Windows drive letters and read their capacity.

    Unavailable drives are skipped rather than stopping the entire scan.
    No files or folders are opened recursively and nothing is modified.
    """
    _require_windows()

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_drive_type = kernel32.GetDriveTypeW
    get_drive_type.argtypes = [wintypes.LPCWSTR]
    get_drive_type.restype = wintypes.UINT

    results: list[DriveInfo] = []

    for root in _iter_drive_roots():
        try:
            drive_type = int(get_drive_type(root))
            usage = shutil.disk_usage(root)
            volume_label, filesystem = _get_volume_details(root)
        except (OSError, PermissionError):
            # A removable drive can be disconnected during scanning.
            continue

        used_bytes = usage.total - usage.free
        results.append(
            DriveInfo(
                drive_letter=root[:2],
                mount_point=root,
                volume_label=volume_label,
                drive_type_code=drive_type,
                drive_type_label=_get_drive_type_label(drive_type),
                filesystem=filesystem,
                total_bytes=usage.total,
                used_bytes=used_bytes,
                free_bytes=usage.free,
            )
        )

    return sorted(results, key=lambda item: item.drive_letter)


def _format_gib(value: float) -> str:
    return f"{value:,.2f} GiB"


def print_drive_report(drives: list[DriveInfo]) -> None:
    """Print a compact Japanese report to the terminal."""
    if not drives:
        print("利用可能なドライブが見つかりませんでした。")
        return

    print("=" * 92)
    print("DCC Storage Manager | ストレージ調査 Step 01")
    print("この調査は読み取り専用です。ファイルの削除・変更は行いません。")
    print("=" * 92)

    for drive in drives:
        label = drive.volume_label or "（ボリューム名なし）"
        filesystem = drive.filesystem or "不明"
        print(f"\n[{drive.drive_letter}] {label}")
        print(f"  種類       : {drive.drive_type_label}")
        print(f"  ファイルシステム: {filesystem}")
        print(f"  使用容量   : {_format_gib(drive.used_gib)} / {_format_gib(drive.total_gib)}")
        print(f"  空き容量   : {_format_gib(drive.free_gib)}")
        print(f"  使用率     : {drive.usage_percent:.1f}%")

    print("\n" + "-" * 92)
    print(f"検出ドライブ数: {len(drives)}")
    print("※ USB接続SSDが『固定ディスク』として表示される場合があります。")
    print("  ドライブ文字が割り当てられていれば検出対象になります。")


def main() -> int:
    try:
        drives = scan_drives()
        print_drive_report(drives)
        return 0
    except OSError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n調査を中断しました。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
