"""Fast, bounded capture of deterministic continuation state."""
from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from agentic_rag.config import load_config
from agentic_rag.transcript import build_digest

from .model import CheckpointSnapshot


_GIT_COMMANDS = (
    ("root", ("rev-parse", "--show-toplevel")),
    ("git_dir", ("rev-parse", "--git-dir")),
    ("git_common_dir", ("rev-parse", "--git-common-dir")),
    ("branch", ("branch", "--show-current")),
    ("head", ("rev-parse", "HEAD")),
    ("status", ("status", "--short")),
)
_ROOT_ARTIFACTS = ("AGENTS.md", "CLAUDE.md", "BACKLOG.md", "FEATURES.md")
_ARTIFACT_DIRECTORIES = (
    Path("docs/superpowers/specs"),
    Path("docs/superpowers/plans"),
)
_GIT_TIMEOUT_SECONDS = 0.35
_GIT_METADATA_MAX_CHARS = 1_024


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _run_git(
    cwd_argument: str,
    command: tuple[str, ...],
    run: Callable[..., Any],
) -> tuple[bool, str, str | None]:
    argv = ["git", "-C", cwd_argument, *command]
    try:
        result = run(
            argv,
            shell=False,
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return False, "", f"git {' '.join(command)} timed out"
    except OSError:
        return False, "", f"git {' '.join(command)} unavailable"
    if result.returncode != 0:
        return False, "", None
    stdout = result.stdout if isinstance(result.stdout, str) else ""
    return True, stdout.rstrip("\r\n"), None


def _canonical(value: str, *, relative_to: Path | None = None) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute() and relative_to is not None:
        path = relative_to / path
    return str(path.resolve(strict=False))


def _git_state(
    cwd_argument: str,
    cwd: Path,
    run: Callable[..., Any],
    status_max_chars: int,
) -> tuple[str | None, dict[str, object], list[str]]:
    ok, root_value, warning = _run_git(cwd_argument, _GIT_COMMANDS[0][1], run)
    warnings = [warning] if warning else []
    if not ok or not root_value:
        return None, {}, warnings

    project_root = _canonical(root_value, relative_to=cwd)
    values: dict[str, str] = {"root": project_root}
    for name, command in _GIT_COMMANDS[1:]:
        succeeded, output, warning = _run_git(cwd_argument, command, run)
        if warning:
            warnings.append(warning)
        if succeeded:
            values[name] = output

    git: dict[str, object] = {
        "worktree": str(cwd),
        "root": project_root,
    }
    for name in ("git_dir", "git_common_dir"):
        if value := values.get(name):
            git[name] = _canonical(value, relative_to=cwd)
    if "branch" in values:
        git["branch"] = values["branch"] or "detached HEAD"
    if head := values.get("head"):
        git["head"] = head[:_GIT_METADATA_MAX_CHARS]
    if "status" in values:
        status = values["status"]
        git["status"] = status[:status_max_chars]
        if len(status) > status_max_chars:
            warnings.append("git status truncated")
    return project_root, git, warnings


def _transcript_state(path_value: str | None) -> tuple[str | None, str | None]:
    if path_value is None:
        return None, None
    path = Path(path_value).expanduser()
    cursor = build_digest(path, max_chars=0).last_uuid
    try:
        stat = path.stat()
    except OSError:
        return cursor, None
    canonical = str(path.resolve(strict=False))
    metadata = f"{canonical}\0{stat.st_size}\0{stat.st_mtime_ns}"
    fingerprint = "sha256:" + hashlib.sha256(metadata.encode()).hexdigest()
    return cursor, fingerprint


def _event_cursor(
    payload: Mapping[str, object],
    *,
    cwd: str | None,
    transcript_fingerprint: str | None,
) -> str:
    identity = {
        "session_id": payload.get("session_id"),
        "turn_id": payload.get("turn_id"),
        "source": payload.get("hook_event_name") or payload.get("source"),
        "trigger": payload.get("trigger"),
        "cwd": cwd,
        "transcript_fingerprint": transcript_fingerprint,
    }
    encoded = json.dumps(identity, sort_keys=True, default=str, separators=(",", ":"))
    return "event:" + hashlib.sha256(encoded.encode()).hexdigest()


def _artifacts(project_root: str, limit: int) -> tuple[tuple[str, ...], bool]:
    root = Path(project_root)
    found: list[str] = []
    for relative in _ROOT_ARTIFACTS:
        if (root / relative).is_file():
            found.append(relative)
    for directory in _ARTIFACT_DIRECTORIES:
        absolute = root / directory
        try:
            entries = sorted(absolute.iterdir(), key=lambda path: path.name)
        except OSError:
            continue
        for entry in entries:
            if entry.is_file():
                found.append((directory / entry.name).as_posix())
    found.sort()
    return tuple(found[:limit]), len(found) > limit


def capture_snapshot(
    payload: Mapping[str, object],
    *,
    run: Callable[..., Any] = subprocess.run,
) -> CheckpointSnapshot:
    """Capture one idempotent operational snapshot without artifact bodies."""
    if not isinstance(payload, Mapping):
        raise TypeError("payload must be a mapping")
    cfg = load_config()
    cwd_argument = _text(payload.get("cwd"))
    cwd = Path(cwd_argument).expanduser().resolve(strict=False) if cwd_argument else None
    project_root: str | None = None
    git: dict[str, object] = {}
    warnings: list[str] = []
    if cwd_argument and cwd is not None:
        project_root, git, git_warnings = _git_state(
            cwd_argument,
            cwd,
            run,
            cfg.checkpoint_status_max_chars,
        )
        warnings.extend(git_warnings)

    transcript_path = _text(payload.get("transcript_path"))
    transcript_cursor, transcript_fingerprint = _transcript_state(transcript_path)
    cursor = transcript_cursor or _event_cursor(
        payload,
        cwd=str(cwd) if cwd else None,
        transcript_fingerprint=transcript_fingerprint,
    )

    artifacts: tuple[str, ...] = ()
    if project_root:
        artifacts, truncated = _artifacts(project_root, cfg.checkpoint_artifact_max)
        if truncated:
            warnings.append("artifact list truncated")

    return CheckpointSnapshot(
        session_id=_text(payload.get("session_id")) or "",
        turn_id=_text(payload.get("turn_id")),
        cursor=cursor,
        source=(
            _text(payload.get("hook_event_name"))
            or _text(payload.get("source"))
            or "event"
        ),
        trigger=_text(payload.get("trigger")),
        cwd=str(cwd) if cwd else None,
        project_root=project_root,
        transcript_fingerprint=transcript_fingerprint,
        git=git,
        artifacts=artifacts,
        warnings=tuple(warnings),
    )
