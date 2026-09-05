import json

from agentic_rag import mining, pins
from agentic_rag.config import Config
from agentic_rag.store import EdgeSpec, get_document

DOMAINS = ["programming", "nature"]


def test_schema_constrains_domains_and_predicates():
    schema = mining.build_schema(DOMAINS)
    mem = schema["properties"]["memories"]["items"]
    assert mem["properties"]["domain"]["enum"] == DOMAINS
    edge = mem["properties"]["edges"]["items"]
    assert "duplicate_of" in edge["properties"]["predicate"]["enum"]
    assert schema["required"] == list(schema["properties"].keys())
    # pins have no slug/domain — spec §6.3 requires their own channel
    pin_c = schema["properties"]["contradictions_with_pins"]["items"]
    assert set(pin_c["required"]) == {"pin", "statement", "quote"}


def test_prompt_contains_digest_domains_and_pins():
    p = mining.build_prompt("THE DIGEST", DOMAINS, ["pin rule 1"])
    assert "THE DIGEST" in p
    assert "programming" in p and "nature" in p
    assert "pin rule 1" in p
    assert "contradict" in p.lower()          # the contradiction question


def _raw(**over):
    base = {"memories": [], "lessons": [], "signals": [],
            "pin_suggestions": [], "contradictions": [],
            "contradictions_with_pins": [], "domain_proposals": []}
    base.update(over)
    return base


def test_parse_drops_unknown_domain_and_incomplete_items():
    data = _raw(memories=[
        {"title": "Good", "body": "b", "domain": "programming", "edges": []},
        {"title": "Bad domain", "body": "b", "domain": "invented", "edges": []},
        {"title": "", "body": "b", "domain": "programming", "edges": []},
    ])
    ext = mining.parse_extraction(data, set(DOMAINS))
    assert [m.title for m in ext.memories] == ["Good"]


def test_parse_edge_evidence_empty_string_becomes_none():
    # BACKLOG gate: EdgeSpec must receive None, never "" — the store's
    # COALESCE guard only protects NULL evidence from being clobbered
    data = _raw(lessons=[{
        "title": "L", "body": "b", "domain": "nature",
        "edges": [{"predicate": "references", "dst_slug": "x",
                   "evidence": "", "confidence": None}],
    }])
    ext = mining.parse_extraction(data, set(DOMAINS))
    assert ext.lessons[0].edges == [
        EdgeSpec("references", "x", evidence=None, confidence=None)]


def test_parse_signal_requires_signal_text():
    data = _raw(signals=[
        {"title": "S", "body": "b", "domain": "programming",
         "signal": "jetsam killed", "edges": []},
        {"title": "no signal", "body": "b", "domain": "programming",
         "signal": "", "edges": []},
    ])
    ext = mining.parse_extraction(data, set(DOMAINS))
    assert [s.title for s in ext.signals] == ["S"]
    assert ext.signals[0].signal == "jetsam killed"


def test_parse_caps_each_list():
    data = _raw(memories=[{"title": f"m{i}", "body": "b",
                           "domain": "nature", "edges": []}
                          for i in range(30)])
    ext = mining.parse_extraction(data, set(DOMAINS))
    assert len(ext.memories) == mining.MAX_ITEMS_PER_KIND


def test_parse_contradiction_with_unknown_domain_is_dropped():
    # grounded-or-dropped for the contradictions channel too — an invalid
    # domain must never reach save_document (it would abort the whole job)
    data = _raw(contradictions=[
        {"slug": "x", "statement": "s", "quote": "q", "domain": "invented"},
        {"slug": "y", "statement": "s", "quote": "q", "domain": "nature"},
    ])
    ext = mining.parse_extraction(data, set(DOMAINS))
    assert [c["slug"] for c in ext.contradictions] == ["y"]


def _no_embed_cfg():
    return Config(db_name="agentic_rag_test", ollama_url="http://localhost:1")


def _seed_domains(conn):
    conn.execute("INSERT INTO domains(name, description) VALUES"
                 " ('programming', 'code'), ('nature', 'field observations')")
    conn.commit()


def _runner_returning(payload):
    def runner(cmd, **kw):
        class P:
            returncode, stderr = 0, ""
            stdout = json.dumps(payload)
        return P()
    return runner


