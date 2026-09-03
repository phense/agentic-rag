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

from agentic_rag.secrets import strip_secrets

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
    identity: FileIdentity | None = None


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
    displaced_path: Path | None


@dataclass(frozen=True)
class RestoreReplacement:
    target_path: Path
    restored_identity: FileIdentity | None
    installed_path: Path


@dataclass(frozen=True)
class InstalledFile:
    target_path: Path
    identity: FileIdentity


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
    installed_files: tuple[InstalledFile, ...]


class _RecoveryConflict(RuntimeError):
    def __init__(self, message: str, *recovery_paths: Path) -> None:
        super().__init__(message)
        self.recovery_paths = recovery_paths


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
        safe_detail = strip_secrets(detail)[0][:500]
        raise RuntimeError(
            f"Codex managed configuration validation failed: {safe_detail}"
        )
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


def _cleanup_stages(
    staged: dict[Path, Path], *, preserve: tuple[Path, ...] = ()
) -> None:
    preserved = set(preserve)
    for path in staged.values():
        if path not in preserved:
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
            records.append(BackupRecord(target, backup, _snapshot(backup).identity))
    return tuple(records)


def _entry_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _reserve_recovery_path(target: Path, label: str) -> Path:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{target.name}.{label}.", dir=target.parent
    )
    os.close(descriptor)
    return Path(name)


def _claim_entry(target: Path, displaced: Path) -> None:
    """Atomically move the current pathname into a reserved recovery entry."""
    os.replace(target, displaced)


def _publish_no_replace(source: Path, target: Path) -> None:
    """Atomically publish one same-filesystem entry only when target is absent."""
    os.link(source, target, follow_symlinks=False)


def _publish_detached_no_replace(source: Path, target: Path) -> FileIdentity:
    """Publish an independent copy and return its pre-publication identity."""
    source_snapshot = _snapshot(source)
    publication = _stage_bytes(
        target,
        source_snapshot.content,
        mode=source_snapshot.identity.mode,
    )
    try:
        published_identity = _snapshot(publication).identity
        _publish_no_replace(publication, target)
    finally:
        # The target keeps the publication inode after a successful link, while
        # the authenticated source remains detached from in-place target edits.
        publication.unlink(missing_ok=True)
    return published_identity


def _restore_captured(captured: Path, target: Path) -> bool:
    """Restore a claimed entry only if no concurrent target now exists."""
    try:
        _publish_no_replace(captured, target)
    except FileExistsError:
        return False
    captured.unlink()
    return True


def _retain_unpublished(staged: Path, target: Path) -> Path:
    recovery = _reserve_recovery_path(target, "unpublished")
    try:
        os.replace(staged, recovery)
    except BaseException:
        recovery.unlink(missing_ok=True)
        raise
    return recovery


def _claim_expected(
    target: Path, expected: FileIdentity, *, label: str
) -> Path:
    displaced = _reserve_recovery_path(target, label)
    try:
        _claim_entry(target, displaced)
    except BaseException:
        displaced.unlink(missing_ok=True)
        raise
    try:
        captured = _snapshot(displaced)
        if captured.identity != expected:
            raise RuntimeError(f"Codex file changed concurrently: {target}")
    except BaseException as exc:
        try:
            restored = _restore_captured(displaced, target)
        except OSError as restore_exc:
            raise RuntimeError(
                "Codex could not restore a captured entry; manual recovery "
                f"required from {displaced}"
            ) from restore_exc
        if not restored:
            raise RuntimeError(
                "Codex captured a changed or symbolic-link entry and a "
                "concurrent destination prevented restoration; manual recovery "
                f"required from {displaced}"
            ) from exc
        raise
    return displaced


def _publish_staged(
    target: Path,
    staged: Path,
    expected: FileIdentity,
) -> Replacement:
    installed_identity = _snapshot(staged).identity
    displaced = (
        _claim_expected(target, expected, label="displaced")
        if expected.exists
        else None
    )
    try:
        _publish_no_replace(staged, target)
    except OSError as exc:
        if displaced is not None:
            restored = _restore_captured(displaced, target)
            recovery = displaced
        elif _entry_exists(target):
            restored = False
            try:
                recovery = _retain_unpublished(staged, target)
            except OSError as recovery_exc:
                raise _RecoveryConflict(
                    "Codex publish found a concurrent destination; it was not "
                    "overwritten and manual recovery is required from "
                    f"{staged}",
                    staged,
                ) from recovery_exc
        else:
            restored = True
            recovery = staged
        if not restored:
            raise _RecoveryConflict(
                "Codex publish found a concurrent destination; it was not "
                "overwritten and manual recovery is required from "
                f"{recovery}",
                recovery,
            ) from exc
        raise
    return Replacement(target, installed_identity, displaced)


