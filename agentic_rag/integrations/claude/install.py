"""Recoverable installation of the Claude hook set and compaction policy.

One target file (``~/.claude/settings.json``), staged in place, published
atomically, backed up uniquely, and identity-bound for restore.  The Codex
installer's snapshot/stage/backup primitives are reused so both targets share
one notion of "changed concurrently".
"""
from __future__ import annotations

import json
import os
from collections.abc import Mapping
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
from .settings import managed_settings, merge_settings, policy_warnings

LABEL = "Claude settings"


@dataclass(frozen=True)
class ClaudeInstallReport:
    settings_path: Path
    check: bool
    changed: bool
    backup: BackupRecord | None
    installed: InstalledFile | None
    warnings: tuple[str, ...]
    managed: tuple[tuple[str, object], ...]


def _load(snapshot: FileSnapshot, path: Path) -> dict:
    if not snapshot.identity.exists or not snapshot.content.strip():
        return {}
    try:
        data = json.loads(snapshot.content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"{path} is not valid JSON ({exc}) — fix it or move it aside, "
            "then re-run rag install"
        ) from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"{path} is not valid JSON: root must be an object")
    return data


def _render(data: dict) -> str:
    return json.dumps(data, indent=2) + "\n"


def install_claude(
    settings_path: Path,
    *,
    python: str,
    check: bool = False,
    environ: Mapping[str, str] | None = None,
) -> ClaudeInstallReport:
    settings_path = Path(os.path.abspath(Path(settings_path).expanduser()))
    env = os.environ if environ is None else environ
    snapshot = _snapshot(settings_path, label=LABEL)
    current = _load(snapshot, settings_path)
    merged = merge_settings(current, python)
    desired = _render(merged)
    changed = not snapshot.identity.exists or desired != snapshot.content.decode(
        "utf-8", errors="replace")
    warnings = policy_warnings(merged, env)
    if check or not changed:
        return ClaudeInstallReport(
            settings_path, check, changed, None, None, warnings, managed_settings())

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    backups = _backup_changed((settings_path,), {settings_path: snapshot})
    backup = backups[0] if backups else None
    staged = _stage_text(settings_path, desired)
    try:
        if _snapshot(settings_path, label=LABEL).identity != snapshot.identity:
            raise RuntimeError(f"{LABEL} file changed concurrently: {settings_path}")
        os.replace(staged, settings_path)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    installed = InstalledFile(
        settings_path, _snapshot(settings_path, label=LABEL).identity)
    return ClaudeInstallReport(
        settings_path, False, True, backup, installed, warnings, managed_settings())


def restore_claude(
    settings_path: Path,
    backup: BackupRecord | None,
    installed: InstalledFile,
) -> tuple[Path, ...]:
    """Put the recorded backup back only if nothing drifted since install."""
    settings_path = Path(settings_path)
    live = _snapshot(settings_path, label=LABEL)
    if live.identity != installed.identity:
        raise RuntimeError(
            f"{settings_path} changed since installation; refusing to overwrite "
            "— compare it with the backup and restore by hand"
        )
    if backup is None:
        settings_path.unlink()
        return (settings_path,)
    saved = _snapshot(backup.backup_path, label=LABEL)
    if backup.identity is None or saved.identity != backup.identity:
        raise RuntimeError(
            f"backup changed since installation: {backup.backup_path}")
    staged = _stage_text(settings_path, saved.content.decode("utf-8"))
    try:
        if _snapshot(settings_path, label=LABEL).identity != installed.identity:
            raise RuntimeError(f"{LABEL} file changed concurrently: {settings_path}")
        os.replace(staged, settings_path)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    return (settings_path,)
