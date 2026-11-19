"""Read-only discovery of known DCC cache and backup locations.

The discovery layer only reads documented configuration artifacts. It never
modifies DCC preferences and never changes, moves, or deletes user data.
"""

from __future__ import annotations

import json
import os
import ntpath
import posixpath
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True, slots=True)
class DiscoveryCandidate:
    """One possible DCC data location discovered from configuration evidence."""

    application: str
    category: str | None
    path: str | None
    status: str
    source: str
    explanation: str
    registerable: bool
    path_exists: bool | None


class DccLocationDiscovery:
    """Discover locations from app-specific config files and helper reports.

    This is deliberately conservative:
    - Maya's effective Autosave path is queried inside Maya by a helper script.
    - ZBrush paths are read from its documented path text files and known folders.
    - After Effects preference files are located, but their internal keys are
      not parsed because Adobe does not document a stable cache-path key and
      warns against manually editing preference files.
    """

    MAYA_REPORT_RELATIVE = Path("DCCStorageManager") / "discovery" / "maya_autosave.json"

    def __init__(
        self,
        *,
        appdata: str | os.PathLike[str] | None = None,
        public_documents: str | os.PathLike[str] | None = None,
        documents: str | os.PathLike[str] | None = None,
        user_profile: str | os.PathLike[str] | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._environment = dict(os.environ if environment is None else environment)
        self._appdata = Path(appdata) if appdata is not None else self._default_appdata()
        self._public_documents = (
            Path(public_documents)
            if public_documents is not None
            else self._default_public_documents()
        )
        self._user_profile = (
            Path(user_profile)
            if user_profile is not None
            else self._default_user_profile()
        )
        self._documents = (
            Path(documents)
            if documents is not None
            else self._user_profile / "Documents"
        )

    def discover(self) -> tuple[DiscoveryCandidate, ...]:
        """Return candidates ordered by application and then source path."""
        candidates: list[DiscoveryCandidate] = []
        candidates.extend(self._discover_maya())
        candidates.extend(self._discover_after_effects())
        candidates.extend(self._discover_zbrush())
        return self._deduplicate(candidates)

    def _discover_maya(self) -> list[DiscoveryCandidate]:
        report_path = self._appdata / self.MAYA_REPORT_RELATIVE
        if report_path.is_file():
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
                if (
                    not isinstance(report, dict)
                    or report.get("version") != 1
                    or report.get("application") != "Maya"
                ):
                    raise ValueError("unsupported report format or application")
                raw_path = report.get("path")
                enabled = report.get("enabled")
                if not isinstance(enabled, bool):
                    raise ValueError("enabled must be boolean")
                if not isinstance(raw_path, str) or not raw_path.strip():
                    raise ValueError("path is missing")
                if not self._is_absolute_path(raw_path):
                    raise ValueError("path must be absolute")

                path = self._expand_path(raw_path)
                exists = self._path_exists(path)
                generated_at = report.get("generated_at", "")
                stale = self._is_report_stale(generated_at)

                if not enabled:
                    return [
                        DiscoveryCandidate(
                            application="Maya",
                            category="backup",
                            path=path,
                            status="自動保存は無効",
                            source="Maya Python API: cmds.autoSave",
                            explanation=(
                                "Mayaから保存先は取得できましたが、自動保存が無効です。"
                                "現在の有効な保存先としては登録しないでください。"
                            ),
                            registerable=False,
                            path_exists=exists,
                        )
                    ]

                if stale:
                    status = "照会結果が古い（再取得推奨）"
                    explanation = (
                        "Mayaから取得した保存先レポートが30日以上前です。"
                        "Maya内でヘルパースクリプトを再実行してください。"
                    )
                    registerable = False
                elif exists:
                    status = "設定から検出・フォルダ確認済み"
                    explanation = (
                        "MayaのautoSaveコマンドが返した実際のAutosave保存先です。"
                        "この場所は復元用データなのでバックアップ候補として扱います。"
                    )
                    registerable = True
                else:
                    status = "設定から検出・現在アクセス不可"
                    explanation = (
                        "Mayaの設定上の保存先を取得しましたが、現在フォルダにアクセスできません。"
                        "外付けドライブが未接続の可能性があります。登録前に場所を確認してください。"
                    )
                    registerable = True

                return [
                    DiscoveryCandidate(
                        application="Maya",
                        category="backup",
                        path=path,
                        status=status,
                        source="Maya Python API: cmds.autoSave(q=True, destinationFolder=True)",
                        explanation=explanation,
                        registerable=registerable,
                        path_exists=exists,
                    )
                ]
            except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
                return [
                    DiscoveryCandidate(
                        application="Maya",
                        category=None,
                        path=str(report_path),
                        status="照会レポートを読み取れません",
                        source="DCCStorageManager Maya helper report",
                        explanation=f"レポートの形式または読み込みに問題があります: {exc}",
                        registerable=False,
                        path_exists=True,
                    )
                ]

        env_path = self._environment.get("MAYA_AUTOSAVE_FOLDER", "").strip()
        if env_path:
            expanded = self._expand_path(env_path)
            exists = self._path_exists(expanded)
            return [
                DiscoveryCandidate(
                    application="Maya",
                    category="backup",
                    path=expanded,
                    status="環境変数を検出（Maya側設定の確認が必要）",
                    source="MAYA_AUTOSAVE_FOLDER",
                    explanation=(
                        "環境変数は検出されました。ただしMayaが環境変数方式を選択しているかは"
                        "別途確認が必要です。Maya内で付属ヘルパーを実行すると実際の保存先を照会できます。"
                    ),
                    # The environment variable is only a clue. Maya may not
                    # currently be using this override, so require a fresh
                    # query from Maya's own autoSave command before registration.
                    registerable=False,
                    path_exists=exists,
                )
            ]

        maya_prefs_root = self._documents / "maya"
        versions = sorted(
            (item for item in maya_prefs_root.glob("*") if item.is_dir()),
            key=lambda item: item.name,
        ) if maya_prefs_root.is_dir() else []
        if versions:
            version_text = ", ".join(item.name for item in versions)
            explanation = (
                f"Mayaのユーザー設定フォルダ（{version_text}）を検出しました。"
                "Autosaveの実際の保存先はMayaのautoSave APIで照会する必要があります。"
                "付属の scripts/maya_query_autosave.py をMayaのScript Editorで実行してください。"
            )
            status = "Maya内で保存先を照会してください"
        else:
            explanation = (
                "Mayaの設定フォルダも照会レポートも見つかりませんでした。"
                "Mayaが未インストール、別ユーザープロファイル、または独自設定の可能性があります。"
            )
            status = "Mayaの設定情報を検出できません"

        return [
            DiscoveryCandidate(
                application="Maya",
                category=None,
                path=None,
                status=status,
                source="Documents/maya と Maya helper report",
                explanation=explanation,
                registerable=False,
                path_exists=None,
            )
        ]

    def _discover_after_effects(self) -> list[DiscoveryCandidate]:
        preference_roots = (
            self._appdata / "Adobe" / "After Effects",
            self._documents / "Adobe" / "After Effects",
        )
        found: list[Path] = []
        for root in preference_roots:
            if root.is_dir():
                found.extend(item for item in root.iterdir() if item.is_dir())

        if found:
            versions = ", ".join(sorted({item.name for item in found}))
            status = "設定フォルダを検出・保存先は手動確認"
            explanation = (
                f"After Effectsの環境設定フォルダ（{versions}）を検出しました。"
                "Adobeが案内するDisk CacheとMedia Cacheの保存先は、After Effectsの"
                "環境設定 > ディスクから確認してください。設定ファイル内の非公開キーは解析しません。"
            )
            source = "Adobe After Effects preferences directory"
        else:
            status = "設定フォルダを検出できません"
            explanation = (
                "After Effectsの環境設定フォルダが見つかりませんでした。"
                "インストール状況やWindowsユーザーを確認してください。"
            )
            source = "AppData/Roaming/Adobe/After Effects"

        return [
            DiscoveryCandidate(
                application="After Effects",
                category=None,
                path=None,
                status=status,
                source=source,
                explanation=explanation,
                registerable=False,
                path_exists=None,
            )
        ]

    def _discover_zbrush(self) -> list[DiscoveryCandidate]:
        candidates: list[DiscoveryCandidate] = []

        # Maxon documents ZBRUSH_USER_ASSETS_DIR as an override for the
        # user-asset root. Search it first, but do not register the root itself:
        # only the specific QuickSave/Scratch Disk locations are actionable.
        configured_assets = self._environment.get("ZBRUSH_USER_ASSETS_DIR", "").strip()
        asset_dirs: list[tuple[Path, str]] = []
        if configured_assets:
            configured_root = Path(self._expand_path(configured_assets))
            if configured_root.is_dir():
                candidates.append(
                    DiscoveryCandidate(
                        application="ZBrush",
                        category=None,
                        path=str(configured_root),
                        status="ユーザーアセットルートを検出",
                        source="ZBRUSH_USER_ASSETS_DIR",
                        explanation=(
                            "Maxonの環境変数で指定されたZBrushユーザーアセットルートです。"
                            "ルート全体は登録せず、この中のQuickSaveやScratch Diskなど個別の保存先を調査します。"
                        ),
                        registerable=False,
                        path_exists=True,
                    )
                )
                asset_dirs.append((configured_root, "ZBRUSH_USER_ASSETS_DIR"))
            else:
                candidates.append(
                    DiscoveryCandidate(
                        application="ZBrush",
                        category=None,
                        path=str(configured_root),
                        status="環境変数の保存先にアクセスできません",
                        source="ZBRUSH_USER_ASSETS_DIR",
                        explanation=(
                            "環境変数は設定されていますが、現在そのフォルダにアクセスできません。"
                            "共有ドライブまたは外付けドライブが接続されているか確認してください。"
                        ),
                        registerable=False,
                        path_exists=False,
                    )
                )

        # The environment variable is an explicit override. Do not also label
        # the default AppData location as active in that case; it may be stale.
        if not configured_assets:
            user_asset_root = self._appdata / "Maxon"
            if user_asset_root.is_dir():
                for asset_dir in sorted(user_asset_root.glob("ZBrush_*")):
                    if asset_dir.is_dir():
                        asset_dirs.append((asset_dir, "ZBrush 2026.1+ user asset directory"))

        seen_asset_dirs: set[str] = set()
        for asset_dir, asset_source in asset_dirs:
            normalized_asset_dir = os.path.normcase(os.path.abspath(asset_dir))
            if normalized_asset_dir in seen_asset_dirs:
                continue
            seen_asset_dirs.add(normalized_asset_dir)
            candidates.extend(
                self._discover_zbrush_config_files(
                    asset_dir,
                    source_prefix=asset_source,
                )
            )
            # If ZBrush provides an explicit QuickSave path file, treat it as
            # authoritative. Do not also guess that the adjacent default folder
            # is active: it may be a stale folder left behind after relocation.
            has_quicksave_path_config = (asset_dir / "ZBrushQuickSavePath.txt").is_file()
            if not has_quicksave_path_config:
                for folder_name in ("QuickSave", "QuickSaves"):
                    folder = asset_dir / folder_name
                    if folder.is_dir():
                        candidates.append(
                            self._make_path_candidate(
                                application="ZBrush",
                                category="backup",
                                path=str(folder),
                                source=asset_source,
                                explanation=(
                                    "ZBrushのユーザーアセットディレクトリ内にあるQuickSaveフォルダです。"
                                    "復元用データの可能性があるためバックアップ候補として扱います。"
                                ),
                            )
                        )

        if self._public_documents.is_dir():
            for legacy_dir in sorted(self._public_documents.glob("ZBrushData*")):
                if not legacy_dir.is_dir():
                    continue
                candidates.extend(self._discover_zbrush_config_files(legacy_dir))
                # As with modern user-asset directories, an explicit path file
                # takes precedence over an inferred adjacent default folder.
                has_quicksave_path_config = (legacy_dir / "ZBrushQuickSavePath.txt").is_file()
                if not has_quicksave_path_config:
                    for folder_name in ("QuickSave", "QuickSaves"):
                        folder = legacy_dir / folder_name
                        if folder.is_dir():
                            candidates.append(
                                self._make_path_candidate(
                                    application="ZBrush",
                                    category="backup",
                                    path=str(folder),
                                    source="ZBrush legacy Public Documents directory",
                                    explanation=(
                                        "旧形式のZBrushDataディレクトリ内にQuickSaveフォルダがあります。"
                                        "旧バージョンの保存データとして確認してください。"
                                    ),
                                )
                            )

        if not candidates:
            return [
                DiscoveryCandidate(
                    application="ZBrush",
                    category=None,
                    path=None,
                    status="QuickSave設定を検出できません",
                    source="Maxon user asset and legacy data directories",
                    explanation=(
                        "既知のZBrushユーザーアセット／旧データディレクトリに"
                        "QuickSaveや保存先設定ファイルが見つかりませんでした。"
                        "ZBrushのバージョンとPreferences > Asset Directoryを確認してください。"
                    ),
                    registerable=False,
                    path_exists=None,
                )
            ]
        return candidates

    def _discover_zbrush_config_files(
        self, base_dir: Path, *, source_prefix: str = ""
    ) -> list[DiscoveryCandidate]:
        candidates: list[DiscoveryCandidate] = []
        config_specs = (
            (
                "ZBrushQuickSavePath.txt",
                "backup",
                "ZBrushQuickSavePath.txt",
                "QuickSave保存先を指定する設定ファイルです。",
            ),
            (
                "ZBrushScratchDiskPath.txt",
                "cache",
                "ZBrushScratchDiskPath.txt",
                "Scratch Disk保存先を指定する設定ファイルです。",
            ),
        )
        for filename, category, source, description in config_specs:
            config_file = base_dir / filename
            if not config_file.is_file():
                continue
            try:
                configured_path = self._read_path_file(config_file)
            except OSError as exc:
                candidates.append(
                    DiscoveryCandidate(
                        application="ZBrush",
                        category=None,
                        path=str(config_file),
                        status="設定ファイルを読み取れません",
                        source=source,
                        explanation=f"設定ファイルの読み込みに失敗しました: {exc}",
                        registerable=False,
                        path_exists=True,
                    )
                )
                continue

            if not configured_path or not self._is_absolute_path(configured_path):
                candidates.append(
                    DiscoveryCandidate(
                        application="ZBrush",
                        category=None,
                        path=str(config_file),
                        status="設定値が空または絶対パスではありません",
                        source=source,
                        explanation="設定ファイルに有効な絶対パスが記録されていません。",
                        registerable=False,
                        path_exists=True,
                    )
                )
                continue

            candidates.append(
                self._make_path_candidate(
                    application="ZBrush",
                    category=category,
                    path=configured_path,
                    source=(f"{source_prefix}: {source}" if source_prefix else source),
                    explanation=f"{description} {base_dir.name}内の設定ファイルから読み取りました。",
                )
            )
        return candidates

    def _make_path_candidate(
        self,
        *,
        application: str,
        category: str,
        path: str,
        source: str,
        explanation: str,
    ) -> DiscoveryCandidate:
        expanded = self._expand_path(path)
        exists = self._path_exists(expanded)
        if exists:
            status = "設定から検出・フォルダ確認済み"
        else:
            status = "設定から検出・現在アクセス不可"
            explanation += " 保存先が外付けドライブの場合は、ドライブが未接続の可能性があります。"
        return DiscoveryCandidate(
            application=application,
            category=category,
            path=expanded,
            status=status,
            source=source,
            explanation=explanation,
            registerable=True,
            path_exists=exists,
        )

    @staticmethod
    def _read_path_file(path: Path) -> str:
        data: str | None = None
        errors: list[UnicodeError] = []
        for encoding in ("utf-8-sig", "utf-16", "cp1252"):
            try:
                data = path.read_text(encoding=encoding)
                break
            except UnicodeError as exc:
                errors.append(exc)
        if data is None:
            raise OSError(f"unsupported text encoding: {errors[-1] if errors else 'unknown'}")

        for line in data.splitlines():
            value = line.strip().strip('"').strip()
            if value:
                return value
        return ""

    @staticmethod
    def _is_absolute_path(path: str) -> bool:
        value = path.strip()
        return (
            ntpath.isabs(value)
            or posixpath.isabs(value)
        )

    def _expand_path(self, path: str) -> str:
        value = os.path.expandvars(path.strip()).strip().strip('"')
        if value.startswith("~"):
            value = os.path.expanduser(value)
        if ntpath.isabs(value):
            return ntpath.normpath(value)
        return str(Path(value).expanduser())

    @staticmethod
    def _path_exists(path: str) -> bool:
        try:
            return Path(path).is_dir()
        except (OSError, ValueError):
            return False

    @staticmethod
    def _is_report_stale(generated_at: object) -> bool:
        if not isinstance(generated_at, str) or not generated_at:
            return True
        try:
            value = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - value.astimezone(timezone.utc)
            return age.total_seconds() > 30 * 24 * 60 * 60
        except ValueError:
            return True

    @staticmethod
    def _default_appdata() -> Path:
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))

    @staticmethod
    def _default_user_profile() -> Path:
        return Path(os.environ.get("USERPROFILE", Path.home()))

    @staticmethod
    def _default_public_documents() -> Path:
        public_root = os.environ.get("PUBLIC")
        if public_root:
            return Path(public_root) / "Documents"
        return Path("C:/Users/Public/Documents")

    @staticmethod
    def _deduplicate(
        candidates: list[DiscoveryCandidate],
    ) -> tuple[DiscoveryCandidate, ...]:
        seen: set[tuple[str, str, str]] = set()
        result: list[DiscoveryCandidate] = []
        for candidate in candidates:
            if candidate.path:
                path = candidate.path
                if ntpath.isabs(path) and ("\\" in path or (len(path) > 1 and path[1] == ":")):
                    key_path = ntpath.normcase(ntpath.normpath(path))
                else:
                    key_path = os.path.normcase(os.path.abspath(path))
            else:
                key_path = candidate.status
            key = (candidate.application, candidate.category or "", key_path)
            if key in seen:
                continue
            seen.add(key)
            result.append(candidate)
        return tuple(result)