def _rollback_replacement(replacement: Replacement) -> None:
    target = replacement.target_path
    captured = _claim_expected(
        target, replacement.installed_identity, label="rollback"
    )
    if replacement.displaced_path is None:
        # The original target was absent. Claiming removes our installed entry;
        # any concurrent new destination remains outside this recovery entry.
        captured.unlink()
        return
    try:
        _publish_no_replace(replacement.displaced_path, target)
    except OSError as exc:
        raise RuntimeError(
            "Codex rollback found a concurrent destination; it was not "
            "overwritten and manual recovery is required from "
            f"{replacement.displaced_path} and {captured}"
        ) from exc
    replacement.displaced_path.unlink()
    captured.unlink()


def _rollback_replacements(
    replacements: list[Replacement], backups: tuple[BackupRecord, ...]
) -> None:
    errors = []
    for replacement in reversed(replacements):
        try:
            _rollback_replacement(replacement)
        except (OSError, RuntimeError) as exc:
            errors.append(f"{replacement.target_path}: {exc}")
    if errors:
        backup_paths = ", ".join(str(item.backup_path) for item in backups)
        raise RuntimeError(
            "Codex installation failed and concurrent edits prevented safe "
            "rollback; manual recovery required from retained backups "
            f"[{backup_paths}] ({'; '.join(errors)})"
        )


def _discard_displaced(replacements: list[Replacement]) -> None:
    for replacement in replacements:
        if replacement.displaced_path is not None:
            replacement.displaced_path.unlink(missing_ok=True)


def _publish_claimed_backups(
    claimed: dict[Path, tuple[BackupRecord, Path]],
) -> list[str]:
    """Publish authenticated claims without discarding recovery evidence."""
    errors = []
    for backup_path, (record, captured) in claimed.items():
        try:
            if _snapshot(captured).identity != record.identity:
                errors.append(
                    f"authenticated rollback backup changed: {captured}"
                )
                continue
            if _entry_exists(backup_path):
                try:
                    current = _snapshot(backup_path).identity
                except RuntimeError:
                    current = None
                if current != record.identity:
                    errors.append(
                        f"rollback backup path has a concurrent entry: "
                        f"{backup_path}; authenticated recovery retained at "
                        f"{captured}"
                    )
                continue
            _publish_no_replace(captured, backup_path)
        except (OSError, RuntimeError) as exc:
            errors.append(
                f"could not safely restore rollback backup path {backup_path}; "
                f"authenticated recovery retained at {captured}: {exc}"
            )
    return errors


def _assert_claimed_backup_paths(
    claimed: dict[Path, tuple[BackupRecord, Path]],
) -> None:
    for backup_path, (record, captured) in claimed.items():
        try:
            current = _snapshot(backup_path).identity
        except RuntimeError as exc:
            raise RuntimeError(
                f"rollback backup path changed; authenticated recovery is "
                f"retained at {captured}: {backup_path}"
            ) from exc
        if current != record.identity:
            raise RuntimeError(
                f"rollback backup path changed; authenticated recovery is "
                f"retained at {captured}: {backup_path}"
            )


def _rollback_restore_replacement(replacement: RestoreReplacement) -> None:
    target = replacement.target_path
    if replacement.restored_identity is None:
        try:
            _publish_no_replace(replacement.installed_path, target)
        except OSError as exc:
            raise RuntimeError(
                "Codex restore rollback found a concurrent destination; it was "
                "not overwritten and manual recovery is required from "
                f"{replacement.installed_path}"
            ) from exc
        replacement.installed_path.unlink()
        return

    restored = _claim_expected(
        target, replacement.restored_identity, label="restore-rollback"
    )
    try:
        _publish_no_replace(replacement.installed_path, target)
    except OSError as exc:
        if not _entry_exists(target):
            _restore_captured(restored, target)
        raise RuntimeError(
            "Codex restore rollback found a concurrent destination; it was not "
            "overwritten and manual recovery is required from "
            f"{replacement.installed_path} and {restored}"
        ) from exc
    replacement.installed_path.unlink()
    restored.unlink()


def _rollback_restore_replacements(
    replacements: list[RestoreReplacement],
) -> list[str]:
    errors = []
    for replacement in reversed(replacements):
        try:
            _rollback_restore_replacement(replacement)
        except (OSError, RuntimeError) as exc:
            errors.append(f"{replacement.target_path}: {exc}")
    return errors


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
            installed_files=(),
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
            replacement = _publish_staged(
                target, staged[target], snapshots[target].identity
            )
            replacements.append(replacement)
            _assert_identity(target, replacement.installed_identity)
    except BaseException as failure:
        preserve = (
            failure.recovery_paths
            if isinstance(failure, _RecoveryConflict)
            else ()
        )
        try:
            _rollback_replacements(replacements, backups)
        finally:
            _cleanup_stages(staged, preserve=preserve)
        raise
    _discard_displaced(replacements)
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
        installed_files=tuple(
            InstalledFile(item.target_path, item.installed_identity)
            for item in replacements
        ),
    )


