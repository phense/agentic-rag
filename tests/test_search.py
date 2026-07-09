import pytest

from agentic_rag import search as search_mod
from agentic_rag import store
from agentic_rag.config import Config


def _no_embed_cfg():
    return Config(db_name="agentic_rag_test", ollama_url="http://localhost:1")


@pytest.fixture
def corpus(conn):
    conn.execute("INSERT INTO domains(name) VALUES ('nature'), ('programming')")
    conn.commit()
    cfg = _no_embed_cfg()
    store.save_document(conn, cfg, title="Photosynthesis",
                        body="Leaves convert sunlight into chemical energy.",
                        domain="nature", dtype="concept")
    store.save_document(conn, cfg, title="Pytest Fixtures",
                        body="Fixtures inject test dependencies.",
                        domain="programming", dtype="lesson")
    # German doc: exercises the tsv_de stemmer — the query below hits it only
    # if German stemming matches the inflected forms (Pflanze/Pflanzen).
    store.save_document(conn, cfg, title="Gartenpflege im Winter",
                        body="Pflanzen im Garten brauchen im Winter besonderen Schutz.",
                        domain="nature", dtype="memory")
    return conn


def test_fulltext_english_hit(corpus):
    hits, warnings = search_mod.search(corpus, _no_embed_cfg(), "convert sunlight")
    assert hits and hits[0].slug == "photosynthesis"
    assert any("embedding" in w for w in warnings)  # Ollama down -> visible warning


def test_fulltext_german_hit(corpus):
    hits, _ = search_mod.search(corpus, _no_embed_cfg(), "Pflanze Garten")
    assert hits and hits[0].slug == "gartenpflege-im-winter"


def test_domain_filter(corpus):
    # positive control: the query DOES match in its own domain …
    hits, _ = search_mod.search(corpus, _no_embed_cfg(), "fixtures",
                                domain="programming")
    assert hits and hits[0].slug == "pytest-fixtures"
    # … so an empty result under the wrong-domain filter is meaningful
    hits, _ = search_mod.search(corpus, _no_embed_cfg(), "fixtures",
                                domain="nature")
    assert hits == []


def test_archived_documents_excluded(corpus):
    hits, _ = search_mod.search(corpus, _no_embed_cfg(), "convert sunlight")
    assert hits and hits[0].slug == "photosynthesis"   # found while active
    corpus.execute(
        "UPDATE documents SET status='archived' WHERE slug='photosynthesis'")
    corpus.commit()
    hits, _ = search_mod.search(corpus, _no_embed_cfg(), "convert sunlight")
    assert all(h.slug != "photosynthesis" for h in hits)


def test_vector_search_with_fake_embeddings(corpus, cfg, monkeypatch):
    # give every chunk the same non-null embedding, query with a matching
    # vector: the vector branch must return ALL three docs even with zero
    # text overlap, deterministically tie-broken by slug
    vec = "[" + ",".join(["0.1"] * 1024) + "]"
    corpus.execute("UPDATE chunks SET embedding = %s::halfvec", (vec,))
    corpus.commit()
    monkeypatch.setattr(
        "agentic_rag.search.try_embed_texts", lambda texts, cfg: [[0.1] * 1024]
    )
    hits, warnings = search_mod.search(corpus, cfg, "zzz-no-text-match-zzz")
    assert {h.slug for h in hits} == {"photosynthesis", "pytest-fixtures",
                                      "gartenpflege-im-winter"}
    assert warnings == []
