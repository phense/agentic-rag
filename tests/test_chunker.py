import re

from agentic_rag.chunker import chunk_markdown, slugify

_HEADINGS_ONLY = re.compile(r"(?:#{1,6} [^\n]*\n*)+")


def test_heading_inside_fence_is_not_a_boundary():
    fence = "```\n# not a heading\ncode line\n```\n"
    body = ("word " * 900) + "\n\n" + fence + "\n\n" + ("word " * 900)
    chunks = chunk_markdown(body)
    with_fence = [c for c in chunks if "# not a heading" in c]
    assert len(with_fence) == 1
    assert with_fence[0].count("```") == 2  # fence stayed intact in one chunk


def test_stacked_headings_attach_to_following_text():
    section = "# A\n\n## B\n\n" + ("text " * 250) + "\n\n"
    chunks = chunk_markdown(section * 5)
    assert all(not _HEADINGS_ONLY.fullmatch(c) for c in chunks)


def test_trailing_bare_heading_merges_backward():
    body = ("p\n\n" * 2500) + "# lonely"
    chunks = chunk_markdown(body)
    assert chunks[-1].endswith("# lonely")
    assert len(chunks[-1]) > len("# lonely")


def test_all_characters_preserved_with_fences():
    body = ("intro\n\n```py\n# x\n\n\ny=1\n```\n\n# H\n\n" +
            "tail " * 1200)
    assert "".join(chunk_markdown(body)) == body


def test_short_doc_is_single_chunk():
    body = "# Title\n\nA short concept page."
    assert chunk_markdown(body) == [body]


def test_long_doc_splits_at_headings():
    sec = "## H\n\n" + ("word " * 300).strip()  # ~1500 chars per section
    body = "\n\n".join([sec, sec, sec, sec])
    chunks = chunk_markdown(body, target=1000, hard_max=4000)
    assert len(chunks) >= 2
    assert all(len(c) <= 4000 for c in chunks)
    # lossless: exact reconstruction, not just word survival
    assert "".join(chunks) == body
    # headings stay attached to their section body — no heading-only chunks
    assert all(not re.fullmatch(r"#{1,6} [^\n]*\n*", c) for c in chunks)


def test_giant_paragraph_is_hard_split():
    body = "x" * 9000  # no structure at all
    chunks = chunk_markdown(body, target=1000, hard_max=4000)
    assert all(len(c) <= 4000 for c in chunks)
    assert "".join(chunks) == body


def test_slugify_basic():
    assert slugify("Photosynthesis in Green Plants!") == \
        "photosynthesis-in-green-plants"


def test_slugify_umlauts_and_length():
    s = slugify("Über-Größe: ein extrem langer Titel " * 5)
    assert len(s) <= 80
    assert " " not in s and s == s.lower()
    assert s.strip("-") == s