def restore_codex(report: CodexInstallReport) -> tuple[Path, ...]:
    """Restore a completed transaction using its retained recovery records."""
    by_target = {record.target_path: record for record in report.backups}
    installed = {item.target_path: item.identity for item in report.installed_files}
    claimed_backups: dict[Path, tuple[BackupRecord, Path]] = {}
    staged_backups: dict[Path, Path] = {}
    replacements: list[RestoreReplacement] = []

    for target in report.changed_paths:
        if target not in installed:
            raise RuntimeError(
                f"no installed identity is available to restore {target} safely"
            )

    try:
        # Atomically claim every rollback entry before reading it. The claimed
        # entry, rather than a separately authenticated pathname, is the
        # transaction's authoritative recovery copy.
        for record in report.backups:
            if record.identity is None:
                raise RuntimeError(
                    f"valid rollback backup identity is unavailable: "
                    f"{record.backup_path}"
                )
            try:
                captured = _claim_expected(
                    record.backup_path,
                    record.identity,
                    label="restore-backup",
                )
            except (OSError, RuntimeError) as exc:
                raise RuntimeError(
                    f"valid rollback backup changed or is unavailable: "
                    f"{record.backup_path}"
                ) from exc
            claimed_backups[record.backup_path] = (record, captured)

        # Stage only bytes read from the stable, authenticated claims. Keep
        # both claims and stages until the entire restore transaction succeeds.
        for target in reversed(report.changed_paths):
            record = by_target.get(target)
            if record is None:
                continue
            captured = claimed_backups[record.backup_path][1]
            try:
                backup_snapshot = _snapshot(captured)
            except RuntimeError as exc:
                raise RuntimeError(
                    f"authenticated rollback backup is unavailable: {captured}"
                ) from exc
            if backup_snapshot.identity != record.identity:
                raise RuntimeError(
                    f"authenticated rollback backup changed after it was "
                    f"claimed: {captured}"
                )
            staged = _stage_bytes(
                target,
                backup_snapshot.content,
                mode=backup_snapshot.identity.mode,
            )
            if _snapshot(staged).identity.digest != record.identity.digest:
                staged.unlink(missing_ok=True)
                raise RuntimeError(
                    f"could not stage exact rollback backup: {record.backup_path}"
                )
            staged_backups[target] = staged

        # Re-publish authenticated backups without releasing the claims. A
        # concurrent substitute therefore blocks restore before any managed
        # target changes, remains untouched, and leaves authenticated evidence.
        backup_errors = _publish_claimed_backups(claimed_backups)
        if backup_errors:
            raise RuntimeError("; ".join(backup_errors))
        _assert_claimed_backup_paths(claimed_backups)

        # A known target conflict must fail before any managed target changes.
        for target in reversed(report.changed_paths):
            expected = installed[target]
            if _snapshot(target).identity != expected:
                raise RuntimeError(
                    f"Codex target changed since installation: {target}"
                )

        for target in reversed(report.changed_paths):
            # Keep checking the published backup entries immediately before
            # each first mutation of a managed target.
            _assert_claimed_backup_paths(claimed_backups)
            expected = installed[target]
            record = by_target.get(target)
            staged = staged_backups.get(target)
            captured = _claim_expected(target, expected, label="restore")
            if record is None:
                replacements.append(RestoreReplacement(target, None, captured))
                continue
            try:
                # Capture the exact target identity before its pathname is
                # published. Publication uses a private copy so an in-place
                # target edit cannot also rewrite the authenticated stage.
                restored_identity = _publish_detached_no_replace(staged, target)
            except OSError as exc:
                if _entry_exists(target):
                    raise RuntimeError(
                        "Codex restore found a concurrent destination; it was not "
                        "overwritten and manual recovery is required from "
                        f"{record.backup_path}, {captured}, and {staged}"
                    ) from exc
                if not _restore_captured(captured, target):
                    raise RuntimeError(
                        "Codex restore could not recover the installed target; "
                        f"manual recovery is required from {captured}"
                    ) from exc
                raise
            replacements.append(
                RestoreReplacement(target, restored_identity, captured)
            )

        # Backup paths must still name the authenticated entries before any
        # recovery evidence is discarded.
        _assert_claimed_backup_paths(claimed_backups)
    except BaseException as failure:
        rollback_errors = _rollback_restore_replacements(replacements)
        backup_errors = _publish_claimed_backups(claimed_backups)
        if rollback_errors or backup_errors:
            details = "; ".join((*rollback_errors, *backup_errors))
            raise RuntimeError(
                "Codex restore failed and safe rollback was incomplete; manual "
                f"recovery is required from retained evidence ({details})"
            ) from failure
        raise

    for replacement in replacements:
        replacement.installed_path.unlink(missing_ok=True)
    for staged in staged_backups.values():
        staged.unlink(missing_ok=True)
    for _, captured in claimed_backups.values():
        captured.unlink(missing_ok=True)
    return report.changed_paths
