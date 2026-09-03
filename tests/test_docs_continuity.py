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
    assert "native Codex memories" in corpus
    assert "agentic-rag" in corpus and "canonical" in corpus
    assert "SessionStart" in corpus and "PostCompact" in corpus


def test_feature_registry_and_numbered_backlog_exist():
    assert Path("FEATURES.md").is_file()
    assert "Codex continuity" in Path("FEATURES.md").read_text()
    assert re.search(
        r"^- [⬜🔵✅🔒⏸] \*\*\d+\.\d+",
        Path("BACKLOG.md").read_text(),
        re.M,
    )
