"""Recoverable installation of Codex continuity configuration and hooks."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
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
from .hooks import ForeignHookDuplicate, duplicate_herdr_commands, merge_hooks


Run = Callable[..., subprocess.CompletedProcess]
LOCAL_ONLY_VALIDATION = (
    "local parsing only; Codex runtime validation remains a rollout step"
)
PROBE_ISOLATION = (
    "every Codex subprocess used an ephemeral isolated CODEX_HOME with a "
    "10-second timeout; probe files were removed and no target files were written"
)
PROBE_TIMEOUT_SECONDS = 10


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
class FileIdentity:
    exists: bool
    device: int | None = None
    inode: int | None = None
    size: int | None = None
    modified_ns: int | None = None
    digest: str | None = None
    mode: int | None = None


@dataclass(frozen=True)
class FileSnapshot:
    identity: FileIdentity
    content: bytes


@dataclass(frozen=True)
class Replacement:
    target_path: Path
    installed_identity: FileIdentity


@dataclass(frozen=True)
class CodexInstallReport:
    paths: CodexPaths
    changed_paths: tuple[Path, ...]
    backups: tuple[BackupRecord, ...]
    created_paths: tuple[Path, ...]
    foreign_hook_duplicates: tuple[ForeignHookDuplicate, ...]
    check: bool
    codex_version: str | None
    runtime_validation: str
    probe_isolation: str


def _snapshot(path: Path) -> FileSnapshot:
    """Read a stable regular-file snapshot without following a leaf symlink."""
    try:
        before = path.lstat()
    except FileNotFoundError:
        return FileSnapshot(FileIdentity(False), b"")
    if stat.S_ISLNK(before.st_mode):
        raise RuntimeError(f"refusing Codex leaf symbolic link: {path}")
    if not stat.S_ISREG(before.st_mode):
        raise RuntimeError(f"refusing non-regular Codex file: {path}")
    content = path.read_bytes()
    try:
        after = path.lstat()
    except FileNotFoundError as exc:
        raise RuntimeError(f"Codex file changed concurrently: {path}") from exc
    stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_mode")
    if any(getattr(before, field) != getattr(after, field) for field in stable_fields):
        raise RuntimeError(f"Codex file changed concurrently: {path}")
    identity = FileIdentity(
        True,
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        hashlib.sha256(content).hexdigest(),
        stat.S_IMODE(after.st_mode),
    )
    return FileSnapshot(identity, content)


def _decode(snapshot: FileSnapshot, path: Path) -> str:
    try:
        return snapshot.content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"{path} is not valid UTF-8: {exc}") from exc


def _assert_identity(path: Path, expected: FileIdentity) -> None:
    if _snapshot(path).identity != expected:
        raise RuntimeError(f"Codex file changed concurrently: {path}")


def _assert_snapshots_unchanged(snapshots: dict[Path, FileSnapshot]) -> None:
    for path, snapshot in snapshots.items():
        _assert_identity(path, snapshot.identity)


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
    with tempfile.TemporaryDirectory(prefix="agentic-rag-codex-validate-") as probe_home:
        probe_prompt = Path(probe_home) / "compact_prompt.md"
        probe_prompt.write_text(_prompt_text(), encoding="utf-8")
        env = dict(os.environ)
        env["CODEX_HOME"] = probe_home
        common = {
            "capture_output": True,
            "text": True,
            "env": env,
            "timeout": PROBE_TIMEOUT_SECONDS,
        }
        try:
            version_proc = run([codex, "--version"], **common)
        except (OSError, subprocess.TimeoutExpired):
            return None, LOCAL_ONLY_VALIDATION
        version_text = (
            version_proc.stdout or version_proc.stderr or ""
        ).strip()
        version = (
            version_text.splitlines()[0]
            if version_proc.returncode == 0 and version_text
            else None
        )
        if version_proc.returncode != 0:
            return version, LOCAL_ONLY_VALIDATION

        try:
            help_proc = run([codex, "--help"], **common)
            app_server_help_proc = run(
                [codex, "app-server", "--help"], **common
            )
        except (OSError, subprocess.TimeoutExpired):
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

        # The clean temporary home strictly probes only managed keys without
        # rejecting preserved future/foreign settings in the user's config.
        probe_options = {
            **options,
            "experimental_compact_prompt_file": str(probe_prompt),
        }
        command = [codex, "app-server", "--strict-config", "--listen", "stdio://"]
        for key, value in probe_options.items():
            command.extend(["--config", _toml_override(key, value)])
        try:
            probe = run(command, input="", **common)
        except (OSError, subprocess.TimeoutExpired):
            return version, LOCAL_ONLY_VALIDATION
    if probe.returncode != 0:
        detail = (probe.stderr or probe.stdout or "Codex rejected the configuration").strip()
        if "--strict-config" in detail and "not supported" in detail:
            return version, LOCAL_ONLY_VALIDATION
        raise RuntimeError(f"Codex managed configuration validation failed: {detail[:500]}")
    return version, "managed configuration validated"


def _plan_install(
    paths: CodexPaths, *, python: str
) -> tuple[
    dict[Path, str],
    tuple[ForeignHookDuplicate, ...],
    dict[Path, FileSnapshot],
]:
    snapshots = {path: _snapshot(path) for path in paths.targets}
    config_source = _decode(snapshots[paths.config_path], paths.config_path)
    hooks_source = _decode(snapshots[paths.hooks_path], paths.hooks_path)
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
    return (
        {
            paths.config_path: config_text,
            paths.hooks_path: hooks_text,
            paths.prompt_path: _prompt_text(),
        },
        duplicates,
        snapshots,
    )


def _stage_bytes(path: Path, content: bytes, *, mode: int | None = None) -> Path:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(descriptor)
    staged = Path(name)
    try:
        staged.write_bytes(content)
        if mode is None and path.exists() and not path.is_symlink():
            mode = stat.S_IMODE(path.stat().st_mode)
        if mode is not None:
            staged.chmod(mode)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    return staged


def _stage_text(path: Path, text: str) -> Path:
    return _stage_bytes(path, text.encode("utf-8"))


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


def _backup_changed(
    changed: tuple[Path, ...], snapshots: dict[Path, FileSnapshot]
) -> tuple[BackupRecord, ...]:
    transaction = uuid.uuid4().hex
    records = []
    for target in changed:
        snapshot = snapshots[target]
        if snapshot.identity.exists:
            backup = target.with_name(f"{target.name}.bak.{transaction}")
            with backup.open("xb") as stream:
                stream.write(snapshot.content)
            if snapshot.identity.mode is not None:
                backup.chmod(snapshot.identity.mode)
            records.append(BackupRecord(target, backup))
    return tuple(records)


def _rollback_replacements(
    replacements: list[Replacement], backups: tuple[BackupRecord, ...]
) -> None:
    by_target = {record.target_path: record.backup_path for record in backups}
    errors = []
    for replacement in reversed(replacements):
        target = replacement.target_path
        try:
            _assert_identity(target, replacement.installed_identity)
            backup = by_target.get(target)
            if backup is None:
                target.unlink(missing_ok=True)
            else:
                backup_snapshot = _snapshot(backup)
                staged = _stage_bytes(
                    target,
                    backup_snapshot.content,
                    mode=backup_snapshot.identity.mode,
                )
                os.replace(staged, target)
        except (OSError, RuntimeError) as exc:
            errors.append(f"{target}: {exc}")
    if errors:
        raise RuntimeError(
            "Codex installation failed and concurrent edits prevented safe "
            "rollback; manual recovery required from retained backups "
            f"({'; '.join(errors)})"
        )


def install_codex(
    paths: CodexPaths, *, check: bool = False, run: Run = subprocess.run
) -> CodexInstallReport:
    """Plan or install all Codex-owned artifacts as one recoverable transaction."""
    desired, duplicates, snapshots = _plan_install(
        paths, python=sys.executable
    )
    changed = tuple(
        path
        for path in paths.targets
        if snapshots[path].content != desired[path].encode("utf-8")
    )
    version, validation = _probe_codex(paths, run=run)
    _assert_snapshots_unchanged(snapshots)
    if check or not changed:
        return CodexInstallReport(
            paths=paths,
            changed_paths=changed,
            backups=(),
            created_paths=tuple(
                path
                for path in changed
                if not snapshots[path].identity.exists
            ),
            foreign_hook_duplicates=duplicates,
            check=check,
            codex_version=version,
            runtime_validation=validation,
            probe_isolation=PROBE_ISOLATION,
        )

    for parent in {path.parent for path in paths.targets}:
        parent.mkdir(parents=True, exist_ok=True)
    staged: dict[Path, Path] = {}
    try:
        for path in paths.targets:
            staged[path] = _stage_text(path, desired[path])
        _validate_stages(staged, paths)
        _assert_snapshots_unchanged(snapshots)
    except BaseException:
        _cleanup_stages(staged)
        raise

    try:
        backups = _backup_changed(changed, snapshots)
    except BaseException:
        _cleanup_stages(staged)
        raise
    created = tuple(
        path for path in changed if not snapshots[path].identity.exists
    )
    replacements: list[Replacement] = []
    try:
        for target in changed:
            _assert_identity(target, snapshots[target].identity)
            installed_identity = _snapshot(staged[target]).identity
            os.replace(staged[target], target)
            replacements.append(Replacement(target, installed_identity))
            _assert_identity(target, installed_identity)
    except BaseException:
        try:
            _rollback_replacements(replacements, backups)
        finally:
            _cleanup_stages(staged)
        raise
    _cleanup_stages(staged)

    return CodexInstallReport(
        paths=paths,
        changed_paths=changed,
        backups=backups,
        created_paths=created,
        foreign_hook_duplicates=duplicates,
        check=False,
        codex_version=version,
        runtime_validation=validation,
        probe_isolation=PROBE_ISOLATION,
    )


def restore_codex(report: CodexInstallReport) -> tuple[Path, ...]:
    """Restore a completed transaction using its retained recovery records."""
    for target in report.changed_paths:
        _snapshot(target)
    by_target = {record.target_path: record.backup_path for record in report.backups}
    for target in reversed(report.changed_paths):
        backup = by_target.get(target)
        if backup is None:
            if target in report.created_paths:
                target.unlink(missing_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        backup_snapshot = _snapshot(backup)
        staged = _stage_bytes(
            target,
            backup_snapshot.content,
            mode=backup_snapshot.identity.mode,
        )
        os.replace(staged, target)
    return report.changed_paths
