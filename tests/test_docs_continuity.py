import re
from pathlib import Path


DOC_PATHS = (
    Path("README.md"),
    Path("docs/01-what-is-agentic-rag.md"),
    Path("docs/02-mental-model.md"),
    Path("docs/03-quick-start.md"),
    Path("docs/05-session-mining-and-curation.md"),
    Path("docs/06-configuration-reference.md"),
    Path("docs/07-privacy-and-cost.md"),
    Path("docs/10-architecture.md"),
    Path("docs/11-reference-cli-and-mcp.md"),
    Path("docs/12-contributing.md"),
    Path("docs/README.md"),
)


def docs_text() -> str:
    return "\n".join(path.read_text() for path in DOC_PATHS)


def test_docs_explain_memory_ownership_and_compaction_limit():
    corpus = docs_text()
    assert "600000" in corpus and "500000" in corpus
    assert "100K reserve" in corpus
    assert re.search(r"(?:above|>) (?:the official )?272K", corpus)
    assert "higher provider pricing" in corpus
    assert "native Codex memories" in corpus
    assert "agentic-rag" in corpus and "canonical" in corpus
    assert "PostCompact cannot inject context" in corpus
    assert 'SessionStart(source="compact")' in corpus
    assert "same-session checkpoint wins regardless of project metadata" in corpus
    assert "compact never falls back to another session or project" in corpus


def test_docs_disclose_external_provider_calls_and_rollout_boundary():
    corpus = docs_text()
    readme = Path("README.md").read_text()
    privacy = Path("docs/07-privacy-and-cost.md").read_text()
    for outbound_summary in (readme, privacy):
        assert "checkpoint enrichment" in outbound_summary
        assert "mining, curation, and" in outbound_summary
    assert "disable_on_external_context = false" in privacy
    assert "live rollout pending" in corpus
    assert "Only LLM-assisted mining and curation" not in corpus
    assert "Mining and curation send only" not in corpus
    assert "Each time Claude" not in corpus
    assert "your Claude subscription or API key" not in corpus


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


def test_rollout_backlog_records_are_actionable_and_ordered_first():
    backlog = Path("BACKLOG.md").read_text()
    assert backlog.index("**0.1**") < backlog.index("**1.1**")
    for number, task, status in (("0.1", "Task 9", "⬜"), ("0.2", "Task 10", "🔒")):
        item = _backlog_item(number)
        assert item.startswith(f"- {status} **{number}**")
        assert task in item
        assert "Why not done:" in item
        assert "Trigger:" in item
        assert "Dependency:" in item
        assert re.search(r"\*\([SMLX]+\)\*", item)

    assert "Task 8 is landed" in _backlog_item("0.1")
    assert re.search(
        r"^- ⬜ \*\*2\.2\*\*.*Refute-trigger checks existence, not recency",
        backlog,
        re.M,
    )


def test_feature_registry_and_numbered_backlog_exist():
    assert Path("FEATURES.md").is_file()
    features = Path("FEATURES.md").read_text()
    assert "Codex continuity" in features
    assert "BACKLOG 2.2" in features
    assert "refute-trigger recency semantics" in features
    assert "live rollout pending" in features
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
    assert "shipped in code, live rollout pending" in readme
    assert "Codex session mining and continuity" in readme
