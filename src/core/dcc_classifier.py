"""Conservative, read-only classifier for common DCC cache/backup paths.

This module labels candidates only. It never deletes, moves, or modifies data.
A classification is not proof that an item is safe to delete.
"""

from __future__ import annotations

import os
import re
import ntpath
import posixpath
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Iterable, TypeAlias

from core.settings_store import CustomLocation

PathLike: TypeAlias = str | os.PathLike[str]


class DataCategory(str, Enum):
    """High-level data categories used by the cleanup review UI."""

    CACHE_CANDIDATE = "キャッシュ候補"
    BACKUP = "バックアップ候補"
    MIXED = "複数分類（要確認）"
    UNKNOWN = "不明"


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    """Classification result with an explanation and a safety reminder."""

    path: str
    application: str
    category: DataCategory
    match_score: int
    rule_id: str
    reason: str
    safety_note: str


@dataclass(frozen=True, slots=True)
class _Rule:
    """One small, deterministic path-matching rule."""

    rule_id: str
    category: DataCategory
    path_names: frozenset[str] = frozenset()
    filename_prefixes: tuple[str, ...] = ()
    filename_suffixes: tuple[str, ...] = ()
    application: str | None = None
    match_score: int = 0
    priority: int = 0
    reason: str = ""


_BACKUP_NAMES = frozenset(
    {
        "autosave",
        "autosaves",
        "autobackup",
        "autobackups",
        "quicksave",
        "quicksaves",
        "backup",
        "backups",
        "recovery",
        "crashrecovery",
    }
)

_CACHE_NAMES = frozenset(
    {
        "cache",
        "caches",
        "diskcache",
        "mediacache",
        "mediacachefiles",
        "temp",
        "tmp",
        "temporary",
        "tempfiles",
    }
)

_RULES: tuple[_Rule, ...] = (
    # App-specific rules receive a higher heuristic match score than generic matches.
    _Rule(
        rule_id="maya_autosave_directory",
        category=DataCategory.BACKUP,
        path_names=frozenset({"autosave", "autosaves"}),
        application="Maya",
        match_score=97,
        priority=120,
        reason="Mayaの自動保存先を示すフォルダ名がパスにあります。",
    ),
    _Rule(
        rule_id="after_effects_cache_directory",
        category=DataCategory.CACHE_CANDIDATE,
        path_names=frozenset({"diskcache", "mediacache", "mediacachefiles"}),
        application="After Effects",
        match_score=97,
        priority=115,
        reason="After EffectsのDisk CacheまたはMedia Cacheを示すフォルダ名があります。",
    ),
    _Rule(
        rule_id="zbrush_quicksave_directory",
        category=DataCategory.BACKUP,
        path_names=frozenset({"quicksave", "quicksaves", "autosave", "autosaves"}),
        application="ZBrush",
        match_score=97,
        priority=120,
        reason="ZBrushのQuickSaveまたはAutoSaveを示すフォルダ名があります。",
    ),
    # Generic backup rules deliberately outrank cache rules. A folder named
    # Backup inside a Cache directory must not be treated as disposable cache.
    _Rule(
        rule_id="generic_backup_directory",
        category=DataCategory.BACKUP,
        path_names=_BACKUP_NAMES,
        match_score=88,
        priority=100,
        reason="自動保存・QuickSave・バックアップを示すフォルダ名があります。",
    ),
    _Rule(
        rule_id="backup_filename",
        category=DataCategory.BACKUP,
        filename_prefixes=("autosave", "quicksave", "backup"),
        filename_suffixes=(".bak", ".backup"),
        match_score=78,
        priority=95,
        reason="ファイル名または拡張子がバックアップ形式に一致します。",
    ),
    _Rule(
        rule_id="generic_cache_directory",
        category=DataCategory.CACHE_CANDIDATE,
        path_names=_CACHE_NAMES,
        match_score=80,
        priority=80,
        reason="Cache・Temp系のフォルダ名があります。実際に再生成可能か確認が必要です。",
    ),
    _Rule(
        rule_id="temporary_filename",
        category=DataCategory.CACHE_CANDIDATE,
        filename_suffixes=(".tmp", ".temp"),
        match_score=68,
        priority=70,
        reason="一時ファイルで使われる拡張子に一致します。",
    ),
)


_CATEGORY_SAFETY_NOTES = {
    DataCategory.CACHE_CANDIDATE: (
        "キャッシュ候補ですが、使用中の可能性や再生成コストがあります。"
        "アプリを終了し、必要性を確認してください。自動削除は行いません。"
    ),
    DataCategory.BACKUP: (
        "復元に必要なデータの可能性があります。最新世代や復元要否を確認してください。"
        "自動削除は行いません。"
    ),
    DataCategory.MIXED: (
        "このフォルダ配下に異なる種類の登録先が含まれています。親フォルダ全体を"
        "キャッシュまたはバックアップとして扱わず、個別のフォルダを確認してください。"
        "自動削除は行いません。"
    ),
    DataCategory.UNKNOWN: (
        "名前だけでは分類できません。プロジェクトデータの可能性があるため、削除候補にしません。"
    ),
}


