"""Provider-neutral structured LLM chokepoint for mining and curation.

Claude remains the backward-compatible public default. Codex is an explicit
provider that runs as an ephemeral, read-only JSON transform in an empty
temporary directory, without loading user/project instructions or plugins.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .config import Config
from .secrets import strip_secrets

_STRIP_ENV = (
    "CLAUDECODE",
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_EXECPATH",
)


class LLMError(RuntimeError):
    """Base class for structured-provider failures."""


class LLMJobError(LLMError):
    """One invocation returned unusable structured content."""


class LLMUnavailableError(LLMError):
    """The configured provider is unavailable across jobs."""


def _child_env(env: dict | None) -> dict:
    child = dict(os.environ if env is None else env)
    for key in _STRIP_ENV:
        child.pop(key, None)
    # A `claude -p` child inherits ~/.claude/settings.json, so on completion it
    # fires ITS OWN Stop hook, which would enqueue the child's transcript for
    # mining -> mining spawns another `claude -p` -> self-amplifying cascade
    # (nested "SESSION DIGEST" digests truncated at max_chars). Setting the
    # kill switch every agentic-rag hook honors (common.is_interactive) makes
    # the system's own LLM calls hook-inert. Stripping CLAUDE_CODE_* above only
    # stops parent-session recursion; this stops child-transcript re-mining.
    child["AGENTIC_RAG_HOOKS_DISABLE"] = "1"
    # ANTHROPIC_API_KEY (if any) passes through UNCHANGED: agentic-rag is
    # auth-agnostic and lets the claude CLI use whatever it is logged into —
    # subscription OAuth or an API key. The user's choice; we neither impose
    # nor refuse one.
    return child


def _binary(cfg: Config, child_env: dict) -> str:
    return shutil.which(cfg.llm_bin, path=child_env.get("PATH")) or cfg.llm_bin


def _diagnostic(proc) -> str:
    raw = (proc.stderr or proc.stdout or "").strip()[:500]
    return strip_secrets(raw)[0]


def _parse_object(raw: str, provider: str) -> dict:
    if not raw:
        raise LLMJobError(f"{provider} output was empty")
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise LLMJobError(
            f"{provider} output is not valid JSON: {raw[:200]!r}") from e
    if not isinstance(data, dict):
        raise LLMJobError(
            f"{provider} output is not a JSON object: {data!r:.200}")
    return data


def check_provider(cfg: Config, *, runner=subprocess.run,
                   env: dict | None = None) -> None:
    """Cheap local preflight for providers that expose one."""
    if cfg.llm_provider == "claude":
        return
    if cfg.llm_provider != "codex":
        raise ValueError(f"unknown LLM provider: {cfg.llm_provider!r}")
    child_env = _child_env(env)
    binary = _binary(cfg, child_env)
    cmd = [binary, "login", "status"]
    try:
        proc = runner(cmd, capture_output=True, text=True, encoding="utf-8",
                      timeout=min(cfg.llm_timeout, 30), env=child_env)
    except FileNotFoundError as e:
        raise LLMUnavailableError(
            f"codex binary not found ({cfg.llm_bin!r}); is the CLI on PATH?") from e
    except subprocess.TimeoutExpired as e:
        raise LLMUnavailableError("codex login status timed out after 30s") from e
    except UnicodeDecodeError as e:
        raise LLMUnavailableError(
            f"codex login status was not valid UTF-8: {e}") from e
    if proc.returncode != 0:
        detail = _diagnostic(proc)
        suffix = f": {detail}" if detail else ""
        raise LLMUnavailableError(
            f"codex login status exited {proc.returncode}{suffix}")


def _run_claude_structured(prompt: str, schema: dict, cfg: Config, *,
                           system: str | None, timeout: int | None,
                           runner, child_env: dict) -> dict:
    binary = _binary(cfg, child_env)
    cmd = [binary, "--model", cfg.llm_model]
    if system is not None:
        cmd += ["--system-prompt", system]
    cmd += ["-p", prompt, "--json-schema", json.dumps(schema)]
    try:
        proc = runner(cmd, capture_output=True, text=True, encoding="utf-8",
                      timeout=timeout or cfg.llm_timeout, env=child_env)
    except FileNotFoundError as e:
        raise LLMUnavailableError(
            f"claude binary not found ({cfg.llm_bin!r}); is the CLI on "
            f"PATH?") from e
    except subprocess.TimeoutExpired as e:
        raise LLMUnavailableError(
            f"claude timed out after {timeout or cfg.llm_timeout}s") from e
    except UnicodeDecodeError as e:
        raise LLMJobError(f"claude output was not valid UTF-8: {e}") from e
    if proc.returncode != 0:
        detail = _diagnostic(proc)
        suffix = f": {detail}" if detail else ""
        raise LLMUnavailableError(
            f"claude exited {proc.returncode}{suffix}")
    return _parse_object(proc.stdout, "claude")


def _run_codex_structured(prompt: str, schema: dict, cfg: Config, *,
                          system: str | None, timeout: int | None,
                          runner, child_env: dict) -> dict:
    check_provider(cfg, runner=runner, env=child_env)
    binary = _binary(cfg, child_env)
    combined = (
        "SYSTEM INSTRUCTIONS\n"
        + (system or "Return only the requested schema-valid JSON object.")
        + "\n\nTASK\n" + prompt
    )
    with tempfile.TemporaryDirectory(prefix="agentic-rag-codex-") as tmp:
        workdir = Path(tmp)
        schema_path = workdir / "schema.json"
        output_path = workdir / "output.json"
        schema_path.write_text(json.dumps(schema), encoding="utf-8")
        cmd = [
            binary, "exec", "--model", cfg.llm_model,
            "-c", f'model_reasoning_effort="{cfg.llm_reasoning_effort}"',
            "--ephemeral", "--sandbox", "read-only",
            "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules",
            "--output-schema", str(schema_path),
            "--output-last-message", str(output_path), combined,
        ]
        try:
            proc = runner(
                cmd, capture_output=True, text=True, encoding="utf-8",
                timeout=timeout or cfg.llm_timeout, env=child_env,
                cwd=str(workdir))
        except FileNotFoundError as e:
            raise LLMUnavailableError(
                f"codex binary not found ({cfg.llm_bin!r}); is the CLI on PATH?") from e
        except subprocess.TimeoutExpired as e:
            raise LLMUnavailableError(
                f"codex timed out after {timeout or cfg.llm_timeout}s") from e
        except UnicodeDecodeError as e:
            raise LLMJobError(f"codex output was not valid UTF-8: {e}") from e
        if proc.returncode != 0:
            detail = _diagnostic(proc)
            suffix = f": {detail}" if detail else ""
            raise LLMUnavailableError(
                f"codex exited {proc.returncode}{suffix}")
        if not output_path.exists():
            raise LLMJobError("codex did not produce structured output")
        return _parse_object(output_path.read_text(encoding="utf-8"), "codex")


def run_structured(prompt: str, schema: dict, cfg: Config, *,
                   system: str | None = None, timeout: int | None = None,
                   runner=subprocess.run, env: dict | None = None) -> dict:
    """Run one provider-backed structured transform and return a JSON object."""
    child_env = _child_env(env)
    if cfg.llm_provider == "claude":
        return _run_claude_structured(
            prompt, schema, cfg, system=system, timeout=timeout,
            runner=runner, child_env=child_env)
    if cfg.llm_provider == "codex":
        return _run_codex_structured(
            prompt, schema, cfg, system=system, timeout=timeout,
            runner=runner, child_env=child_env)
    raise ValueError(f"unknown LLM provider: {cfg.llm_provider!r}")
