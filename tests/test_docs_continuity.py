import re
import tomllib
from pathlib import Path


DOC_PATHS = (
    Path("README.md"),
    Path("docs/00-whats-new-in-0.3.md"),
    Path("docs/00-whats-new-in-0.4.md"),
    Path("docs/00-whats-new-in-0.5.md"),
    Path("docs/01-what-is-agentic-rag.md"),
    Path("docs/02-mental-model.md"),
    Path("docs/03-quick-start.md"),
    Path("docs/04-working-with-memory.md"),
    Path("docs/05-session-mining-and-curation.md"),
    Path("docs/06-configuration-reference.md"),
    Path("docs/07-privacy-and-cost.md"),
    Path("docs/10-architecture.md"),
    Path("docs/11-reference-cli-and-mcp.md"),
    Path("docs/12-contributing.md"),
    Path("docs/README.md"),
)


def test_v030_release_metadata_and_whats_new_are_linked():
    pyproject = Path("pyproject.toml").read_text()
    changelog = Path("CHANGELOG.md").read_text()
    readme = Path("README.md").read_text()
    handbook = Path("docs/README.md").read_text()
    whats_new = Path("docs/00-whats-new-in-0.3.md")

    assert "## [0.3.0] - 2026-09-03" in changelog
    assert whats_new.is_file()
    assert "What’s New in 0.3.0" in whats_new.read_text()
    assert "docs/00-whats-new-in-0.3.md" in readme
    assert "00-whats-new-in-0.3.md" in handbook


def test_v040_release_metadata_and_whats_new_are_linked():
    pyproject = Path("pyproject.toml").read_text()
    changelog = Path("CHANGELOG.md").read_text()
    readme = Path("README.md").read_text()
    handbook = Path("docs/README.md").read_text()
    whats_new = Path("docs/00-whats-new-in-0.4.md")

    assert "## [0.4.2] - 2026-09-04" in changelog
    assert "## [0.4.1] - 2026-09-04" in changelog
    assert "## [0.4.0] - 2026-09-04" in changelog
    assert whats_new.is_file()
    assert whats_new.read_text().startswith("# What’s New in 0.4.0\n")
    assert "docs/00-whats-new-in-0.4.md" in readme
    assert "00-whats-new-in-0.4.md" in handbook
    assert "unreleased" not in readme.lower().split("what’s new in 0.4.0")[0]


def test_v050_release_metadata_and_whats_new_are_linked():
    pyproject = Path("pyproject.toml").read_text()
    changelog = Path("CHANGELOG.md").read_text()
    readme = Path("README.md").read_text()
    handbook = Path("docs/README.md").read_text()
    whats_new = Path("docs/00-whats-new-in-0.5.md")

    assert 'version = "0.5.0"' in pyproject
    assert "## [0.5.0] - 2026-09-06" in changelog
    assert whats_new.is_file()
    assert whats_new.read_text().startswith("# What’s New in 0.5.0\n")
    assert "docs/00-whats-new-in-0.5.md" in readme
    assert "00-whats-new-in-0.5.md" in handbook
    assert "unreleased" not in readme.lower().split("what’s new in 0.5.0")[0]
    assert "assets/agy/compact_prompt.md" in pyproject


def test_wheel_configuration_includes_runtime_migrations():
    project = tomllib.loads(Path("pyproject.toml").read_text())
    force_include = project["tool"]["hatch"]["build"]["targets"]["wheel"][
        "force-include"
    ]

    assert force_include["sql"] == "sql"


def test_release_lock_uses_patched_cryptography():
    lock = tomllib.loads(Path("uv.lock").read_text())
    cryptography = next(
        package for package in lock["package"] if package["name"] == "cryptography"
    )
    version = tuple(int(part) for part in cryptography["version"].split("."))

    assert version >= (50, 0, 0)


def docs_text() -> str:
    return "\n".join(path.read_text() for path in DOC_PATHS)