def _transcript(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text(json.dumps({
        "uuid": "u1", "type": "user",
        "message": {"role": "user", "content": "we learned a thing"}}) + "\n")
    return str(p)


def test_mine_session_redacts_all_matching_pin_kinds_without_mutating_them(
        conn, tmp_path):
    _seed_domains(conn)
    project = "/Users/example/Agents/agentic-rag"
    global_secret = "sk-abcdefghijklmnop1234"
    path_secret = "api_key=abcdefghijklmnop"
    document_secret = "Bearer abcdef1234567890abcdef"

    global_id = pins.add_pin(
        conn, body=f"Never send {global_secret}.")
    path_id = pins.add_pin(
        conn, body=f"Keep {path_secret} local.", scope=project)
    doc = conn.execute(
        "INSERT INTO documents(slug, domain, dtype, title, body) VALUES"
        " ('private-rule', 'programming', 'lesson', %s, 'fixture')"
        " RETURNING id",
        (f"Authorization: {document_secret}",)).fetchone()
    conn.commit()
    document_id = pins.add_pin(conn, document_id=str(doc["id"]))
    original = {
        str(row["id"]): row["body"]
        for row in conn.execute(
            "SELECT id, body FROM pins WHERE id = ANY(%s::uuid[])",
            ([global_id, path_id, document_id],)).fetchall()
    }

    seen = {}

    def runner(cmd, **kwargs):
        seen["prompt"] = cmd[cmd.index("-p") + 1]

        class P:
            returncode, stderr = 0, ""
            stdout = json.dumps(_raw())

        return P()

    mining.mine_session(
        conn, _no_embed_cfg(), session_id="pin-redaction",
        transcript_path=_transcript(tmp_path), last_uuid=None,
        project=f"{project}/subdir", runner=runner)

    prompt = seen["prompt"]
    assert global_secret not in prompt
    assert path_secret not in prompt
    assert document_secret not in prompt
    assert prompt.count("[REDACTED]") >= 3
    stored = {
        str(row["id"]): row["body"]
        for row in conn.execute(
            "SELECT id, body FROM pins WHERE id = ANY(%s::uuid[])",
            ([global_id, path_id, document_id],)).fetchall()
    }
    assert stored == original


def test_mine_session_saves_items_with_provenance(conn, tmp_path):
    _seed_domains(conn)
    payload = _raw(
        memories=[{"title": "Fact One", "body": "body one",
                   "domain": "programming", "edges": []}],
        signals=[{"title": "Jetsam OOM", "body": "watch for jetsam",
                  "domain": "programming", "signal": "jetsam killed process",
                  "edges": []}])
    res = mining.mine_session(
        conn, _no_embed_cfg(), session_id="sess-1",
        transcript_path=_transcript(tmp_path),
        last_uuid=None, project="/proj", runner=_runner_returning(payload))
    assert res.saved == 2
    from agentic_rag.mining_window import read_window
    assert read_window(_transcript(tmp_path), after_uuid=res.new_last_uuid).text == ""
    doc = get_document(conn, "fact-one")
    assert doc["dtype"] == "memory"
    assert doc["provenance"]["origin"] == "session-mining"
    assert doc["provenance"]["session_id"] == "sess-1"
    assert doc["provenance"]["project"] == "/proj"
    sig = get_document(conn, "jetsam-oom")
    assert sig["dtype"] == "signal"
    assert "jetsam killed process" in sig["body"]     # FTS-recallable
    assert sig["meta"]["signal"] == "jetsam killed process"


def test_mine_session_materializes_contradictions(conn, tmp_path):
    _seed_domains(conn)
    conn.execute(
        "INSERT INTO documents(slug, domain, dtype, title, body) VALUES"
        " ('old-claim', 'programming', 'memory', 'Old claim', 'wrong thing')")
    conn.commit()
    payload = _raw(contradictions=[{
        "slug": "old-claim", "statement": "the session showed X is false",
        "quote": "user: X is actually false", "domain": "programming"}])
    res = mining.mine_session(
        conn, _no_embed_cfg(), session_id="s2",
        transcript_path=_transcript(tmp_path),
        last_uuid=None, project=None, runner=_runner_returning(payload))
    assert res.contradictions == 1
    contra = get_document(conn, "contradiction-old-claim")
    assert contra is not None
    out = {(e.predicate, e.peer_slug) for e in contra["edges_out"]}
    assert ("contradicts", "old-claim") in out


def test_mine_session_records_suggestions_as_audit_rows(conn, tmp_path):
    _seed_domains(conn)
    payload = _raw(
        pin_suggestions=[{"body": "always run tests", "scope": "global",
                          "reason": "user said so"}],
        domain_proposals=[{"name": "devops", "description": "infra",
                           "reason": "no fit"}])
    res = mining.mine_session(
        conn, _no_embed_cfg(), session_id="s3",
        transcript_path=_transcript(tmp_path),
        last_uuid=None, project=None, runner=_runner_returning(payload))
    assert res.pin_suggestions == 1 and res.domain_proposals == 1
    ops = [r["op"] for r in conn.execute(
        "SELECT op FROM audit_log ORDER BY id").fetchall()]
    assert "pin_suggestion" in ops and "domain_proposal" in ops
    assert conn.execute(
        "SELECT count(*) AS n FROM pins").fetchone()["n"] == 0   # never auto-pin


def test_mine_session_records_pin_contradictions(conn, tmp_path):
    # spec §6.3 contradictions_with_pins: pins are automation-exempt, so the
    # ONLY output is an audit row surfaced by rag review — no doc, no edge,
    # and never a pin change
    _seed_domains(conn)
    payload = _raw(contradictions_with_pins=[{
        "pin": "Never skip the calibration step.",
        "statement": "the session skipped calibration and the user approved",
        "quote": "user: skip the calibration here"}])
    res = mining.mine_session(
        conn, _no_embed_cfg(), session_id="s6",
        transcript_path=_transcript(tmp_path),
        last_uuid=None, project=None, runner=_runner_returning(payload))
    assert res.pin_contradictions == 1
    assert res.saved == 0                              # no document created
    row = conn.execute(
        "SELECT summary FROM audit_log WHERE op = 'pin_contradiction'"
    ).fetchone()
    assert "calibration" in row["summary"]
    assert conn.execute("SELECT count(*) AS n FROM pins").fetchone()["n"] == 0


def test_mine_session_dedup_records_duplicate_of_edge(conn, tmp_path,
                                                      monkeypatch):
    _seed_domains(conn)
    existing = conn.execute(
        "INSERT INTO documents(slug, domain, dtype, title, body) VALUES"
        " ('known-fact', 'programming', 'memory', 'Known fact', 'the body')"
        " RETURNING id").fetchone()
    conn.execute(
        "INSERT INTO chunks(document_id, idx, content, embedding)"
        " VALUES (%s, 0, 'the body', %s::halfvec)",
        (existing["id"], "[" + ",".join(["0.1"] * 1024) + "]"))
    conn.commit()
    # the dedup PROBE gets a matching vector (cosine similarity 1.0); the
    # save path inside still runs on the dead-port cfg (NULL embeddings)
    monkeypatch.setattr(mining, "try_embed_texts",
                        lambda texts, cfg: [[0.1] * 1024 for _ in texts])
    payload = _raw(memories=[{"title": "Known fact restated",
                              "body": "the body", "domain": "programming",
                              "edges": []}])
    res = mining.mine_session(
        conn, _no_embed_cfg(), session_id="s4",
        transcript_path=_transcript(tmp_path),
        last_uuid=None, project=None, runner=_runner_returning(payload))
    assert res.saved == 1
    assert res.duplicates == 1
    doc = get_document(conn, "known-fact-restated")
    out = {(e.predicate, e.peer_slug) for e in doc["edges_out"]}
    assert ("duplicate_of", "known-fact") in out      # recorded, NOT merged


def test_mine_session_skips_synthetic_mining_transcript(conn, tmp_path):
    # Defense-in-depth for the mining cascade: a transcript whose first user
    # message IS our own mining prompt (a `claude -p` subprocess transcript)
    # must be skipped — no Haiku call, no garbage doc. The llm.py kill switch
    # stops NEW ones enqueuing; this drains any already-queued backlog safely.
    # A real session that merely DISCUSSES mining has a different first turn.
    _seed_domains(conn)
    synth = tmp_path / "synthetic.jsonl"
    synth.write_text(json.dumps({
        "uuid": "u1", "type": "user",
        "message": {"role": "user", "content":
                    "SESSION DIGEST (user/assistant prose + tool names; "
                    "tool outputs omitted):\n[user] nested content"}}) + "\n")
    def exploding_runner(cmd, **kw):
        raise AssertionError("LLM must not run for a synthetic transcript")
    res = mining.mine_session(
        conn, _no_embed_cfg(), session_id="synth-1",
        transcript_path=str(synth),
        last_uuid=None, project=None, runner=exploding_runner)
    assert res.saved == 0
    assert res.skipped == "synthetic mining transcript"


def test_mine_session_mines_real_session_that_mentions_digest(conn, tmp_path):
    # Guard must NOT over-trigger: a real session whose first turn merely talks
    # about digests is mined normally (marker must be the FIRST prose line).
    _seed_domains(conn)
    real = tmp_path / "real.jsonl"
    real.write_text(json.dumps({
        "uuid": "u1", "type": "user",
        "message": {"role": "user", "content":
                    "the SESSION DIGEST truncation bug — let's debug it"}}) + "\n")
    payload = _raw(memories=[{"title": "Debug Fact", "body": "b",
                              "domain": "programming", "edges": []}])
    res = mining.mine_session(
        conn, _no_embed_cfg(), session_id="real-1", transcript_path=str(real),
        last_uuid=None, project=None, runner=_runner_returning(payload))
    assert res.skipped is None
    assert res.saved == 1


def test_mine_session_empty_digest_skips_without_llm_call(conn, tmp_path):
    _seed_domains(conn)
    empty = tmp_path / "e.jsonl"
    empty.write_text("")
    def exploding_runner(cmd, **kw):
        raise AssertionError("LLM must not be called for an empty digest")
    res = mining.mine_session(
        conn, _no_embed_cfg(), session_id="s5", transcript_path=str(empty),
        last_uuid=None, project=None, runner=exploding_runner)
    assert res.saved == 0
    assert res.skipped == "empty digest"
