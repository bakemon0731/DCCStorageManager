"""Run this script inside Maya's Script Editor (Python tab).

It queries Maya's effective Autosave destination through the documented
maya.cmds.autoSave command and writes a read-only report for DCC Storage
Manager. It does not change Maya preferences or touch saved scene files.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import maya.cmds as cmds


def main() -> Path:
    enabled = bool(cmds.autoSave(query=True, enable=True))
    destination = cmds.autoSave(query=True, destinationFolder=True)
    if not isinstance(destination, str) or not destination.strip():
        raise RuntimeError("MayaからAutosave保存先を取得できませんでした。")

    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA環境変数を取得できませんでした。")

    output_dir = Path(appdata) / "DCCStorageManager" / "discovery"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "maya_autosave.json"
    temporary_path = output_path.with_suffix(".json.tmp")

    report = {
        "version": 1,
        "application": "Maya",
        "maya_version": cmds.about(version=True),
        "enabled": enabled,
        "path": os.path.normpath(destination.strip()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "maya.cmds.autoSave(query=True, destinationFolder=True)",
    }

    with temporary_path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary_path, output_path)
    print("DCC Storage Manager: Maya Autosave report saved:", output_path)
    print("Autosave enabled:", enabled)
    print("Autosave destination:", destination)
    return output_path


main()
