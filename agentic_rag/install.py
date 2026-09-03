"""Targeted Claude and Codex installation for the ``rag install`` CLI.

The no-option path remains the legacy Claude installation: user-scoped MCP
registration, additive ``~/.claude/settings.json`` hook wiring, and the one
existing backup LaunchAgent.  Codex installation is an explicit, separate
target and never registers Claude MCP servers or another scheduler.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from . import backup
from .config import Config
from .integrations.codex import config as codex_config
from .integrations.codex import install as codex_install

SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
HOOK_MARKER = "agentic_rag.hooks."
MCP_NAME = "agentic-rag"
MCP_NAME_RO = "agentic-rag-ro"   # spec §5: the subagent server, rag_reader
CODEX_ROLLBACK_VERSION = 1


def managed_codex_settings() -> tuple[tuple[str, object], ...]:
    """Return the exact managed values from the canonical Codex policy."""
    return tuple(codex_config.ROOT_VALUES.items()) + tuple(
        (f"features.{key}", value)
        for key, value in codex_config.FEATURE_VALUES.items()
    ) + tuple(
        (f"memories.{key}", value)
        for key, value in codex_config.MEMORY_VALUES.items()
    )


def hook_entries(python: str) -> dict:
    def block(module: str, timeout: int) -> dict:
        return {"hooks": [{"type": "command",
                           "command": f"{python} -m {module}",
                           "timeout": timeout}]}
    return {
        "SessionStart": [{"matcher": "startup|resume|clear|compact",
                          **block("agentic_rag.hooks.session_start", 10)}],
        "UserPromptSubmit": [block("agentic_rag.hooks.prompt_recall", 5)],
        "Stop": [block("agentic_rag.hooks.stop_enqueue", 10)],
    }


def _is_ours(entry: dict) -> bool:
    return any(HOOK_MARKER in h.get("command", "")
               for h in entry.get("hooks", []))


def merge_hooks(settings: dict, python: str) -> dict:
    out = dict(settings)
    hooks = {k: list(v) for k, v in dict(out.get("hooks") or {}).items()}
    for event, entries in hook_entries(python).items():
        kept = [e for e in hooks.get(event, []) if not _is_ours(e)]
        hooks[event] = kept + entries
    out["hooks"] = hooks
    return out


def register_mcp(python: str, run=subprocess.run) -> None:
    """Register BOTH servers user-scope: agentic-rag (read-write, main
    sessions) and agentic-rag-ro (RAG_READONLY=1 → six read tools on the
    rag_reader role — spec §5's subagent server). Subagents inherit all
    session MCP servers, so containment additionally needs the subagent
    definition to allowlist only mcp__agentic-rag-ro__* tools."""
    # Resolve through PATH so this works on Windows too, where the CLI is a
    # claude.cmd shim unreachable by bare name (mirrors the llm.py seam).
    claude = shutil.which("claude") or "claude"
    base = {"type": "stdio", "command": python,
            "args": ["-m", "agentic_rag.mcp_server"]}
    servers = [
        (MCP_NAME, base),
        (MCP_NAME_RO, {**base, "env": {"RAG_READONLY": "1"}}),
    ]
    for name, spec in servers:
        run([claude, "mcp", "remove", "-s", "user", name],
            capture_output=True, text=True)      # rc ignored: may not exist
        proc = run([claude, "mcp", "add-json", "-s", "user", name,
                    json.dumps(spec)], capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                f"claude mcp add-json ({name}) failed: "
                f"{(proc.stderr or '')[:300]}")


@dataclass(frozen=True)
class InstallReport:
    settings_path: Path | None
    plist_path: Path | None
    mcp_registered: bool
    codex_report: codex_install.CodexInstallReport | None = None
    rollback_path: Path | None = None
    restored_paths: tuple[Path, ...] = ()

    @property
    def codex(self) -> codex_install.CodexInstallReport | None:
        """Short compatibility alias for target-aware CLI consumers."""
        return self.codex_report


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(path.expanduser()))


def _identity_data(identity: codex_install.FileIdentity) -> dict:
    return asdict(identity)


def _identity_from_data(data: object, *, label: str) -> codex_install.FileIdentity:
    fields = {
        "exists", "device", "inode", "size", "modified_ns", "digest", "mode",
    }
    if not isinstance(data, dict) or set(data) != fields:
        raise RuntimeError(f"invalid Codex rollback {label} identity")
    identity = codex_install.FileIdentity(**data)
    integers = (
        identity.device,
        identity.inode,
        identity.size,
        identity.modified_ns,
        identity.mode,
    )
    if (
        identity.exists is not True
        or any(not isinstance(value, int) for value in integers)
        or not isinstance(identity.digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", identity.digest) is None
    ):
        raise RuntimeError(f"invalid Codex rollback {label} identity")
    return identity


def _record_data(report: codex_install.CodexInstallReport) -> dict:
    changed = set(report.changed_paths)
    created = set(report.created_paths)
    backup_targets = {item.target_path for item in report.backups}
    installed_targets = {item.target_path for item in report.installed_files}
    if (
        report.check
        or not changed
        or created & backup_targets
        or created | backup_targets != changed
        or installed_targets != changed
    ):
        raise RuntimeError("Codex install did not produce a restorable report")
    backups = []
    for item in report.backups:
        snapshot = codex_install._snapshot(item.backup_path)
        if item.identity is None or snapshot.identity != item.identity:
            raise RuntimeError(
                f"valid rollback backup is unavailable: {item.backup_path}"
            )
        backups.append({
            "target_path": str(item.target_path),
            "backup_path": str(item.backup_path),
            "identity": _identity_data(item.identity),
        })
    return {
        "version": CODEX_ROLLBACK_VERSION,
        "home": str(report.paths.home),
        "changed_paths": [str(path) for path in report.changed_paths],
        "created_paths": [str(path) for path in report.created_paths],
        "backups": backups,
        "installed_files": [
            {
                "target_path": str(item.target_path),
                "identity": _identity_data(item.identity),
            }
            for item in report.installed_files
        ],
    }


def record_codex_rollback(report: codex_install.CodexInstallReport) -> Path:
    """Atomically persist the identities needed by ``restore_codex``."""
    data = _record_data(report)
    state_dir = report.paths.home / ".agentic-rag" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    record_path = state_dir / f"codex-rollback-{uuid.uuid4().hex}.json"
    descriptor, name = tempfile.mkstemp(
        prefix=".codex-rollback-", suffix=".tmp", dir=state_dir
    )
    staged = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        staged.chmod(0o600)
        os.link(staged, record_path, follow_symlinks=False)
    finally:
        staged.unlink(missing_ok=True)
    return record_path


def _record_path(value: object, *, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"invalid Codex rollback {label}")
    path = Path(value)
    if not path.is_absolute() or _absolute(path) != path:
        raise RuntimeError(f"invalid Codex rollback {label}")
    return path


def _load_codex_rollback(
        record_path: Path,
) -> codex_install.CodexInstallReport:
    record_path = _absolute(record_path)
    snapshot = codex_install._snapshot(record_path)
    if not snapshot.identity.exists:
        raise RuntimeError(f"invalid Codex rollback record: {record_path}")
    try:
        data = json.loads(snapshot.content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid Codex rollback record: {record_path}") from exc
    expected_keys = {
        "version", "home", "changed_paths", "created_paths", "backups",
        "installed_files",
    }
    if (
        not isinstance(data, dict)
        or set(data) != expected_keys
        or data["version"] != CODEX_ROLLBACK_VERSION
    ):
        raise RuntimeError(f"invalid Codex rollback record: {record_path}")
    try:
        home = _record_path(data["home"], label="home")
        paths = codex_install.CodexPaths.for_home(home)
        changed = tuple(
            _record_path(value, label="changed path")
            for value in data["changed_paths"]
        )
        created = tuple(
            _record_path(value, label="created path")
            for value in data["created_paths"]
        )
        backups = tuple(
            codex_install.BackupRecord(
                _record_path(item["target_path"], label="backup target"),
                _record_path(item["backup_path"], label="backup path"),
                _identity_from_data(item["identity"], label="backup"),
            )
            for item in data["backups"]
        )
        installed = tuple(
            codex_install.InstalledFile(
                _record_path(item["target_path"], label="installed target"),
                _identity_from_data(item["identity"], label="installed"),
            )
            for item in data["installed_files"]
        )
    except (KeyError, TypeError) as exc:
        raise RuntimeError(f"invalid Codex rollback record: {record_path}") from exc

    target_set = set(paths.targets)
    changed_set = set(changed)
    created_set = set(created)
    backup_targets = {item.target_path for item in backups}
    installed_targets = {item.target_path for item in installed}
    backup_paths = [item.backup_path for item in backups]
    valid_backup_names = all(
        item.backup_path.parent == item.target_path.parent
        and item.backup_path.name.startswith(item.target_path.name + ".bak.")
        and re.fullmatch(
            r"[0-9a-f]{32}",
            item.backup_path.name.removeprefix(item.target_path.name + ".bak."),
        ) is not None
        for item in backups
    )
    if (
        not changed
        or len(changed_set) != len(changed)
        or not changed_set <= target_set
        or len(created_set) != len(created)
        or created_set & backup_targets
        or created_set | backup_targets != changed_set
        or installed_targets != changed_set
        or len(installed_targets) != len(installed)
        or len(set(backup_paths)) != len(backup_paths)
        or not valid_backup_names
    ):
        raise RuntimeError(f"invalid Codex rollback record: {record_path}")
    report = codex_install.CodexInstallReport(
        paths=paths,
        changed_paths=changed,
        backups=backups,
        created_paths=created,
        foreign_hook_duplicates=(),
        check=False,
        codex_version=None,
        runtime_validation="recorded rollback",
        probe_isolation="not applicable during rollback",
        installed_files=installed,
    )
    return report


def restore_codex_rollback(record_path: Path) -> tuple[Path, ...]:
    """Validate a recorded transaction, then use Task 6's safe restore."""
    report = _load_codex_rollback(record_path)
    return codex_install.restore_codex(report)


def install(cfg: Config, *, settings_path: Path | None = None,
            run=subprocess.run, with_launchd: bool = True,
            codex: bool = False, check: bool = False,
            codex_home: Path | None = None,
            restore_path: Path | None = None) -> InstallReport:
    if restore_path is not None and not codex:
        raise ValueError("restore_path requires codex=True")
    if restore_path is not None and check:
        raise ValueError("Codex restore and check are mutually exclusive")
    if codex:
        if restore_path is not None:
            restored = restore_codex_rollback(restore_path)
            return InstallReport(None, None, False, restored_paths=restored)
        paths = codex_install.CodexPaths.for_home(
            _absolute(Path.home() if codex_home is None else codex_home)
        )
        report = codex_install.install_codex(paths, check=check, run=run)
        rollback_path = None
        if not report.check and report.changed_paths:
            try:
                rollback_path = record_codex_rollback(report)
            except BaseException as record_failure:
                try:
                    codex_install.restore_codex(report)
                except BaseException as restore_failure:
                    backups = ", ".join(
                        str(item.backup_path) for item in report.backups
                    )
                    raise RuntimeError(
                        "Codex installation could not record rollback and "
                        "automatic restoration failed; manual recovery "
                        f"required from [{backups}]"
                    ) from restore_failure
                raise RuntimeError(
                    "Codex installation was restored because its rollback "
                    "record could not be written"
                ) from record_failure
        return InstallReport(
            None, None, False, report, rollback_path=rollback_path
        )
    if check:
        raise ValueError("--check requires --codex")

    python = sys.executable
    register_mcp(python, run=run)

    settings_path = settings_path or SETTINGS_PATH
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        current = json.loads(settings_path.read_text())
    except OSError:
        current = {}        # no settings file yet — start fresh
    except ValueError as e:
        # a CORRUPT settings.json must never be silently replaced with a
        # hooks-only file — that would drop the user's model/permissions/
        # foreign hooks from the live config (the .bak of garbage is no
        # recovery). Abort loudly; the user fixes or moves the file aside.
        raise RuntimeError(
            f"{settings_path} is not valid JSON ({e}) — fix it or move it "
            f"aside, then re-run rag install") from e
    if settings_path.exists():
        settings_path.with_suffix(".json.bak").write_text(
            settings_path.read_text())
    merged = merge_hooks(current, python)
    tmp = settings_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(merged, indent=2) + "\n")
    os.replace(tmp, settings_path)

    plist = None
    if with_launchd and sys.platform == "darwin":
        # the launchd gate: resolve rag NEXT TO the current interpreter —
        # never trust a stale plist or an inherited PATH
        rag_bin = Path(python).with_name("rag")
        plist = backup.install_launchd(cfg, rag_bin)
    return InstallReport(settings_path, plist, True)
