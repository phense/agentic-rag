from agentic_rag import domains


def test_add_domain_upserts_and_audits(conn):
    domains.add_domain(conn, "nature", "field observations")
    domains.add_domain(conn, "nature", "updated description")
    rows = conn.execute(
        "SELECT description FROM domains WHERE name = 'nature'").fetchall()
    assert rows == [{"description": "updated description"}]
    audits = conn.execute(
        "SELECT count(*) AS n FROM audit_log WHERE op = 'domain_add'"
    ).fetchone()
    assert audits["n"] == 2


def test_list_domains_includes_doc_counts(conn):
    domains.add_domain(conn, "a", "first")
    domains.add_domain(conn, "b", "second")
    conn.execute(
        "INSERT INTO documents(slug, domain, dtype, title) "
        "VALUES ('d1', 'a', 'memory', 'D1')")
    conn.commit()
    infos = {d.name: d for d in domains.list_domains(conn)}
    assert infos["a"].docs == 1
    assert infos["b"].docs == 0
    assert infos["a"].description == "first"


def test_seed_defaults_creates_general(conn):
    from agentic_rag import domains as domains_mod
    domains_mod.seed_defaults(conn)
    names = {d.name for d in domains_mod.list_domains(conn)}
    assert "general" in names
    # idempotent — a second call neither errors nor duplicates
    domains_mod.seed_defaults(conn)
    assert sum(1 for d in domains_mod.list_domains(conn)
               if d.name == "general") == 1