def _normalize_name(value: str) -> str:
    """Normalize a path component for conservative exact-name matching."""
    return re.sub(r"[\s_-]+", "", value.casefold())


def _split_path(raw_path: str) -> tuple[str, ...]:
    """Split either Windows or POSIX paths, independent of host OS."""
    if "\\" in raw_path or re.match(r"^[A-Za-z]:", raw_path):
        parts = PureWindowsPath(raw_path).parts
    else:
        parts = PurePosixPath(raw_path).parts
    return tuple(part for part in parts if part not in {"", "."})


def _detect_application(parts: tuple[str, ...]) -> str:
    """Infer an application only when a recognizable path component exists."""
    normalized_parts = tuple(_normalize_name(part) for part in parts)

    for part in normalized_parts:
        if re.fullmatch(r"(?:adobe)?aftereffects(?:20\d{2})?", part):
            return "After Effects"

    for part in normalized_parts:
        if part == "maya" or re.fullmatch(r"maya20\d{2}", part):
            return "Maya"

    for part in normalized_parts:
        if part == "zbrush":
            return "ZBrush"
        # Older user-data paths may use ZBrushData2026; app asset folders in
        # newer versions use ZBrush_[hash]. Normalization removes underscores.
        if re.fullmatch(r"zbrushdata20\d{2}", part):
            return "ZBrush"
        if re.fullmatch(r"zbrush20\d{2}", part):
            return "ZBrush"
        if re.fullmatch(r"zbrush[a-z0-9]{6,}", part):
            return "ZBrush"

    return "不明"


def _matches_rule(
    rule: _Rule,
    *,
    normalized_parts: tuple[str, ...],
    normalized_filename: str,
    application: str,
) -> bool:
    if rule.application is not None and rule.application != application:
        return False

    has_path_match = any(part in rule.path_names for part in normalized_parts)
    has_prefix_match = any(
        normalized_filename.startswith(prefix)
        for prefix in rule.filename_prefixes
    )
    # Suffixes are checked against the original filename so dots are retained.
    has_suffix_match = any(
        normalized_filename.endswith(suffix)
        for suffix in rule.filename_suffixes
    )
    return has_path_match or has_prefix_match or has_suffix_match



def _is_windows_style_path(raw_path: str) -> bool:
    return "\\\\" in raw_path or (len(raw_path) >= 2 and raw_path[1] == ":")


def _is_same_or_descendant_path(candidate: str, registered_root: str) -> bool:
    """Compare paths by components, not string prefixes.

    This is a lexical comparison: it does not resolve symlinks or require an
    external drive to be connected. Windows paths are case-insensitive.
    """
    candidate_windows = _is_windows_style_path(candidate)
    root_windows = _is_windows_style_path(registered_root)
    if candidate_windows != root_windows:
        return False

    if candidate_windows:
        candidate_normalized = ntpath.normpath(candidate.replace("/", "\\"))
        root_normalized = ntpath.normpath(registered_root.replace("/", "\\"))
        candidate_parts = tuple(
            part.casefold() for part in PureWindowsPath(candidate_normalized).parts
        )
        root_parts = tuple(
            part.casefold() for part in PureWindowsPath(root_normalized).parts
        )
    else:
        candidate_parts = PurePosixPath(posixpath.normpath(candidate)).parts
        root_parts = PurePosixPath(posixpath.normpath(registered_root)).parts

    return (
        len(candidate_parts) >= len(root_parts)
        and candidate_parts[: len(root_parts)] == root_parts
    )


def _find_custom_location(
    raw_path: str, custom_locations: Iterable[CustomLocation]
) -> CustomLocation | None:
    """Return the most specific registered location matching this path."""
    matches = [
        location
        for location in custom_locations
        if _is_same_or_descendant_path(raw_path, location.path)
    ]
    if not matches:
        return None

    # A nested registration is more specific than its parent registration.
    def path_depth(location: CustomLocation) -> int:
        if _is_windows_style_path(location.path):
            return len(PureWindowsPath(location.path).parts)
        return len(PurePosixPath(location.path).parts)

    # Prefer the deepest registration. If malformed/external settings ever
    # contain same-depth overlapping matches, prefer backup conservatively.
    return max(
        matches,
        key=lambda location: (
            path_depth(location),
            1 if location.category == "backup" else 0,
        ),
    )


def _find_conflicting_descendant_locations(
    raw_path: str,
    parent_location: CustomLocation,
    custom_locations: Iterable[CustomLocation],
) -> tuple[CustomLocation, ...]:
    """Find nested registrations that make a registered parent mixed.

    Example: E:\\test is registered as cache while
    E:\\test\\Backup is registered as backup. The exact parent folder
    contains both categories, so it must not be presented as pure cache.
    """
    conflicts: list[CustomLocation] = []
    for location in custom_locations:
        if location.id == parent_location.id:
            continue
        if (
            location.category == parent_location.category
            and location.application == parent_location.application
        ):
            continue

        # The registered path must be strictly below the candidate path.
        is_descendant = _is_same_or_descendant_path(location.path, raw_path)
        is_same_or_ancestor = _is_same_or_descendant_path(raw_path, location.path)
        if is_descendant and not is_same_or_ancestor:
            conflicts.append(location)

    return tuple(conflicts)


