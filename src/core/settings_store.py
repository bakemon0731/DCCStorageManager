"""Persistent user settings for DCC Storage Manager.

Settings are stored separately from disposable cache data. Writes are atomic:
new JSON is written to a temporary file and then replaces the old file.
"""

from __future__ import annotations

import json
import os
import ntpath
import posixpath
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from uuid import uuid4


SETTINGS_VERSION = 1
SUPPORTED_APPLICATIONS = ("Maya", "After Effects", "ZBrush")
SUPPORTED_CATEGORIES = ("cache", "backup")
SUPPORTED_ORIGINS = ("manual", "discovered")


class SettingsError(Exception):
    """Base exception for settings operations."""


class SettingsFormatError(SettingsError):
    """Raised when a settings file is invalid or unsupported."""


class DuplicateLocationError(SettingsError):
    """Raised when the same location has already been registered."""


@dataclass(frozen=True, slots=True)
class CustomLocation:
    """One user-registered DCC data location.

    category is a stable, language-independent value: ``cache`` or ``backup``.
    ``path`` may refer to an offline external drive; it need not exist while
    loading settings.
    """

    id: str
    application: str
    category: str
    path: str
    origin: str = "manual"
    source: str = "手動登録"


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Validated application settings loaded from the JSON file."""

    version: int = SETTINGS_VERSION
    custom_locations: tuple[CustomLocation, ...] = ()


def get_default_settings_path() -> Path:
    """Return the per-user settings path for the current operating system."""
    if os.name == "nt":
        base = os.environ.get("APPDATA")
        base_path = Path(base) if base else Path.home() / "AppData" / "Roaming"
    elif sys.platform == "darwin":
        base_path = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_CONFIG_HOME")
        base_path = Path(base) if base else Path.home() / ".config"

    return base_path / "DCCStorageManager" / "settings.json"


def _is_windows_style_path(raw_path: str) -> bool:
    return "\\" in raw_path or (len(raw_path) >= 2 and raw_path[1] == ":")


def normalize_path_for_comparison(raw_path: str) -> tuple[str, str]:
    """Normalize a path lexically for exact/descendant comparisons.

    This intentionally does not resolve symlinks or require the path to exist.
    Windows path comparisons are case-insensitive; POSIX comparisons remain
    case-sensitive.
    """
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("保存先のパスを入力してください。")

    value = raw_path.strip()
    if _is_windows_style_path(value):
        normalized = ntpath.normpath(value.replace("/", "\\"))
        pure_path = PureWindowsPath(normalized)
        if not pure_path.is_absolute():
            raise ValueError("保存先には絶対パスを指定してください。")
        return "windows", ntpath.normcase(normalized)

    normalized = posixpath.normpath(value)
    pure_path = PurePosixPath(normalized)
    if not pure_path.is_absolute():
        raise ValueError("保存先には絶対パスを指定してください。")
    return "posix", normalized


def _validate_location_data(
    *,
    location_id: str,
    application: str,
    category: str,
    path: str,
    origin: str = "manual",
    source: str = "手動登録",
) -> CustomLocation:
    if not isinstance(location_id, str) or not location_id.strip():
        raise SettingsFormatError("カスタム保存先のIDが不正です。")
    if application not in SUPPORTED_APPLICATIONS:
        raise SettingsFormatError(f"未対応のアプリケーションです: {application}")
    if category not in SUPPORTED_CATEGORIES:
        raise SettingsFormatError(f"未対応のデータ分類です: {category}")
    if origin not in SUPPORTED_ORIGINS:
        raise SettingsFormatError(f"未対応の登録元です: {origin}")
    if not isinstance(source, str) or not source.strip():
        source = "手動登録" if origin == "manual" else "自動検出"
    if len(source) > 200:
        raise SettingsFormatError("登録元の説明は200文字以内にしてください。")
    if not isinstance(path, str) or not path.strip():
        raise SettingsFormatError("カスタム保存先のパスが空です。")
    try:
        normalized_kind, normalized_path = normalize_path_for_comparison(path)
    except ValueError as exc:
        raise SettingsFormatError(str(exc)) from exc

    # Registering a whole drive/root would classify almost every file on that
    # volume. Require a concrete child folder instead.
    if normalized_kind == "windows":
        component_count = len(PureWindowsPath(normalized_path).parts)
    else:
        component_count = len(PurePosixPath(normalized_path).parts)
    if component_count <= 1:
        raise SettingsFormatError("ドライブやルート全体ではなく、具体的なフォルダを登録してください。")

    # Store a normalized but readable path. Preserve Windows drive spelling,
    # while removing redundant separators and dot segments.
    if normalized_kind == "windows":
        stored_path = ntpath.normpath(path.strip().replace("/", "\\"))
    else:
        stored_path = posixpath.normpath(path.strip())

    return CustomLocation(
        id=location_id.strip(),
        application=application,
        category=category,
        path=stored_path,
        origin=origin,
        source=source.strip(),
    )


class SettingsStore:
    """Load, validate, and atomically save user settings."""

    def __init__(self, settings_path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(settings_path) if settings_path is not None else get_default_settings_path()

    def load(self) -> AppSettings:
        """Load settings. A missing file means first launch; invalid JSON is an error."""
        if not self.path.exists():
            return AppSettings()

        try:
            raw: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SettingsFormatError(f"設定ファイルを読み込めません: {exc}") from exc

        if not isinstance(raw, dict):
            raise SettingsFormatError("設定ファイルの最上位はJSONオブジェクトである必要があります。")

        version = raw.get("version")
        if version != SETTINGS_VERSION:
            raise SettingsFormatError(
                f"未対応の設定バージョンです: {version!r}（対応: {SETTINGS_VERSION}）"
            )

        locations_data = raw.get("custom_locations", [])
        if not isinstance(locations_data, list):
            raise SettingsFormatError("custom_locations は配列である必要があります。")

        locations: list[CustomLocation] = []
        seen_paths: set[tuple[str, str]] = set()
        seen_ids: set[str] = set()

        for index, item in enumerate(locations_data):
            if not isinstance(item, dict):
                raise SettingsFormatError(f"カスタム保存先 {index + 1} 件目の形式が不正です。")
            try:
                location = _validate_location_data(
                    location_id=item.get("id"),
                    application=item.get("application"),
                    category=item.get("category"),
                    path=item.get("path"),
                    # Old STEP 04C settings had no provenance fields.
                    # Treat them as manual registrations for compatibility.
                    origin=item.get("origin", "manual"),
                    source=item.get(
                        "source",
                        "手動登録（旧形式）" if item.get("origin") is None else "手動登録",
                    ),
                )
                path_key = normalize_path_for_comparison(location.path)
            except (ValueError, SettingsFormatError) as exc:
                raise SettingsFormatError(
                    f"カスタム保存先 {index + 1} 件目が不正です: {exc}"
                ) from exc

            if location.id in seen_ids:
                raise SettingsFormatError(f"カスタム保存先IDが重複しています: {location.id}")
            if path_key in seen_paths:
                raise SettingsFormatError(f"カスタム保存先パスが重複しています: {location.path}")

            seen_ids.add(location.id)
            seen_paths.add(path_key)
            locations.append(location)

        return AppSettings(version=version, custom_locations=tuple(locations))

    def save(self, settings: AppSettings) -> None:
        """Atomically persist settings without touching any DCC data files."""
        if settings.version != SETTINGS_VERSION:
            raise SettingsError(f"保存できない設定バージョンです: {settings.version}")

        payload = {
            "version": SETTINGS_VERSION,
            "custom_locations": [
                {
                    "id": location.id,
                    "application": location.application,
                    "category": location.category,
                    "path": location.path,
                    "origin": location.origin,
                    "source": location.source,
                }
                for location in settings.custom_locations
            ],
        }

        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_name(self.path.name + ".tmp")
        try:
            with temporary_path.open("w", encoding="utf-8", newline="\n") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_path, self.path)
        except OSError as exc:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise SettingsError(f"設定ファイルを保存できません: {exc}") from exc

    def add_custom_location(
        self,
        *,
        application: str,
        category: str,
        path: str,
        origin: str = "manual",
        source: str = "手動登録",
    ) -> CustomLocation:
        """Validate and append one custom location, then save immediately."""
        new_location = _validate_location_data(
            location_id=uuid4().hex,
            application=application,
            category=category,
            path=path,
            origin=origin,
            source=source,
        )
        settings = self.load()
        new_key = normalize_path_for_comparison(new_location.path)

        for existing in settings.custom_locations:
            if normalize_path_for_comparison(existing.path) == new_key:
                raise DuplicateLocationError(
                    "同じ保存先はすでに登録されています。既存の登録を確認してください。"
                )

        updated = AppSettings(
            version=SETTINGS_VERSION,
            custom_locations=(*settings.custom_locations, new_location),
        )
        self.save(updated)
        return new_location

    def remove_custom_location(self, location_id: str) -> bool:
        """Remove a registered location by ID. Return False when not found."""
        settings = self.load()
        remaining = tuple(
            location for location in settings.custom_locations
            if location.id != location_id
        )
        if len(remaining) == len(settings.custom_locations):
            return False

        self.save(AppSettings(version=SETTINGS_VERSION, custom_locations=remaining))
        return True
