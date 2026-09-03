"""Fast, bounded capture of deterministic continuation state."""
from __future__ import annotations

import hashlib
import json
import subprocess
import threading
import time
from bisect import insort
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from agentic_rag.config import load_config
from agentic_rag.secrets import strip_secrets

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
_GIT_PATH_MAX_CHARS = 4_096
_SECRET_SCAN_OVERLAP_CHARS = 256
_MAX_UTF8_BYTES_PER_CHAR = 4
TRANSCRIPT_TAIL_BYTES = 64 * 1024


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _path_text(value: object) -> str | None:
    """Validate path text without changing whitespace-significant names."""
    return value if isinstance(value, str) and value.strip() else None


def _run_git(
    cwd_argument: str,
    command: tuple[str, ...],
    run: Callable[..., Any],
    *,
    max_chars: int,
) -> tuple[bool, str, str | None, bool]:
    argv = ["git", "-C", cwd_argument, *command]
    read_chars = max(0, max_chars) + _SECRET_SCAN_OVERLAP_CHARS
    try:
        if run is subprocess.run:
            returncode, stdout, timed_out, read_truncated = _bounded_git_process(
                argv, read_chars
            )
            if timed_out:
                return False, "", f"git {' '.join(command)} timed out", False
        else:
            result = run(
                argv,
                shell=False,
                capture_output=True,
                text=True,
                check=False,
                timeout=_GIT_TIMEOUT_SECONDS,
            )
            returncode = result.returncode
            raw_stdout = result.stdout if isinstance(result.stdout, str) else ""
            read_truncated = len(raw_stdout) > read_chars
            stdout = raw_stdout[:read_chars]
    except subprocess.TimeoutExpired:
        return False, "", f"git {' '.join(command)} timed out", False
    except OSError:
        return False, "", f"git {' '.join(command)} unavailable", False
    if returncode != 0 and not read_truncated:
        return False, "", None, False
    raw = stdout.rstrip("\r\n")
    sanitized = strip_secrets(raw)[0]
    truncated = read_truncated or len(raw) > max_chars or len(sanitized) > max_chars
    return True, sanitized[:max_chars], None, truncated


