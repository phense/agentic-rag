"""Recoverable installation of the Antigravity CLI hook into ``hooks.json``.

One target file (``~/.gemini/config/hooks.json``, shared by the Antigravity
CLI, IDE, and desktop app), staged in place, published atomically, backed up
uniquely, and identity-bound for restore.  The Codex installer's
snapshot/stage/backup primitives are reused, exactly as the Claude adapter
does, so all three targets share one notion of "changed concurrently".
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from ..codex.install import (
    BackupRecord,
    FileSnapshot,
    InstalledFile,
    _backup_changed,
    _snapshot,
    _stage_text,
)
from .hooks import merge_hooks, owned_commands

LABEL = "Antigravity hooks"
DEFAULT_HOOKS_PATH = Path("~/.gemini/config/hooks.json")


def hooks_path_for_home(home: Path | None = None) -> Path:
    base = Path.home() if home is None else Path(home)
    return base / ".gemini" / "config" / "hooks.json"


@dataclass(frozen=True)
class AgyInstallReport:
    hooks_path: Path
    check: bool
    changed: bool
    backup: BackupRecord | None
    installed: InstalledFile | None
    commands: tuple[str, ...]
    warnings: tuple[str, ...]


def _load(snapshot: FileSnapshot, path: Path) -> dict:
    if not snapshot.identity.exists or not snapshot.content.strip():
        return {}
    try:
        data = json.loads(snapshot.content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"{path} is not valid JSON ({exc}) — fix it or move it aside, "
            "then re-run rag install --agy"
        ) from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"{path} is not valid JSON: root must be an object")
    return data


def _render(data: dict) -> str:
    return json.dumps(data, indent=2) + "\n"


def _warnings(hooks_path: Path) -> tuple[str, ...]:
    warnings: list[str] = []
    app_dir = hooks_path.parent.parent / "antigravity-cli"
    if not app_dir.is_dir():
        warnings.append(
            f"{app_dir} not found; the Antigravity CLI has not run on this "
            "machine yet — hooks load once `agy` starts")
    return tuple(warnings)


def install_agy(
    hooks_path: Path, *, python: str, check: bool = False,
) -> AgyInstallReport:
    hooks_path = Path(os.path.abspath(Path(hooks_path).expanduser()))
    snapshot = _snapshot(hooks_path, label=LABEL)
    current = _load(snapshot, hooks_path)
    merged = merge_hooks(current, python)
    desired = _render(merged)
    changed = not snapshot.identity.exists or desired != snapshot.content.decode(
        "utf-8", errors="replace")
    commands = owned_commands(merged)
    warnings = _warnings(hooks_path)
    if check or not changed:
        return AgyInstallReport(
            hooks_path, check, changed, None, None, commands, warnings)

    hooks_path.parent.mkdir(parents=True, exist_ok=True)
    backups = _backup_changed((hooks_path,), {hooks_path: snapshot})
    backup = backups[0] if backups else None
    staged = _stage_text(hooks_path, desired)
    try:
        if _snapshot(hooks_path, label=LABEL).identity != snapshot.identity:
            raise RuntimeError(f"{LABEL} file changed concurrently: {hooks_path}")
        os.replace(staged, hooks_path)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    installed = InstalledFile(
        hooks_path, _snapshot(hooks_path, label=LABEL).identity)
    return AgyInstallReport(
        hooks_path, False, True, backup, installed, commands, warnings)


def restore_agy(
    hooks_path: Path,
    backup: BackupRecord | None,
    installed: InstalledFile,
) -> tuple[Path, ...]:
    """Put the recorded backup back only if nothing drifted since install."""
    hooks_path = Path(hooks_path)
    live = _snapshot(hooks_path, label=LABEL)
    if live.identity != installed.identity:
        raise RuntimeError(
            f"{hooks_path} changed since installation; refusing to overwrite "
            "— compare it with the backup and restore by hand"
        )
    if backup is None:
        hooks_path.unlink()
        return (hooks_path,)
    saved = _snapshot(backup.backup_path, label=LABEL)
    if backup.identity is None or saved.identity != backup.identity:
        raise RuntimeError(
            f"backup changed since installation: {backup.backup_path}")
    staged = _stage_text(hooks_path, saved.content.decode("utf-8"))
    try:
        if _snapshot(hooks_path, label=LABEL).identity != installed.identity:
            raise RuntimeError(f"{LABEL} file changed concurrently: {hooks_path}")
        os.replace(staged, hooks_path)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    return (hooks_path,)
