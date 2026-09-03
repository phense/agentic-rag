"""Recoverable installation of Codex continuity configuration and hooks."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import uuid
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Callable

from .config import FEATURE_VALUES, MEMORY_VALUES, ROOT_VALUES, merge_config
from .hooks import duplicate_herdr_commands, merge_hooks


Run = Callable[..., subprocess.CompletedProcess]
LOCAL_ONLY_VALIDATION = (
    "local parsing only; Codex runtime validation remains a rollout step"
)


@dataclass(frozen=True)
class CodexPaths:
    home: Path
    config_path: Path
    hooks_path: Path
    prompt_path: Path

    @classmethod
    def for_home(cls, home: Path) -> CodexPaths:
        home = Path(home)
        codex_home = home / ".codex"
        return cls(
            home=home,
            config_path=codex_home / "config.toml",
            hooks_path=codex_home / "hooks.json",
            prompt_path=codex_home / "compact_prompt.md",
        )

    @property
    def targets(self) -> tuple[Path, Path, Path]:
        return self.config_path, self.hooks_path, self.prompt_path


@dataclass(frozen=True)
class BackupRecord:
    target_path: Path
    backup_path: Path


@dataclass(frozen=True)
class CodexInstallReport:
    paths: CodexPaths
    changed_paths: tuple[Path, ...]
    backups: tuple[BackupRecord, ...]
    created_paths: tuple[Path, ...]
    foreign_hook_duplicates: tuple[str, ...]
    check: bool
    codex_version: str | None
    runtime_validation: str


def _read_optional(path: Path, default: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default


def _prompt_text() -> str:
    return resources.files("assets").joinpath(
        "codex", "compact_prompt.md"
    ).read_text(encoding="utf-8")


def _toml_override(key: str, value: object) -> str:
    if isinstance(value, bool):
        literal = "true" if value else "false"
    elif isinstance(value, str):
        literal = json.dumps(value)
    else:
        literal = str(value)
    return f"{key}={literal}"


def _probe_codex(
    paths: CodexPaths, *, run: Run
) -> tuple[str | None, str]:
    codex = shutil.which("codex") or "codex"
    options = {**ROOT_VALUES}
    options.update({f"features.{key}": value for key, value in FEATURE_VALUES.items()})
    options.update({f"memories.{key}": value for key, value in MEMORY_VALUES.items()})
    common = {"capture_output": True, "text": True}

    try:
        version_proc = run([codex, "--version"], **common)
    except OSError:
        return None, LOCAL_ONLY_VALIDATION
    version_text = (version_proc.stdout or version_proc.stderr or "").strip()
    version = (
        version_text.splitlines()[0]
        if version_proc.returncode == 0 and version_text
        else None
    )
    if version_proc.returncode != 0:
        return version, LOCAL_ONLY_VALIDATION

    try:
        help_proc = run([codex, "--help"], **common)
        app_server_help_proc = run([codex, "app-server", "--help"], **common)
    except OSError:
        return version, LOCAL_ONLY_VALIDATION
    supports_probe = (
        help_proc.returncode == 0
        and "--strict-config" in (help_proc.stdout or "")
        and app_server_help_proc.returncode == 0
        and "--strict-config" in (app_server_help_proc.stdout or "")
        and "--listen" in (app_server_help_proc.stdout or "")
    )
    if not supports_probe:
        return version, LOCAL_ONLY_VALIDATION

    # A clean temporary CODEX_HOME makes this a strict probe of only the keys
    # managed here, without rejecting preserved future/foreign user settings.
    with tempfile.TemporaryDirectory(prefix="agentic-rag-codex-validate-") as probe_home:
        probe_prompt = Path(probe_home) / "compact_prompt.md"
        probe_prompt.write_text(_prompt_text(), encoding="utf-8")
        probe_options = {
            **options,
            "experimental_compact_prompt_file": str(probe_prompt),
        }
        command = [codex, "app-server", "--strict-config", "--listen", "stdio://"]
        for key, value in probe_options.items():
            command.extend(["--config", _toml_override(key, value)])
        env = dict(os.environ)
        env["CODEX_HOME"] = probe_home
        try:
            probe = run(command, env=env, input="", **common)
        except OSError:
            return version, LOCAL_ONLY_VALIDATION
    if probe.returncode != 0:
        detail = (probe.stderr or probe.stdout or "Codex rejected the configuration").strip()
        if "--strict-config" in detail and "not supported" in detail:
            return version, LOCAL_ONLY_VALIDATION
        raise RuntimeError(f"Codex managed configuration validation failed: {detail[:500]}")
    return version, "managed configuration validated"


def _desired_texts(paths: CodexPaths, *, python: str) -> tuple[dict[Path, str], tuple[str, ...]]:
    config_source = _read_optional(paths.config_path, "")
    hooks_source = _read_optional(paths.hooks_path, "")
    try:
        config_text = merge_config(config_source, home=paths.home)
    except Exception as exc:
        raise RuntimeError(f"{paths.config_path} is not valid Codex TOML: {exc}") from exc
    try:
        hooks_data = json.loads(hooks_source) if hooks_source.strip() else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{paths.hooks_path} is not valid JSON: {exc}") from exc
    if not isinstance(hooks_data, dict):
        raise RuntimeError(
            f"{paths.hooks_path} is not valid Codex hooks JSON: "
            "root must be an object"
        )
    duplicates = duplicate_herdr_commands(hooks_data)
    try:
        hooks_text = json.dumps(merge_hooks(hooks_data, python), indent=2) + "\n"
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{paths.hooks_path} is not valid Codex hooks JSON: {exc}") from exc
    return {
        paths.config_path: config_text,
        paths.hooks_path: hooks_text,
        paths.prompt_path: _prompt_text(),
    }, duplicates


def _stage_text(path: Path, text: str) -> Path:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(descriptor)
    staged = Path(name)
    try:
        staged.write_text(text, encoding="utf-8")
        if path.exists():
            staged.chmod(path.stat().st_mode)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    return staged


def _validate_stages(staged: dict[Path, Path], paths: CodexPaths) -> None:
    tomllib.loads(staged[paths.config_path].read_text(encoding="utf-8"))
    hooks = json.loads(staged[paths.hooks_path].read_text(encoding="utf-8"))
    if not isinstance(hooks, dict):
        raise ValueError("staged hooks JSON root must be an object")
    if not staged[paths.prompt_path].read_text(encoding="utf-8").strip():
        raise ValueError("staged compact prompt is empty")


def _cleanup_stages(staged: dict[Path, Path]) -> None:
    for path in staged.values():
        path.unlink(missing_ok=True)


def _backup_changed(changed: tuple[Path, ...]) -> tuple[BackupRecord, ...]:
    transaction = uuid.uuid4().hex
    records = []
    for target in changed:
        if target.exists():
            backup = target.with_name(f"{target.name}.bak.{transaction}")
            shutil.copy2(target, backup)
            records.append(BackupRecord(target, backup))
    return tuple(records)


def _rollback_replacements(
    changed: tuple[Path, ...], backups: tuple[BackupRecord, ...]
) -> None:
    by_target = {record.target_path: record.backup_path for record in backups}
    errors = []
    for target in changed:
        try:
            backup = by_target.get(target)
            if backup is None:
                target.unlink(missing_ok=True)
            else:
                shutil.copy2(backup, target)
        except OSError as exc:
            errors.append(f"{target}: {exc}")
    if errors:
        raise RuntimeError(
            "Codex installation failed and automatic rollback was incomplete; "
            f"recover from retained backups ({'; '.join(errors)})"
        )


def install_codex(
    paths: CodexPaths, *, check: bool = False, run: Run = subprocess.run
) -> CodexInstallReport:
    """Plan or install all Codex-owned artifacts as one recoverable transaction."""
    desired, duplicates = _desired_texts(paths, python=sys.executable)
    changed = tuple(
        path
        for path in paths.targets
        if not path.exists() or _read_optional(path, "") != desired[path]
    )
    version, validation = _probe_codex(paths, run=run)
    if check or not changed:
        return CodexInstallReport(
            paths, changed, (), tuple(path for path in changed if not path.exists()),
            duplicates, check, version, validation
        )

    for parent in {path.parent for path in paths.targets}:
        parent.mkdir(parents=True, exist_ok=True)
    staged: dict[Path, Path] = {}
    try:
        for path in paths.targets:
            staged[path] = _stage_text(path, desired[path])
        _validate_stages(staged, paths)
    except BaseException:
        _cleanup_stages(staged)
        raise

    try:
        backups = _backup_changed(changed)
    except BaseException:
        _cleanup_stages(staged)
        raise
    created = tuple(path for path in changed if not path.exists())
    try:
        for target in changed:
            os.replace(staged[target], target)
    except BaseException:
        try:
            _rollback_replacements(changed, backups)
        finally:
            _cleanup_stages(staged)
        raise
    _cleanup_stages(staged)

    return CodexInstallReport(
        paths, changed, backups, created, duplicates, False, version, validation
    )


def restore_codex(report: CodexInstallReport) -> tuple[Path, ...]:
    """Restore a completed transaction using its retained recovery records."""
    by_target = {record.target_path: record.backup_path for record in report.backups}
    for target in reversed(report.changed_paths):
        backup = by_target.get(target)
        if backup is None:
            if target in report.created_paths:
                target.unlink(missing_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = _stage_text(target, backup.read_text(encoding="utf-8"))
        os.replace(staged, target)
    return report.changed_paths