def _bounded_git_process(
    argv: list[str], read_chars: int
) -> tuple[int, str, bool, bool]:
    """Read a finite prefix, enforcing one deadline and always reaping Git."""
    process = subprocess.Popen(
        argv,
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if process.stdout is None:  # pragma: no cover - PIPE guarantees a stream
        process.kill()
        process.wait()
        return process.returncode, "", False, False

    byte_limit = read_chars * _MAX_UTF8_BYTES_PER_CHAR
    read_size = byte_limit + 1
    result: list[bytes] = []
    read_errors: list[BaseException] = []

    def read_prefix() -> None:
        try:
            result.append(process.stdout.read(read_size))
        except BaseException as exc:  # propagated after process cleanup
            read_errors.append(exc)

    deadline = time.monotonic() + _GIT_TIMEOUT_SECONDS
    reader = threading.Thread(target=read_prefix, daemon=True)
    reader.start()
    reader.join(timeout=_GIT_TIMEOUT_SECONDS)
    timed_out = reader.is_alive()
    read_truncated = bool(result and len(result[0]) > byte_limit)
    if timed_out or read_truncated:
        try:
            process.kill()
        except OSError:
            pass
    try:
        process.wait(timeout=max(0.001, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            process.kill()
        except OSError:
            pass
        process.wait()
    reader.join(timeout=0.1)
    process.stdout.close()
    if read_errors:
        raise OSError("failed to read git output") from read_errors[0]
    data = result[0][:byte_limit] if result else b""
    return (
        process.returncode,
        data.decode("utf-8", errors="replace"),
        timed_out,
        read_truncated,
    )


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
    ok, root_value, warning, root_truncated = _run_git(
        cwd_argument,
        _GIT_COMMANDS[0][1],
        run,
        max_chars=_GIT_PATH_MAX_CHARS,
    )
    warnings = [warning] if warning else []
    if root_truncated:
        warnings.append("git rev-parse --show-toplevel output truncated")
    if not ok or not root_value or root_truncated:
        return None, {}, warnings

    project_root = _canonical(root_value, relative_to=cwd)
    values: dict[str, str] = {"root": project_root}
    for name, command in _GIT_COMMANDS[1:]:
        output_limit = (
            status_max_chars
            if name == "status"
            else _GIT_PATH_MAX_CHARS
            if name in {"git_dir", "git_common_dir"}
            else _GIT_METADATA_MAX_CHARS
        )
        succeeded, output, warning, truncated = _run_git(
            cwd_argument, command, run, max_chars=output_limit
        )
        if warning:
            warnings.append(warning)
        if succeeded:
            values[name] = output
        if truncated:
            if name == "status":
                warnings.append("git status truncated")
            else:
                warnings.append(f"git {' '.join(command)} output truncated")

    git: dict[str, object] = {
        "worktree": str(cwd),
        "root": project_root,
    }
    for name in ("git_dir", "git_common_dir"):
        if value := values.get(name):
            git[name] = _canonical(value, relative_to=cwd)
    if "branch" in values:
        branch = values["branch"] or "detached HEAD"
        git["branch"] = branch
    if head := values.get("head"):
        git["head"] = head[:_GIT_METADATA_MAX_CHARS]
    if "status" in values:
        git["status"] = values["status"]
    return project_root, git, warnings


def _transcript_state(path_value: str | None) -> tuple[str | None, str | None]:
    if path_value is None:
        return None, None
    path = Path(path_value).expanduser()
    try:
        stat = path.stat()
    except OSError:
        return None, None
    canonical = str(path.resolve(strict=False))
    metadata = f"{canonical}\0{stat.st_size}\0{stat.st_mtime_ns}"
    fingerprint = "sha256:" + hashlib.sha256(metadata.encode()).hexdigest()
    cursor = None
    try:
        # Reserve one byte for boundary detection.  One capped read then
        # contains the complete tail through EOF plus the byte immediately
        # preceding it, without scanning or materializing the whole JSONL.
        content_limit = TRANSCRIPT_TAIL_BYTES - 1
        start = max(0, stat.st_size - content_limit)
        read_start = start - 1 if start else 0
        with path.open("rb") as fh:
            fh.seek(read_start)
            tail = fh.read(TRANSCRIPT_TAIL_BYTES)
        if start:
            if tail[:1] == b"\n":
                tail = tail[1:]
            else:
                boundary = tail.find(b"\n")
                tail = tail[boundary + 1:] if boundary >= 0 else b""
        for raw in reversed(tail.splitlines()):
            try:
                event = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            value = event.get("uuid") if isinstance(event, dict) else None
            if isinstance(value, str) and value.strip():
                cursor = value
                break
    except OSError:
        pass
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


class _ArtifactCandidates:
    """Keep only the lexically first ``limit + 1`` paths while streaming."""

    def __init__(self, limit: int):
        self.limit = max(0, limit)
        self._capacity = self.limit + 1
        self._items: list[str] = []
        self._seen = 0

    @property
    def retained_count(self) -> int:
        return len(self._items)

    def add(self, candidate: str) -> None:
        self._seen += 1
        if len(self._items) < self._capacity:
            insort(self._items, candidate)
        elif candidate < self._items[-1]:
            self._items.pop()
            insort(self._items, candidate)

    def result(self) -> tuple[tuple[str, ...], bool]:
        return tuple(self._items[:self.limit]), self._seen > self.limit


def _artifacts(project_root: str, limit: int) -> tuple[tuple[str, ...], bool]:
    root = Path(project_root)
    found = _ArtifactCandidates(limit)
    for relative in _ROOT_ARTIFACTS:
        if (root / relative).is_file():
            found.add(relative)
    for directory in _ARTIFACT_DIRECTORIES:
        absolute = root / directory
        try:
            entries = absolute.iterdir()
        except OSError:
            continue
        try:
            for entry in entries:
                if entry.is_file():
                    found.add((directory / entry.name).as_posix())
        except OSError:
            continue
    return found.result()


def capture_snapshot_seed(payload: Mapping[str, object]) -> CheckpointSnapshot:
    """Capture the bounded state that precedes optional repository probes."""
    if not isinstance(payload, Mapping):
        raise TypeError("payload must be a mapping")
    cwd_argument = _path_text(payload.get("cwd"))
    cwd = Path(cwd_argument).expanduser().resolve(strict=False) if cwd_argument else None
    transcript_path = _text(payload.get("transcript_path"))
    transcript_cursor, transcript_fingerprint = _transcript_state(transcript_path)
    cursor = transcript_cursor or _event_cursor(
        payload,
        cwd=str(cwd) if cwd else None,
        transcript_fingerprint=transcript_fingerprint,
    )

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
        project_root=None,
        transcript_fingerprint=transcript_fingerprint,
    )


def capture_repository_state(
    snapshot: CheckpointSnapshot,
    *,
    cwd: object,
    run: Callable[..., Any] = subprocess.run,
) -> CheckpointSnapshot:
    """Add bounded Git/artifact metadata to an already captured seed."""
    if not isinstance(snapshot, CheckpointSnapshot):
        raise TypeError("snapshot must be a CheckpointSnapshot")
    cwd_argument = _path_text(cwd)
    if cwd_argument is None or snapshot.cwd is None:
        return snapshot
    cfg = load_config()
    project_root, git, warnings = _git_state(
        cwd_argument,
        Path(snapshot.cwd),
        run,
        cfg.checkpoint_status_max_chars,
    )
    artifacts: tuple[str, ...] = ()
    if project_root:
        artifacts, truncated = _artifacts(project_root, cfg.checkpoint_artifact_max)
        if truncated:
            warnings.append("artifact list truncated")
    return replace(
        snapshot,
        project_root=project_root,
        git=git,
        artifacts=artifacts,
        warnings=(*snapshot.warnings, *warnings),
    )


def capture_snapshot(
    payload: Mapping[str, object],
    *,
    run: Callable[..., Any] = subprocess.run,
) -> CheckpointSnapshot:
    """Capture one idempotent operational snapshot without artifact bodies."""
    seed = capture_snapshot_seed(payload)
    return capture_repository_state(seed, cwd=payload.get("cwd"), run=run)