def test_docs_explain_memory_ownership_and_compaction_limit():
    corpus = docs_text()
    assert "350000" in corpus and "250000" in corpus
    assert "100K reserve" in corpus
    assert re.search(r"(?:above|>) (?:the official )?272K", corpus)
    assert "higher provider pricing" in corpus
    assert "native Codex memories" in corpus
    assert "agentic-rag" in corpus and "canonical" in corpus
    assert "PostCompact cannot inject context" in corpus
    assert 'SessionStart(source="compact")' in corpus
    assert "same-session checkpoint wins regardless of project metadata" in corpus
    assert "compact never falls back to another session or project" in corpus

    current_config = Path("docs/06-configuration-reference.md").read_text()
    current_cost = Path("docs/07-privacy-and-cost.md").read_text()
    current_reference = Path("docs/11-reference-cli-and-mcp.md").read_text()
    assert "model_context_window = 350000" in current_config
    assert "model_auto_compact_token_limit = 250000" in current_config
    assert "model_context_window = 350000" in current_cost
    assert "model_auto_compact_token_limit = 250000" in current_cost
    assert "model_context_window=350000" in current_reference
    assert "model_auto_compact_token_limit=250000" in current_reference

    historical_v030 = Path("docs/00-whats-new-in-0.3.md").read_text()
    historical_v040 = Path("docs/00-whats-new-in-0.4.md").read_text()
    assert "600,000-token context window" in historical_v030
    assert "500,000 total tokens" in historical_v030
    assert "Codex 600K/500K policy" in historical_v040


def test_docs_disclose_external_provider_calls_and_rollout_boundary():
    corpus = docs_text()
    readme = Path("README.md").read_text()
    privacy = Path("docs/07-privacy-and-cost.md").read_text()
    readme_summary = re.search(
        r"> \*\*Your data stays.*?(?=\n\n)", readme, re.S
    )
    privacy_summary = re.search(
        r"In every case, \*\*embeddings are local\*\*.*?(?=\n### Native)",
        privacy,
        re.S,
    )
    assert readme_summary and privacy_summary
    for outbound_summary in (readme_summary.group(0), privacy_summary.group(0)):
        outbound_summary = " ".join(
            outbound_summary.replace("**", "").replace(">", "").split()
        )
        for disclosed_input in (
            "mining",
            "curation",
            "checkpoint enrichment",
            "matching pin bodies",
        ):
            assert disclosed_input in outbound_summary
        assert re.search(
            r"secret-stripped (?:copies of )?(?:all )?matching pin bodies",
            outbound_summary,
        )
        assert "without mutating stored pin text" in outbound_summary
        assert "not independently redacted" not in outbound_summary
        assert "no-secrets rule" not in outbound_summary
        assert "all matching pin bodies" in outbound_summary
    assert "disable_on_external_context = false" in privacy
    assert "live verification pending" in corpus
    assert "Only LLM-assisted mining and curation" not in corpus
    assert "Mining and curation send only" not in corpus
    assert "not independently secret-stripped" not in corpus
    assert "Each time Claude" not in corpus
    assert "your Claude subscription or API key" not in corpus
    assert "send bounded, redacted inputs" not in corpus
    assert "bounded provider inputs" not in corpus
    assert "Provider-bound prompts are bounded" not in corpus
    assert "curation inputs are bounded" not in corpus
    assert "bounded mining, curation" not in corpus
    assert "nothing leaves" not in corpus.lower()
    assert not re.search(
        r"nothing leaves.{0,160}(?:unless|except).*backups?", corpus, re.I | re.S
    )
    assert not re.search(
        r"all provider(?:-bound)? inputs (?:are|remain) redacted", corpus, re.I
    )


def test_privacy_role_matrix_includes_checkpoint_writer_grants():
    privacy = Path("docs/07-privacy-and-cost.md").read_text()
    writer_row = next(line for line in privacy.splitlines() if "| `rag_writer` |" in line)
    assert "`SELECT`/`INSERT`/`UPDATE`" in writer_row
    assert "`continuation_checkpoints`" in writer_row


def _backlog_item(number: str) -> str:
    backlog = Path("BACKLOG.md").read_text()
    match = re.search(
        rf"^- [⬜🔵✅🔒⏸] \*\*{re.escape(number)}\*\*.*?(?=^- [⬜🔵✅🔒⏸] \*\*\d+\.\d+\*\*|\Z)",
        backlog,
        re.M | re.S,
    )
    assert match, f"missing backlog item {number}"
    return match.group(0)


