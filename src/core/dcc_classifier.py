"""Conservative, read-only classifier for common DCC cache/backup paths.

This module labels candidates only. It never deletes, moves, or modifies data.
A classification is not proof that an item is safe to delete.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath, PureWindowsPath
from typing import TypeAlias

PathLike: TypeAlias = str | os.PathLike[str]


class DataCategory(str, Enum):
    """High-level data categories used by the cleanup review UI."""

    CACHE_CANDIDATE = "キャッシュ候補"
    BACKUP = "バックアップ候補"
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


def classify_path(path: PathLike) -> ClassificationResult:
    """Classify a path using conservative names and path signatures.

    The function does not inspect file contents, access the filesystem, or
    infer that an item is safe to delete. Custom cache locations whose names do
    not contain recognizable markers will be returned as UNKNOWN.
    """
    try:
        raw_path_value = os.fspath(path)
    except TypeError as exc:
        raise ValueError("path must be a non-empty string or Path") from exc
    if not isinstance(raw_path_value, str) or not raw_path_value.strip():
        raise ValueError("path must be a non-empty string or Path")

    raw_path = raw_path_value.strip()
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