def classify_path(
    path: PathLike, custom_locations: Iterable[CustomLocation] = ()
) -> ClassificationResult:
    """Classify a path using conservative names and path signatures.

    The function does not inspect file contents, access the filesystem, or
    infer that an item is safe to delete. Explicit user-registered locations
    can classify arbitrary paths. Built-in backup markers override a custom
    cache registration to protect likely recovery data.
    """
    try:
        raw_path_value = os.fspath(path)
    except TypeError as exc:
        raise ValueError("path must be a non-empty string or Path") from exc
    if not isinstance(raw_path_value, str) or not raw_path_value.strip():
        raise ValueError("path must be a non-empty string or Path")

    raw_path = raw_path_value.strip()
    # Materialize once because custom locations are consulted more than once
    # (the caller may have supplied a one-shot generator).
    custom_location_list = tuple(custom_locations)
    parts = _split_path(raw_path)
    if not parts:
        return ClassificationResult(
            path=raw_path,
            application="不明",
            category=DataCategory.UNKNOWN,
            match_score=0,
            rule_id="no_path_components",
            reason="判定できるパス要素がありません。",
            safety_note=_CATEGORY_SAFETY_NOTES[DataCategory.UNKNOWN],
        )

    normalized_parts = tuple(_normalize_name(part) for part in parts)
    normalized_filename = normalized_parts[-1]
    application = _detect_application(parts)

    matched_rules = [
        rule
        for rule in _RULES
        if _matches_rule(
            rule,
            normalized_parts=normalized_parts,
            normalized_filename=normalized_filename,
            application=application,
        )
    ]

    custom_match = _find_custom_location(raw_path, custom_location_list)
    if custom_match is not None:
        conflicting_descendants = _find_conflicting_descendant_locations(
            raw_path, custom_match, custom_location_list
        )
        if conflicting_descendants:
            nested_paths = ", ".join(location.path for location in conflicting_descendants[:3])
            involved_applications = {
                custom_match.application,
                *(location.application for location in conflicting_descendants),
            }
            mixed_application = (
                custom_match.application
                if len(involved_applications) == 1
                else "複数のソフト"
            )
            return ClassificationResult(
                path=raw_path,
                application=mixed_application,
                category=DataCategory.MIXED,
                match_score=100,
                rule_id="custom_location:mixed_descendants",
                reason=(
                    "このフォルダには複数のカスタム分類が含まれています。"
                    f"配下の別分類登録: {nested_paths}"
                ),
                safety_note=_CATEGORY_SAFETY_NOTES[DataCategory.MIXED],
            )

        # A backup marker nested inside a registered cache folder remains a
        # backup candidate. Safety-related built-in rules take precedence.
        backup_rules = [
            rule for rule in matched_rules
            if rule.category == DataCategory.BACKUP
        ]
        if custom_match.category == "cache" and backup_rules:
            selected_backup_rule = max(
                backup_rules, key=lambda rule: (rule.priority, rule.match_score)
            )
            return ClassificationResult(
                path=raw_path,
                application=custom_match.application,
                category=DataCategory.BACKUP,
                match_score=selected_backup_rule.match_score,
                rule_id=f"backup_override:{selected_backup_rule.rule_id}",
                reason=(
                    "登録された保存先内ですが、バックアップを示す名前・拡張子が"
                    "見つかったため、バックアップ候補として扱いました。"
                ),
                safety_note=_CATEGORY_SAFETY_NOTES[DataCategory.BACKUP],
            )

        custom_category = (
            DataCategory.CACHE_CANDIDATE
            if custom_match.category == "cache"
            else DataCategory.BACKUP
        )
        category_label = "キャッシュ" if custom_match.category == "cache" else "バックアップ"
        return ClassificationResult(
            path=raw_path,
            application=custom_match.application,
            category=custom_category,
            match_score=100,
            rule_id=f"custom_location:{custom_match.id}",
            reason=(
                f"ユーザーが登録した{category_label}保存先と一致しました。"
                f"登録パス: {custom_match.path}"
            ),
            safety_note=_CATEGORY_SAFETY_NOTES[custom_category],
        )

    if not matched_rules:
        category = DataCategory.UNKNOWN
        return ClassificationResult(
            path=raw_path,
            application=application,
            category=category,
            match_score=0,
            rule_id="no_matching_rule",
            reason="既知のキャッシュ・自動保存・バックアップの命名規則に一致しません。",
            safety_note=_CATEGORY_SAFETY_NOTES[category],
        )

    selected_rule = max(matched_rules, key=lambda rule: (rule.priority, rule.match_score))
    return ClassificationResult(
        path=raw_path,
        application=application,
        category=selected_rule.category,
        match_score=selected_rule.match_score,
        rule_id=selected_rule.rule_id,
        reason=selected_rule.reason,
        safety_note=_CATEGORY_SAFETY_NOTES[selected_rule.category],
    )