def test_working_with_memory_matches_completed_pin_security_boundary():
    chapter = " ".join(
        Path("docs/04-working-with-memory.md").read_text().split()
    )
    pin_security = _backlog_item("0.0")

    assert pin_security.startswith("- ✅ **0.0**")
    assert (
        "secret-strips a provider-bound copy of each matching pin body "
        "without mutating stored pin text"
    ) in chapter
    assert "backlog 0.0 is complete" in chapter


def test_rollout_backlog_records_are_actionable_and_ordered_first():
    backlog = Path("BACKLOG.md").read_text()
    assert backlog.index("**0.0**") < backlog.index("**0.1**")
    assert backlog.index("**0.1**") < backlog.index("**1.1**")
    for number, task in (("0.0", "Secret-strip"), ("0.1", "Task 9")):
        item = _backlog_item(number)
        assert item.startswith(f"- ✅ **{number}**")
        assert task in item
        assert "completed 2026-09-03" in item

    rollout = _backlog_item("0.2")
    assert rollout.startswith("- 🔵 **0.2**")
    assert "deployment completed on 2026-09-03" in rollout
    assert "Why not done:" in rollout
    assert "Trigger:" in rollout
    assert "Dependency:" in rollout
    assert "interactive Codex sessions" in " ".join(rollout.split())
    assert re.search(r"\*\([SMLX]+\)\*", rollout)
    assert re.search(
        r"^- ✅ \*\*2\.2\*\*.*Refute/reactivation evidence epoch",
        backlog,
        re.M,
    )

    pin_security = _backlog_item("0.0")
    assert "provider-bound pin bodies" in pin_security
    assert "without mutating stored pin text" in " ".join(pin_security.split())


def test_feature_registry_and_numbered_backlog_exist():
    assert Path("FEATURES.md").is_file()
    features = Path("FEATURES.md").read_text()
    assert "Codex continuity" in features
    assert "BACKLOG 2.2" in features
    assert "refute-trigger recency semantics" in features
    normalized_features = " ".join(features.split())
    assert "secret-stripped provider-bound matching pin bodies" in normalized_features
    assert "without mutating stored pin text" in normalized_features
    assert "✅ **Pre-install review.**" in features
    assert "BACKLOG 0.0" not in features
    assert "Live verification remains pending" in normalized_features
    assert re.search(
        r"^- [⬜🔵✅🔒⏸] \*\*\d+\.\d+",
        Path("BACKLOG.md").read_text(),
        re.M,
    )


def test_codex_install_docs_separate_policy_settings_from_prompt_artifact():
    reference = Path("docs/11-reference-cli-and-mcp.md").read_text()
    assert "managed policy settings" in reference
    assert "prompt artifact path" in reference
    assert "every managed setting" not in reference


def test_comparison_distinguishes_code_shipped_from_operationally_live():
    readme = Path("README.md").read_text()
    assert "shipped and installed, live verification pending" in readme
    assert re.search(
        r"^\| Codex session mining and continuity \| 🧪 \| ❌ you feed it \|$",
        readme,
        re.M,
    )


def test_docs_explain_claude_continuity_contract():
    corpus = docs_text()
    assert "autoCompactWindow" in corpus and "500000" in corpus
    assert "[1m]" in corpus
    assert "compact_summary" in corpus
    assert "stdout" in corpus and "PreCompact" in corpus
    assert "10,000" in corpus or "10000" in corpus
    assert "1.5" in corpus and "SessionEnd" in corpus
    assert "handoff" in corpus
    assert "rag install --check" in corpus
    assert "rag install --restore" in corpus
    assert "Claude auto-memory" in corpus or "auto-memory" in corpus
    assert "00-whats-new-in-0.4.md" in Path("docs/README.md").read_text()
    assert "## [Unreleased]" in Path("CHANGELOG.md").read_text()
    assert "Claude continuity" in Path("FEATURES.md").read_text()
