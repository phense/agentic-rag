"""The `rag` CLI — thin argparse layer over the library."""
from __future__ import annotations

import argparse
import dataclasses
import json
import shlex
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg

from . import backup as backup_mod
from . import curation as curation_mod
from . import db, jobs as jobs_mod, search as search_mod, store
from . import domains as domains_mod
from . import embed
from . import install as install_mod
from . import maintenance as maintenance_mod
from . import migration as migration_mod
from . import pins as pins_mod
from . import status as status_mod
from . import worker as worker_mod
from .config import load_config
from .secrets import strip_secrets
from .store import EdgeSpec


def _json_default(o):
    if dataclasses.is_dataclass(o):
        return dataclasses.asdict(o)
    return str(o)  # UUID, datetime, Path


def _safe(value: object) -> str:
    return strip_secrets(str(value))[0]


def _safe_excerpt(value: object, max_chars: int) -> str:
    return _safe(value)[:max_chars]


def _format_age(value) -> str:
    seconds = max(0, int(value.total_seconds()))
    if seconds >= 86400:
        return f"{seconds // 86400}d"
    if seconds >= 3600:
        return f"{seconds // 3600}h"
    if seconds >= 60:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def _main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="rag")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db")

    p_inst = sub.add_parser("install")
    p_inst.add_argument("--no-launchd", action="store_true")
    p_inst.add_argument("--codex", action="store_true",
                        help="target Codex config and lifecycle hooks")
    p_inst.add_argument("--check", action="store_true",
                        help="show the changes without writing files")
    p_inst.add_argument("--restore", type=Path, default=None,
                        metavar="ROLLBACK_RECORD",
                        help="restore a recorded Claude or Codex installation")
    p_inst.add_argument("--codex-home", type=Path, default=None,
                        help=argparse.SUPPRESS)

    p_dom = sub.add_parser("domain")
    dom_sub = p_dom.add_subparsers(dest="domain_cmd", required=True)
    d_add = dom_sub.add_parser("add")
    d_add.add_argument("name")
    d_add.add_argument("--description", default="")
    dom_sub.add_parser("list")

    p_save = sub.add_parser("save")
    p_save.add_argument("--project")
    p_save.add_argument("--scope", choices=["project", "global", "unknown"])
    p_save.add_argument("--title", required=True)
    p_save.add_argument("--domain", required=True)
    p_save.add_argument("--dtype", required=True)
    p_save.add_argument("--body")
    p_save.add_argument("--file", type=Path)
    p_save.add_argument("--slug", help="upsert: update the doc with this slug"
                        " if it exists, else create it with this slug")
    p_save.add_argument("--edge", action="append", default=[],
                        metavar="PREDICATE:SLUG")

    p_assert = sub.add_parser("assert", help="save one evidence-backed immutable fact")
    for name in ('entity','attribute','value','domain','source-id','quote'):
        p_assert.add_argument('--'+name,required=True)
    p_assert.add_argument('--role',choices=['user','assistant'],default='user')
    p_assert.add_argument('--event-at')
    p_assert.add_argument('--expires-at')
    p_assert.add_argument('--relation',choices=['assertion','extension','replacement'],default='assertion')
    p_assert.add_argument('--project')
    p_assert.add_argument('--scope',choices=['project','global','unknown'])

    p_get = sub.add_parser("get")
    p_get.add_argument("id_or_slug")
    p_get.add_argument("--json", action="store_true")

    p_context = sub.add_parser("context", help="bounded advisory project context")
    p_context.add_argument("--project")
    p_context.add_argument("--prompt", help="selective prompt recall; omit for startup context")
    p_context.add_argument("--session-id")
    p_context.add_argument("--json", action="store_true")
    p_profile = sub.add_parser("profile", help="rebuild a derived project profile")
    p_profile.add_argument("--project")
    p_profile.add_argument("--refresh", action="store_true", required=True)

    p_search = sub.add_parser("search")
    p_search.add_argument("query")
    p_search.add_argument("--graph-depth",type=int,choices=[0,1,2],default=0)
    p_search.add_argument("--as-of")
    p_search.add_argument("--history", action="store_true")
    p_search.add_argument("--project")
    p_search.add_argument("--scope", choices=["project", "global", "all"])
    p_search.add_argument("--domain")
    p_search.add_argument("-k", type=int, default=8)
    p_search.add_argument("--json", action="store_true")

    sub.add_parser("status")

    p_bench = sub.add_parser("benchmark", help="synthetic memory evaluation in an owned temporary database")
    bench_sub = p_bench.add_subparsers(dest="benchmark_cmd", required=True)
    b_run = bench_sub.add_parser("run")
    b_run.add_argument("--output", type=Path, required=True)
    b_run.add_argument("--corpus", type=Path)
    b_run.add_argument("--project")
    b_run.add_argument("--retrieval-baseline",action="store_true")
    b_run.add_argument("--graph-depth",type=int,choices=[0,1,2],default=0)
    b_run.add_argument("--local-rerank",action="store_true")
    b_run.add_argument("--query-expansion",action="store_true")
    b_run.add_argument("--validity-baseline", action="store_true", help="temporal fixture only: compare prior status-only eligibility")
    b_run.add_argument("--scope", choices=["project", "global", "all"])
    b_run.add_argument("--mode", choices=["retrieval", "end-to-end"], default="retrieval")
    b_run.add_argument("--search-mode", choices=["fts", "hybrid"], default="hybrid")
    b_run.add_argument("--context-chars", type=int, default=4000)
    b_run.add_argument("--split", choices=["all", "dev", "test"], default="all")
    b_run.add_argument("--limit", type=int)
    b_run.add_argument("--smoke", action="store_true", help="reduce source corpus; not a full baseline")
    b_run.add_argument("--answers", action="store_true", help="call configured LLM for answers")
    b_run.add_argument("--judge", action="store_true", help="separately call configured LLM for grading (requires --answers)")
    b_compare = bench_sub.add_parser("compare")
    b_compare.add_argument("before", type=Path)
    b_compare.add_argument("after", type=Path)

    p_queue = sub.add_parser("queue")
    queue_sub = p_queue.add_subparsers(dest="queue_cmd", required=True)
    q_requeue = queue_sub.add_parser("requeue-legacy-provider-failures")
    q_requeue.add_argument("--expect", type=int, default=60)
    q_requeue.add_argument("--yes", action="store_true")

    p_pin = sub.add_parser("pin")
    pin_sub = p_pin.add_subparsers(dest="pin_cmd", required=True)
    pa = pin_sub.add_parser("add")
    pa.add_argument("--body")
    pa.add_argument("--document")
    pa.add_argument("--scope", default="global")
    pa.add_argument("--priority", type=int, default=100)
    pin_sub.add_parser("list").add_argument("--all", action="store_true")
    pin_sub.add_parser("rm").add_argument("pin_id")
    pin_sub.add_parser("verify").add_argument("pin_id")

    p_bk = sub.add_parser("backup")
    p_bk.add_argument("--install-launchd", action="store_true")

    p_maint = sub.add_parser("maintenance")
    p_maint.add_argument("--install-launchd", action="store_true")
    p_maint.add_argument("--verify-backup", action="store_true",
                         help="force the weekly restore-test now")
    p_maint.add_argument("--no-worker", action="store_true",
                         help="skip the worker drain tick")

    p_rs = sub.add_parser("restore")
    p_rs.add_argument("dump", type=Path)
    p_rs.add_argument("--yes", action="store_true")

    sub.add_parser("review")
    p_evidence=sub.add_parser('evidence',help='audited source trust and claim review')
    es=p_evidence.add_subparsers(dest='evidence_cmd',required=True)
    ps=es.add_parser('source-state');ps.add_argument('source_key')
    ps.add_argument('--state',required=True,choices=['active','refuted','removed']);ps.add_argument('--reason',required=True)
    pr=es.add_parser('review');pr.add_argument('id_or_slug')
    pr.add_argument('--state',required=True,choices=['confirmed','unreviewed','refuted']);pr.add_argument('--reason',required=True)

    p_scope = sub.add_parser("scope", help="inspect or repair document applicability")
    ss = p_scope.add_subparsers(dest="scope_cmd", required=True)
    ss.add_parser("backfill", help="audit-map unambiguous legacy paths, retain unknowns")
    ss.add_parser("report", help="show unknown legacy applicability")
    sp = ss.add_parser("set")
    sp.add_argument("id_or_slug")
    sp.add_argument("--project")
    sp.add_argument("--scope", choices=["project", "global", "unknown"])

    p_purge = sub.add_parser("purge")
    p_purge.add_argument("--older-days", type=int, default=30)
    p_purge.add_argument("--yes", action="store_true")

    p_mig = sub.add_parser("migrate")
    mig_sub = p_mig.add_subparsers(dest="migrate_cmd", required=True)
    m_run = mig_sub.add_parser("run")
    m_run.add_argument("--source", type=Path,
                       default=Path.home() / ".ultra-memory",
                       help="an llm-wiki store: a dir with wiki/ and optional"
                            " memory.db")
    m_run.add_argument("--yes", action="store_true")
    m_run.add_argument("--dry-run", action="store_true")
    m_run.add_argument("--limit", type=int, default=None)
    m_run.add_argument("--skip-backup", action="store_true")
    mig_sub.add_parser("classify")
    m_apply = mig_sub.add_parser("apply-domains")
    m_apply.add_argument("report_tsv", type=Path)
    m_apply.add_argument("--yes", action="store_true")
    m_rep = mig_sub.add_parser("report")
    m_rep.add_argument("--golden", type=Path, default=None)

    args = p.parse_args(argv)
    if args.cmd == "install" and args.restore is not None and args.check:
        p.error("--restore and --check are mutually exclusive")
    if (args.cmd == "install" and args.codex_home is not None
            and not args.codex):
        p.error("--codex-home requires --codex")
    if (args.cmd == "install" and args.restore is not None
            and args.codex_home is not None):
        p.error("--restore reads its target home from the rollback record")
    cfg = load_config()

    if args.cmd == "context":
        from .context import build
        with db.connect(cfg,role="reader") as context_conn:
            result=build(context_conn,cfg,project=args.project,mode="prompt" if args.prompt is not None else "startup",
                         prompt=args.prompt,session_id=args.session_id,source="startup")
        print(json.dumps(result,default=_json_default,ensure_ascii=False) if args.json else result["text"])
        return 0
    if args.cmd == "profile":
        with db.connect(cfg,role="writer") as profile_conn:
            result=store.refresh_profile(profile_conn,cfg,args.project,actor="cli")
        print(json.dumps(result,default=_json_default,ensure_ascii=False))
        return 0

    if args.cmd == "benchmark":
        from .benchmark.runner import compare, run
        if args.benchmark_cmd == "compare":
            print(json.dumps(compare(json.loads(args.before.read_text()),
                                     json.loads(args.after.read_text())), indent=2))
            return 0
        report = run(cfg, output=args.output, corpus_path=args.corpus, mode=args.mode,
                     search_mode=args.search_mode, context_chars=args.context_chars,
                     split=args.split, limit=args.limit, answers=args.answers,
                     judge=args.judge, smoke=args.smoke, project=args.project, scope=args.scope, validity_baseline=args.validity_baseline,retrieval_baseline=args.retrieval_baseline,graph_depth=args.graph_depth,local_rerank=args.local_rerank,query_expansion=args.query_expansion,
                     progress=lambda message: print(message, file=sys.stderr))
        print(json.dumps(report['summary'], indent=2))
        print(f"Reports: {args.output / 'results.json'} and {args.output / 'report.md'}")
        return 3 if report['summary']['failed_queries'] or report['ingestion']['failed_sources'] else 0

    if args.cmd == "assert":
        with db.connect(cfg,role='writer') as connection:
            result=store.save_assertion(connection,cfg,entity=args.entity,attribute=args.attribute,
                value=args.value,domain=args.domain,event_at=args.event_at,expires_at=args.expires_at,
                relation=args.relation,project=args.project,scope=args.scope,
                evidence={'source_id':args.source_id,'role':args.role,'quote':args.quote})
            print(json.dumps(dataclasses.asdict(result),default=_json_default,indent=2))
        return 0

    if args.cmd == 'evidence':
        with db.connect(cfg,role='writer') as connection:
            if args.evidence_cmd=='source-state':
                store.set_source_state(connection,args.source_key,state=args.state,reason=args.reason)
            else:
                doc=store.get_document(connection,args.id_or_slug)
                if not doc:raise ValueError('document not found')
                store.review_claim(connection,str(doc['id']),state=args.state,reason=args.reason)
        print('evidence state saved')
        return 0

    if args.cmd == "scope":
        from .scope import backfill
        with db.connect(cfg, role="reader" if args.scope_cmd == "report" else "writer") as connection:
            if args.scope_cmd == "backfill":
                print(json.dumps(backfill(connection), indent=2))
            elif args.scope_cmd == "report":
                report = curation_mod.review_report(connection, cfg)
                print(json.dumps({"unknown_count": report["unknown_scope_count"], "unknown": report["unknown_scopes"]}, default=_json_default, indent=2))
            else:
                doc = store.get_document(connection, args.id_or_slug)
                if doc is None:
                    raise ValueError("document not found")
                store.set_project_scope(connection, str(doc["id"]), project=args.project, scope=args.scope)
                print("scope saved")
        return 0

    if args.cmd == "init-db":
        applied = db.init_db(cfg)
        print("applied:", ", ".join(applied) or "(none — up to date)")
        return 0

    if args.cmd == "backup":
        if args.install_launchd:
            if sys.platform != "darwin":
                print("launchd is macOS-only; on Linux schedule 'rag backup'"
                      " via cron or a systemd timer"
                      " (see docs/deploy/scheduling-linux.md)", file=sys.stderr)
                return 1
            rag_bin = Path(shutil.which("rag") or sys.argv[0]).resolve()
            plist = backup_mod.install_launchd(cfg, rag_bin)
            print(f"launchd installed: {plist}")
        res = backup_mod.run_backup(cfg)
        print(f"local:  {res.local_path}")
        print(f"cloud:  {res.cloud_path or '—'}")
        for w in res.warnings:
            print(f"WARNING: {w}", file=sys.stderr)
        return 0

    if args.cmd == "restore":
        if not args.yes:
            print("refusing without --yes", file=sys.stderr)
            return 1
        backup_mod.restore(cfg, args.dump, assume_yes=True)
        print("restored.")
        return 0

    if args.cmd == "maintenance":
        if args.install_launchd:
            if sys.platform != "darwin":
                print("launchd is macOS-only; on Linux schedule 'rag maintenance'"
                      " via cron or a systemd timer"
                      " (see docs/deploy/scheduling-linux.md)", file=sys.stderr)
                return 1
            rag_bin = Path(shutil.which("rag") or sys.argv[0]).resolve()
            plist = maintenance_mod.install_launchd(cfg, rag_bin)
            print(f"launchd installed: {plist}")
            return 0
        return maintenance_mod.run(cfg, force_verify=args.verify_backup,
                                   skip_worker=args.no_worker)

    if args.cmd == "purge":
        if not args.yes:
            print("refusing without --yes", file=sys.stderr)
            return 1
        admin = db.connect(cfg, role="admin")
        try:
            n = curation_mod.purge(admin, older_days=args.older_days,
                                   assume_yes=True)
        finally:
            admin.close()
        print(f"purged {n} refuted documents")
        return 0

    if args.cmd == "install":
        if args.codex:
            rep = install_mod.install(
                cfg,
                with_launchd=not args.no_launchd,
                codex=True,
                check=args.check,
                codex_home=args.codex_home,
                restore_path=args.restore,
            )
        else:
            rep = install_mod.install(
                cfg, with_launchd=not args.no_launchd, codex=False,
                check=args.check, restore_path=args.restore,
            )
        if rep.restored_paths:
            for path in rep.restored_paths:
                print(f"restored: {_safe(path)}")
            print("rollback complete")
            return 0
        if rep.codex is not None:
            codex_rep = rep.codex
            for key, value in install_mod.managed_codex_settings():
                print(f"managed: {key}={json.dumps(value)}")
            action = "would change" if codex_rep.check else "changed"
            if codex_rep.changed_paths:
                for path in codex_rep.changed_paths:
                    print(f"{action}: {_safe(path)}")
            else:
                print("Codex files: already up to date")
            for record in codex_rep.backups:
                print(
                    f"backup: {_safe(record.target_path)} <- "
                    f"{_safe(record.backup_path)}"
                )
            for duplicate in codex_rep.foreign_hook_duplicates:
                print(
                    "review: foreign herdr-agent-state.sh hook appears "
                    f"{duplicate.count} times"
                )
            if codex_rep.codex_version:
                print(f"codex: {_safe(codex_rep.codex_version)}")
            print(f"validation: {_safe(codex_rep.runtime_validation)}")
            print(f"probe: {_safe(codex_rep.probe_isolation)}")
            print("hooks: review and trust changed handlers with `/hooks`")
            if codex_rep.check:
                print("rollback: not needed in check mode; no files were changed")
                print("check complete: no files written")
            elif rep.rollback_path is not None:
                record = shlex.quote(_safe(rep.rollback_path))
                print(f"rollback: rag install --codex --restore {record}")
            return 0
        claude_rep = rep.claude_report
        if claude_rep is not None:
            for key, value in claude_rep.managed:
                print(f"managed: {key}={json.dumps(value)}")
            if claude_rep.changed:
                action = "would change" if claude_rep.check else "changed"
                print(f"{action}: {_safe(claude_rep.settings_path)}")
            else:
                print("Claude settings: already up to date")
            if claude_rep.backup is not None:
                print(f"backup: {_safe(claude_rep.backup.target_path)} <- "
                      f"{_safe(claude_rep.backup.backup_path)}")
            for warning in claude_rep.warnings:
                print(f"warning: {_safe(warning)}")
            if claude_rep.check:
                print("hooks: review changed handlers with `/hooks` after installing")
                print("check complete: no files written; MCP and launchd untouched")
                return 0
        print(f"mcp:      registered '{install_mod.MCP_NAME}' and"
              f" '{install_mod.MCP_NAME_RO}' (user scope)")
        print("          (restrict subagents by allowlisting only"
              " mcp__agentic-rag-ro__* tools in their definitions)")
        print(f"hooks:    {rep.settings_path} — review changed handlers with `/hooks`")
        print("autocompact: verify with `/autocompact` (expect 500000 tokens from settings)")
        print(f"launchd:  {rep.plist_path or 'skipped'}")
        if rep.rollback_path is not None:
            record = shlex.quote(_safe(rep.rollback_path))
            print(f"rollback: rag install --restore {record}")
        return 0

    if args.cmd == "migrate" and args.migrate_cmd == "run":
        if not (args.yes or args.dry_run):
            print("refusing without --yes (use --dry-run to preview)",
                  file=sys.stderr)
            return 1
        lock = None
        if not args.dry_run:
            if not args.skip_backup:
                backup_mod.run_backup(cfg)
                print("pre-migration backup done")
            if embed.try_embed_texts(["migration preflight"], cfg) is None:
                print("error: Ollama/bge-m3 unreachable — the import embeds"
                      " every chunk; only --dry-run works without embeddings",
                      file=sys.stderr)
                return 3
            # pass LOCK_PATH explicitly — acquire_lock's default is bound at
            # def time; the module attr is what tests monkeypatch (ffa86a2)
            lock = worker_mod.acquire_lock(worker_mod.LOCK_PATH)
            if lock is None:
                print("error: another writer (worker) is active — retry in a"
                      " moment", file=sys.stderr)
                return 3
        conn = db.connect(cfg, role="writer")
        try:
            migration_mod.run_migration(conn, cfg, args.source,
                                        dry_run=args.dry_run,
                                        limit=args.limit)
        finally:
            conn.close()
            if lock is not None:
                lock.close()
        return 0

    if args.cmd == "migrate" and args.migrate_cmd == "classify":
        conn = db.connect(cfg, role="reader")
        try:
            out = migration_mod.classify_domains(conn, cfg)
        finally:
            conn.close()
        print(f"report: {out}")
        return 0

    if args.cmd == "migrate" and args.migrate_cmd == "apply-domains":
        if not args.yes:
            print("refusing without --yes", file=sys.stderr)
            return 1
        # same worker flock as `migrate run` — apply-domains writes too
        # (set_domain), so it must not race the worker's writes either
        lock = worker_mod.acquire_lock(worker_mod.LOCK_PATH)
        if lock is None:
            print("error: another writer (worker) is active — retry in a"
                  " moment", file=sys.stderr)
            return 3
        conn = db.connect(cfg, role="writer")
        try:
            applied, skipped = migration_mod.apply_domain_report(
                conn, args.report_tsv)
        finally:
            conn.close()
            lock.close()
        print(f"domains applied: {applied}, skipped: {skipped}")
        return 0

    if args.cmd == "migrate" and args.migrate_cmd == "report":
        conn = db.connect(cfg, role="reader")
        try:
            out = migration_mod.acceptance_report(conn, cfg,
                                                  golden=args.golden)
        finally:
            conn.close()
        print(f"report: {out}")
        return 0

    conn = db.connect(cfg, role="writer")
    try:
        if args.cmd == "domain" and args.domain_cmd == "add":
            domains_mod.add_domain(conn, args.name, args.description)
            print(f"domain '{args.name}' ready")
            return 0

        if args.cmd == "domain" and args.domain_cmd == "list":
            for d in domains_mod.list_domains(conn):
                print(f"{d.name:<20} {d.docs:>5}  {d.description}")
            return 0

        if args.cmd == "save":
            body = args.body if args.body is not None else (
                args.file.read_text() if args.file else "")
            edges = []
            for spec in args.edge:
                pred, _, slug = spec.partition(":")
                if not slug:
                    print(f"bad --edge (want PREDICATE:SLUG): {spec}",
                          file=sys.stderr)
                    return 1
                edges.append(EdgeSpec(pred, slug))
            # --slug upserts: reuse the existing doc_id when that slug is live
            # (update path), else create carrying the requested slug. Enables
            # idempotent re-ingestion and read-modify-write appends.
            doc_id = None
            if args.slug:
                row = conn.execute(
                    "SELECT id FROM documents WHERE slug = %s", (args.slug,)
                ).fetchone()
                if row is not None:
                    doc_id = str(row["id"])
            res = store.save_document(
                conn, cfg, title=args.title, body=body, domain=args.domain,
                dtype=args.dtype, edges=edges, actor="cli",
                slug=args.slug, doc_id=doc_id, project=args.project, scope=args.scope,
            )
            print(f"{'created' if res.created else 'updated'} {res.slug}"
                  f" ({res.n_chunks} chunks, {res.n_edges} edges)")
            for w in res.warnings:
                print(f"WARNING: {w}", file=sys.stderr)
            return 0

        if args.cmd == "get":
            doc = store.get_document(conn, args.id_or_slug)
            if doc is None:
                print("not found", file=sys.stderr)
                return 1
            if args.json:
                print(json.dumps(doc, default=_json_default, indent=1))
            else:
                print(f"# {doc['title']}  [{doc['domain']}/{doc['dtype']}"
                      f" · {doc['status']} · {doc['slug']}]\n")
                print(doc["body"])
                for e in doc["edges_out"]:
                    print(f"  -> {e.predicate}: {e.peer_slug}")
                for e in doc["edges_in"]:
                    print(f"  <- {e.predicate}: {e.peer_slug}")
            return 0

        if args.cmd == "search":
            hits, warnings = search_mod.search(
                conn, cfg, args.query, domain=args.domain, k=args.k,
                project=args.project, scope=args.scope, as_of=args.as_of, history=args.history,graph_depth=args.graph_depth)
            if args.json:
                print(json.dumps({"results": hits, "warnings": warnings},
                                 default=_json_default, indent=1))
            else:
                for h in hits:
                    print(f"{h.score:.4f}  {h.slug:<40} [{h.domain}/{h.dtype}]")
                for w in warnings:
                    print(f"WARNING: {w}", file=sys.stderr)
            return 0

        if args.cmd == "status":
            rep = status_mod.gather_status(conn, cfg)
            print("documents:")
            for r in rep.documents:
                print(f"  {r['domain']:<20} {r['status']:<10} {r['n']}")
            print("queue:")
            for r in rep.queue:
                print(f"  {r['kind']:<10} {r['status']:<12} {r['n']}")
            for e in rep.queue_errors:
                session = _safe_excerpt(e.session_id or "-", 500)
                diagnostic = _safe_excerpt(e.last_error or "-", 500)
                print(f"  ERROR #{e.id} {e.kind} ({session}, "
                      f"{e.attempts} attempts): {diagnostic}")
            print(f"mining accepted batches awaiting application: {rep.pending_mining_batches}")
            for window in rep.mining_windows:
                state = "applied" if window["applied_at"] else "accepted"
                print(f"mining window {window['id']}: {state}; remainder={window['has_more']}")
            for source in rep.mining_source_warnings:
                print(f"mining source warning (job {source['id']}): " + "; ".join(source["warnings"]))
            if rep.oldest_open_mine_at:
                print("oldest open mine: "
                      f"{rep.oldest_open_mine_at:%Y-%m-%d %H:%M}")
            if rep.provider_health:
                state = ("available" if rep.provider_health.available
                         else "unavailable")
                provider = _safe(rep.provider_health.provider)
                print(f"provider: {provider} {state}")
                if not rep.provider_health.available:
                    if rep.provider_health.reason:
                        print(f"  reason: {_safe(rep.provider_health.reason)}")
                    if rep.provider_health.provider == "codex":
                        print("  remediation: run `codex login`; queued jobs "
                              "resume automatically")
            print(f"checkpoints: {rep.open_checkpoints} open")
            if rep.newest_checkpoint_at:
                project = rep.newest_checkpoint_project or "-"
                print(
                    "  newest: "
                    f"{rep.newest_checkpoint_at:%Y-%m-%d %H:%M} "
                    f"[{rep.newest_checkpoint_quality}] {_safe(project)}"
                )
                handoff_at = rep.newest_checkpoint_handoff_at
                if handoff_at is not None:
                    age = datetime.now(timezone.utc) - handoff_at
                    print(f"checkpoint handoff: {handoff_at:%Y-%m-%d %H:%M} "
                          f"({_format_age(age)} ago)")
                else:
                    print("checkpoint handoff: none")
            print(
                "checkpoint enrichments: "
                f"{rep.pending_checkpoint_enrichments} pending"
            )
            if rep.oldest_pending_checkpoint_enrichment_age is not None:
                print(
                    "  oldest pending: "
                    f"{_format_age(rep.oldest_pending_checkpoint_enrichment_age)}"
                )
            for warning in rep.checkpoint_warnings:
                print(f"WARNING: {_safe(warning)}")
            print(f"last local backup: {rep.last_backup or '—'}")
            if rep.backup_warning:
                print(f"WARNING: {_safe(rep.backup_warning)}")
            if rep.last_curation_at:
                print(f"last curation: {rep.last_curation_at:%Y-%m-%d %H:%M}")
            return 0

        if args.cmd == "queue" and args.queue_cmd == "requeue-legacy-provider-failures":
            count = jobs_mod.count_legacy_provider_failures(conn)
            print(f"candidate count: {count}")
            if count != args.expect:
                print(f"count mismatch: expected {args.expect}, found {count}; no changes",
                      file=sys.stderr)
                return 1
            if not args.yes:
                print("refusing without --yes", file=sys.stderr)
                return 1
            if not jobs_mod.requeue_legacy_provider_failures(
                    conn, expected_count=args.expect):
                print("count changed during requeue; no changes", file=sys.stderr)
                return 1
            print(f"requeued {count} legacy provider-failure job(s)")
            return 0

        if args.cmd == "review":
            rep = curation_mod.review_report(conn, cfg)
            print(f"unknown project scopes: {rep['unknown_scope_count']} (rag scope report)")
            print("duplicate candidates:")
            for d in rep["duplicate_candidates"]:
                print(f"  {d['src_slug']} duplicate_of {d['dst_slug']}")
            print("dangling links:")
            for d in rep["dangling"]:
                print(f"  {d['src_slug']} -{d['predicate']}-> {d['dst_slug']}")
            print("stale pins:")
            for p_ in rep["stale_pins"]:
                print(f"  {p_['id']}  (since {p_['anchor']:%Y-%m-%d})"
                      f"  {p_['body'][:80]}")
            print("mining suggestions:")
            for s in rep["suggestions"]:
                print(f"  [{s['op']}] {s['summary'][:100]}")
            print("queue errors:")
            for e in rep["queue_errors"]:
                session = _safe_excerpt(e["session_id"] or "-", 500)
                diagnostic = _safe_excerpt(e["last_error"] or "-", 500)
                print(f"  #{e['id']} {e['kind']} ({session}, "
                      f"{e['attempts']} attempts): {diagnostic}")
            return 0

        if args.cmd == "pin":
            if args.pin_cmd == "add":
                pid = pins_mod.add_pin(
                    conn, body=args.body, document_id=args.document,
                    scope=args.scope, priority=args.priority)
                print(f"pinned {pid}")
                return 0
            if args.pin_cmd == "list":
                for p in pins_mod.list_pins(conn, include_inactive=args.all):
                    state = "" if p.active else " (inactive)"
                    print(f"{p.id}  [{p.scope}] p{p.priority}{state}  {p.body}")
                return 0
            if args.pin_cmd == "rm":
                ok = pins_mod.unpin(conn, args.pin_id)
                print("unpinned" if ok else "no such active pin")
                return 0 if ok else 1
            if args.pin_cmd == "verify":
                ok = pins_mod.verify_pin(conn, args.pin_id)
                print("verified" if ok else "no such active pin")
                return 0 if ok else 1
    finally:
        conn.close()
    return 1


def main(argv: list[str] | None = None) -> int:
    """Exit-code contract: 0 ok · 1 user/data error · 3 infrastructure
    (DB down, pg tools, Ollama) · 4 unexpected. argparse exits 2 itself."""
    try:
        return _main(argv)
    except (psycopg.OperationalError, RuntimeError) as e:
        print(f"error: {_safe(e)}", file=sys.stderr)
        return 3
    except (ValueError, FileNotFoundError) as e:
        print(f"error: {_safe(e)}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 — last-resort mapping, never a traceback
        print(
            f"unexpected error: {type(e).__name__}: {_safe(e)}",
            file=sys.stderr,
        )
        return 4


if __name__ == "__main__":
    sys.exit(main())
