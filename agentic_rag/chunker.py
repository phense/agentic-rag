"""Structural markdown chunking (headings > paragraphs > hard split) + slugify."""
from __future__ import annotations

import re
import unicodedata

_HEADING = re.compile(r"^#{1,6} ", re.MULTILINE)
_HEADING_ONLY = re.compile(r"(?:#{1,6} [^\n]*\n*)+")  # also stacked headings
_FENCE_OPEN = re.compile(r"^(`{3,}|~{3,})", re.MULTILINE)


def _fence_spans(body: str) -> list[tuple[str, bool]]:
    """Split into (text, is_fenced) spans. A fence opens with ```/~~~ at line
    start and closes with at least the same marker on its own line; an
    unclosed fence runs to the end of the text. Preserves all characters."""
    spans: list[tuple[str, bool]] = []
    pos = 0
    while True:
        m = _FENCE_OPEN.search(body, pos)
        if m is None:
            break
        close = re.search(rf"^{re.escape(m.group(1))}[`~]*[ \t]*$",
                          body[m.end():], re.MULTILINE)
        end = m.end() + close.end() if close else len(body)
        nl = body.find("\n", end)
        end = len(body) if nl == -1 else nl + 1
        if m.start() > pos:
            spans.append((body[pos:m.start()], False))
        spans.append((body[m.start():end], True))
        pos = end
    if pos < len(body):
        spans.append((body[pos:], False))
    return spans


def _split_blocks(body: str) -> list[str]:
    """Split at headings, then blank lines — never inside a code fence.
    Preserves all characters."""
    parts: list[str] = []
    for span, fenced in _fence_spans(body):
        if fenced:
            parts.append(span)
            continue
        idx = [m.start() for m in _HEADING.finditer(span)]
        bounds = [0] + [i for i in idx if i != 0] + [len(span)]
        for a, b in zip(bounds, bounds[1:]):
            section = span[a:b]
            parts.extend(p for p in re.split(r"(?<=\n\n)", section) if p)
    return parts


def chunk_markdown(body: str, target: int = 1000, hard_max: int = 4000) -> list[str]:
    if len(body) <= hard_max:
        return [body] if body else []
    # a heading block always stays attached to its section body — an isolated
    # heading chunk carries no retrievable content and strips context from
    # the section it introduced
    blocks: list[str] = []
    for b in _split_blocks(body):
        if blocks and _HEADING_ONLY.fullmatch(blocks[-1]):
            blocks[-1] += b
        else:
            blocks.append(b)
    if len(blocks) > 1 and _HEADING_ONLY.fullmatch(blocks[-1]):
        trailing = blocks.pop()
        blocks[-1] += trailing
    chunks: list[str] = []
    current = ""
    for block in blocks:
        while len(block) > hard_max:  # pathological: no structure
            if current:
                chunks.append(current)
                current = ""
            chunks.append(block[:hard_max])
            block = block[hard_max:]
        if current and len(current) + len(block) > target:
            chunks.append(current)
            current = block
        else:
            current += block
    if current:
        chunks.append(current)
    return chunks


def slugify(title: str, max_len: int = 80) -> str:
    s = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:max_len].rstrip("-")
