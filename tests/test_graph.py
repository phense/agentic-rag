import pytest

from agentic_rag import graph, store
from agentic_rag.config import Config
from agentic_rag.store import EdgeSpec


def _cfg():
    return Config(db_name="agentic_rag_test", ollama_url="http://localhost:1")


@pytest.fixture
def net(conn):
    """photosynthesis -> chlorophyll -> chloroplast ; photosynthesis -> sunlight
    (chain for depth/path tests)."""
    conn.execute("INSERT INTO domains(name) VALUES ('nature')")
    conn.commit()
    ids = {}
    for slug, title in [("chlorophyll", "Chlorophyll"),
                        ("chloroplast", "Chloroplast"), ("sunlight", "Sunlight")]:
        ids[slug] = store.save_document(conn, _cfg(), title=title, body="x",
                                        domain="nature", dtype="concept",
                                        slug=slug).doc_id
    ids["photosynthesis"] = store.save_document(
        conn, _cfg(), title="Photosynthesis", body="x", domain="nature",
        dtype="concept",
        edges=[EdgeSpec("depends_on", "chlorophyll", confidence="high"),
               EdgeSpec("references", "sunlight")],
    ).doc_id
    store.save_document(
        conn, _cfg(), title="Chlorophyll", body="x", domain="nature",
        dtype="concept", doc_id=ids["chlorophyll"],
        edges=[EdgeSpec("extends", "chloroplast")],
    )
    return conn, ids


def test_neighbors_depth_1(net):
    conn, ids = net
    hops = graph.neighbors(conn, ids["photosynthesis"], depth=1)
    slugs = {h.dst_id for h in hops} | {h.src_id for h in hops}
    assert ids["chlorophyll"] in slugs and ids["sunlight"] in slugs
    assert all(h.depth == 1 for h in hops)
    assert ids["chloroplast"] not in slugs  # 2 hops away


def test_neighbors_depth_2_reaches_chloroplast(net):
    conn, ids = net
    hops = graph.neighbors(conn, ids["photosynthesis"], depth=2)
    touched = {h.dst_id for h in hops} | {h.src_id for h in hops}
    assert ids["chloroplast"] in touched


def test_neighbors_predicate_filter(net):
    conn, ids = net
    hops = graph.neighbors(conn, ids["photosynthesis"], depth=1,
                           predicates=["depends_on"])
    assert len(hops) == 1 and hops[0].predicate == "depends_on"


def test_path_photosynthesis_to_chloroplast(net):
    conn, ids = net
    steps = graph.path(conn, ids["photosynthesis"], ids["chloroplast"])
    assert [s.doc_id for s in steps] == [ids["photosynthesis"],
                                         ids["chlorophyll"],
                                         ids["chloroplast"]]
    assert steps[0].via_predicate is None
    assert steps[1].via_predicate == "depends_on"
    assert steps[2].via_predicate == "extends"


def test_path_none_when_unreachable(net):
    conn, ids = net
    lonely = store.save_document(conn, _cfg(), title="Lonely", body="x",
                                 domain="nature", dtype="concept").doc_id
    assert graph.path(conn, ids["photosynthesis"], lonely) == []


def test_timeline_orders_by_valid_from(net):
    conn, ids = net
    edges = graph.timeline(conn, ids["photosynthesis"])
    assert len(edges) == 2
    assert edges == sorted(edges, key=lambda e: e.valid_from)
