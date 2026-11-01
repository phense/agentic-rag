"""`rag extraction validate|inspect|dry-run` (RAG-067, feature 6.9).

Validate, inspect and the default dry-run never call a provider and never write.
`dry-run --evaluate` calls the already configured provider once on a bounded,
redacted sample inside a read-only transaction: no knowledge, embedding, audit
or queue write. In client mode the service owns its policy file, so commands
that would need it are refused instead of answering from a local file.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from . import extraction_policy as ep

MAX_SAMPLE_BYTES = 65536
MAX_SAMPLE_EVENTS = 64
MAX_SAMPLE_CHARS = 12000
MAX_SHOWN_CHARS = 200


def add_parser(sub) -> None:
    p = sub.add_parser('extraction', help='versioned extraction policy: validate, inspect, dry-run')
    ex = p.add_subparsers(dest='extraction_cmd', required=True)
    v = ex.add_parser('validate', help='strictly validate the policy file; no provider, no write')
    v.add_argument('--file', type=Path, help='policy file (default: [mining] policy_file)')
    i = ex.add_parser('inspect', help='effective policy per domain with precedence; no provider, no write')
    i.add_argument('--file', type=Path)
    i.add_argument('--project', help='project scope: absolute path, global or unknown')
    i.add_argument('--domain', action='append', default=[], help='repeatable; default: every defined domain')
    i.add_argument('--queued', action='store_true', help='policy identities of pending local and central work')
    d = ex.add_parser('dry-run', help='sanitized plan for a sample; --evaluate calls the configured provider')
    d.add_argument('--file', type=Path)
    d.add_argument('--project', required=True)
    d.add_argument('--domain', action='append', default=[])
    d.add_argument('--sample', type=Path, required=True, help='JSON {"events": [{"source_id","role","text"}]}')
    d.add_argument('--evaluate', action='store_true', help='explicit opt-in: one provider call, still no writes')


class Refused(ValueError):
    pass


def _path(args, cfg):
    return args.file if args.file is not None else cfg.mine_policy_file


def _client_guard(args, cfg, *, needs_service_file=True):
    if cfg.service_mode != 'client':
        return
    if args.extraction_cmd == 'dry-run' and args.evaluate:
        raise Refused('unsupported_in_client_mode: evaluation uses the service provider; run it on the service host')
    if needs_service_file and args.file is None:
        raise Refused('unsupported_in_client_mode: the service owns its extraction policy; '
                      'run this on the service host or pass --file to check a local draft')
    if getattr(args, 'queued', False):
        raise Refused('unsupported_in_client_mode: queued work is inspected on the service host')


def _policy_file(path):
    return None if path is None else ep.load_file(path)


def _shown(text) -> str:
    from .secrets import strip_secrets
    return strip_secrets(str(text))[0][:MAX_SHOWN_CHARS]


def _describe(policy: ep.Policy, trace, channels) -> dict:
    return {'scopes': trace, 'digest': policy.digest, 'categories': [c for c in channels if c in policy.categories],
            'limits': {c: policy.limit(c) for c in channels}, 'max_body_chars': policy.max_body_chars,
            'guidance': policy.guidance, 'examples': [dict(e) for e in policy.examples]}


def _domains(cfg, args):
    if args.domain:
        return sorted(set(args.domain))
    if cfg.service_mode == 'client':
        raise Refused('unsupported_in_client_mode: pass --domain with --file')
    from . import db
    with db.connect(cfg, role='reader') as conn:
        return [r['name'] for r in conn.execute('SELECT name FROM domains ORDER BY name')]


def validate(args, cfg) -> tuple[int, dict]:
    _client_guard(args, cfg, needs_service_file=False)
    path = _path(args, cfg)
    if path is None:
        return 0, {'valid': True, 'configured': False, 'policy': 'builtin', 'provider_calls': 0, 'writes': 0}
    try:
        policy = ep.load_file(path)
    except ep.PolicyError as error:
        return 1, {'valid': False, 'errors': error.errors, 'provider_calls': 0, 'writes': 0}
    return 0, {'valid': True, 'configured': True, 'identity': policy.identity,
               'file_sha256': sha256(Path(path).read_bytes()).hexdigest(),
               'global': bool(policy.global_fragment), 'rules': len(policy.rules),
               'caps': {'file_bytes': ep.MAX_FILE_BYTES, 'rules': ep.MAX_RULES, 'guidance_chars': ep.MAX_GUIDANCE_CHARS,
                        'examples': ep.MAX_EXAMPLES, 'example_chars': ep.MAX_EXAMPLE_CHARS,
                        'max_items_per_category': ep.HARD_CAPS, 'max_body_chars': ep.MAX_BODY_CHARS},
               'provider_calls': 0, 'writes': 0}


def inspect(args, cfg) -> tuple[int, dict]:
    _client_guard(args, cfg)
    if args.queued:
        return 0, queued(cfg)
    if not args.project:
        raise Refused('--project is required unless --queued is given')
    path = _path(args, cfg)
    policy = _policy_file(path)
    project = ep.canonical_project(args.project)
    names = _domains(cfg, args)
    bundle = ep.build_bundle(policy, project, names)
    out = {'project': project, 'source': 'builtin' if path is None else 'file',
           'identity': policy.identity if policy else None, 'bundle_digest': bundle.digest,
           'precedence': ['builtin', 'global', 'domain', 'project', 'exact'],
           'domains': {}, 'all_disabled': ep.all_disabled(bundle, names),
           'preferences_chars': len(ep.render_preferences(bundle, names)), 'provider_calls': 0, 'writes': 0}
    for name in names:
        effective, trace = ep.resolve(policy, name, project)
        out['domains'][name] = _describe(effective, trace, ep.DOMAIN_CHANNELS)
    effective, trace = ep.resolve_domainless(policy, project)
    out['domainless'] = _describe(effective, trace, ep.DOMAINLESS_CHANNELS)
    return 0, out


def queued(cfg) -> dict:
    """Which policy each pending job or window will use: admitted digest, legacy or bound."""
    from . import db
    with db.connect(cfg, role='reader') as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        jobs = conn.execute("""SELECT q.id,q.status,q.payload ? 'extraction_policy' captured,
              q.payload->'extraction_policy'->>'digest' digest,b.digest bound
            FROM mining_queue q LEFT JOIN extraction_policy_bindings b
              ON b.session_id=q.session_id AND b.input_cursor=COALESCE(q.last_uuid,'')
            WHERE q.kind='mine' AND q.status IN ('pending','processing','error') ORDER BY q.id""").fetchall()
        windows = conn.execute("""SELECT w.id,w.state,w.payload ? '_extraction_policy' captured,
              w.payload->'_extraction_policy'->>'digest' digest,b.digest bound
            FROM service_windows w LEFT JOIN extraction_policy_bindings b
              ON b.session_id=w.session_id AND b.input_cursor=w.input_cursor
            WHERE w.state IN ('queued','blocked','error') ORDER BY w.created_at,w.id""").fetchall()
    def row(r, ident):
        return {ident: str(r['id']), 'state': r['status'] if 'status' in r else r['state'],
                'admitted': r['digest'] if r['captured'] else 'legacy-builtin', 'bound': r['bound']}
    return {'jobs': [row(r, 'job') for r in jobs], 'windows': [row(r, 'receipt') for r in windows],
            'provider_calls': 0, 'writes': 0}


def _sample(path):
    from .mining_window import MiningWindow
    from .secrets import strip_secrets
    from .validity import parse_time
    raw = Path(path).read_bytes()
    if len(raw) > MAX_SAMPLE_BYTES:
        raise Refused('sample_too_large')
    try:
        data = json.loads(raw)
        items = data['events']
        assert isinstance(items, list) and 1 <= len(items) <= MAX_SAMPLE_EVENTS
    except (ValueError, KeyError, TypeError, AssertionError):
        raise Refused('invalid_sample: expected {"events": [...]} with 1-64 events') from None
    events, redactions, seen = [], 0, set()
    for index, item in enumerate(items):
        if not isinstance(item, dict) or item.get('role') not in ('user', 'assistant') or not isinstance(item.get('text'), str):
            raise Refused(f'invalid_sample: event {index} needs role user|assistant and text')
        source = item.get('source_id', f'sample-{index}')
        timestamp = item.get('timestamp')
        if (not isinstance(source, str) or not source or len(source) > 512
                or any(ord(c) < 32 or ord(c) == 127 for c in source)
                or strip_secrets(source)[1]):
            raise Refused(f'invalid_sample: invalid source metadata at event {index}')
        try:
            if timestamp is not None:
                if not isinstance(timestamp, str) or len(timestamp) > 128 or strip_secrets(timestamp)[1]:
                    raise ValueError()
                parse_time(timestamp)
        except (ValueError, TypeError):
            raise Refused(f'invalid_sample: invalid timestamp at event {index}') from None
        if source in seen:
            raise Refused(f'invalid_sample: duplicate source_id at event {index}')
        seen.add(source)
        body = item['text'][len(f"[{item['role']}] "):] if item['text'].startswith(f"[{item['role']}] ") else item['text']
        # Preserve source wording for exact-quote grounding, including whitespace.
        clean, count = strip_secrets(body)
        redactions += count
        events.append({'source_id': source, 'role': item['role'], 'timestamp': timestamp,
                       'text': f"[{item['role']}] {clean}", 'offset': 0, 'complete': True})
    text = '\n'.join(e['text'] for e in events)
    if len(text) > MAX_SAMPLE_CHARS:
        raise Refused('sample_too_large')
    return MiningWindow(text, 'dry-run-end', False, (), False, tuple(events)), redactions


def dry_run(args, cfg) -> tuple[int, dict]:
    _client_guard(args, cfg)
    from . import db, mining
    path = _path(args, cfg)
    policy = _policy_file(path)
    project = ep.canonical_project(args.project)
    window, redactions = _sample(args.sample)
    with db.connect(cfg, role='reader') as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        names = [r['name'] for r in conn.execute('SELECT name FROM domains ORDER BY name')]
        if args.domain:
            names = [n for n in names if n in set(args.domain)]
        bundle = ep.build_bundle(policy, project, names)
        disabled = ep.all_disabled(bundle, names)
        preferences = ep.render_preferences(bundle, names)
        out = {'project': project, 'source': 'builtin' if path is None else 'file', 'bundle_digest': bundle.digest,
               'domains': names, 'all_disabled': disabled, 'would_call_provider': bool(names) and not disabled,
               'sample_events': len(window.events), 'sample_redactions': redactions,
               'preferences': preferences, 'provider_calls': 0, 'writes': 0}
        if not args.evaluate or not names:
            return 0, out
        filtered, report, skip, called = mining.prepare_extraction(
            conn, cfg, window=window, session_id='dry-run', project=args.project, domain_names=names, bundle=bundle)
        conn.rollback()
    retained = {}
    for channel in ep.CHANNELS:
        for item in filtered.get(channel) or []:
            field = ep.TEXT_FIELDS[channel]
            retained.setdefault(channel, []).append({
                'title': _shown(item.get('title') or item.get('name') or item.get('entity') or ''),
                'text': _shown(item.get(field) or ''), 'domain': item.get('domain'),
                'claim_kind': item.get('claim_kind'),
                'evidence': len(item['evidence']) if isinstance(item.get('evidence'), list) else int(bool(item.get('evidence')))})
    out.update(provider_calls=int(called), retained=retained, rejected=report['rejected'], skipped=skip,
               note='Mock or real provider output is filtered deterministically; this proves enforcement, not truth.')
    return 0, out


def run(args, cfg) -> int:
    import sys
    try:
        code, out = {'validate': validate, 'inspect': inspect, 'dry-run': dry_run}[args.extraction_cmd](args, cfg)
    except Refused as refusal:
        print(f'error: {refusal}', file=sys.stderr)
        return 1
    except ep.PolicyError as error:
        print(json.dumps({'valid': False, 'errors': error.errors, 'provider_calls': 0, 'writes': 0}))
        return 1
    print(json.dumps(out, ensure_ascii=False, sort_keys=True, default=str))
    return code
