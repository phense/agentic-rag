"""Explicit operator commands; inspection never opens a provider or database."""
from __future__ import annotations

import json


def add_parser(sub):
    root = sub.add_parser('providers', help='inspect providers offline or explicitly probe synthetic input')
    commands = root.add_subparsers(dest='provider_cmd', required=True)
    commands.add_parser('inspect', help='show capabilities and bounds without network or database calls')
    probe = commands.add_parser('probe', help='send fixed synthetic text to one configured embedding profile')
    probe.add_argument('profile')
    probe.add_argument('--allow-egress', action='store_true', help='explicitly permit a non-loopback provider destination')
    extraction = commands.add_parser('probe-extraction', help='send a fixed synthetic request to the extraction provider')
    extraction.add_argument('--allow-egress', action='store_true', help='explicitly permit external extraction through the configured provider')
    index = sub.add_parser('index', help='manage bounded, model-bound embedding generations as the local owner')
    operations = index.add_subparsers(dest='index_cmd', required=True)
    status = operations.add_parser('status', help='inspect retained generation coverage without provider calls')
    status.add_argument('name', nargs='?')
    create = operations.add_parser('create', help='verify a profile and create a separate generation')
    create.add_argument('name')
    create.add_argument('--profile', required=True)
    create.add_argument('--allow-egress', action='store_true')
    build = operations.add_parser('build', help='process one explicit bounded batch of stored chunk text')
    build.add_argument('name')
    build.add_argument('--batch-size', type=int, default=8)
    build.add_argument('--allow-corpus', action='store_true')
    build.add_argument('--allow-egress', action='store_true')
    build.add_argument('--dry-run', action='store_true', help='show coverage/destination/bounds without credentials, inference or writes')
    for operation in ('activate', 'rollback'):
        command = operations.add_parser(operation, help='select a fully current generation after identity verification')
        command.add_argument('name')
        command.add_argument('--allow-egress', action='store_true')


def run(args, cfg):
    if args.cmd == 'index':
        return run_index(args, cfg)
    if args.provider_cmd == 'inspect':
        profiles = {}
        if getattr(cfg, 'embedding_profiles', None):
            from .providers import describe_profile, resolve_profile
            profiles = {name: describe_profile(resolve_profile(cfg, name)) for name in cfg.embedding_profiles}
        from .providers import describe_llm
        result = {'mode': 'offline-inspection', 'corpus_requests': 0,
            'extraction': describe_llm(cfg),
            'profiles': profiles,
            'legacy': {'model': cfg.embed_model, 'dimensions': cfg.embed_dim,
                'identity': 'historical raw vectors are untagged; use a managed rebuild for a model change'}}
    elif args.provider_cmd == 'probe-extraction':
        from .providers import describe_llm, probe_llm
        metadata = describe_llm(cfg)
        if metadata['external_egress'] and not args.allow_egress:
            raise ValueError('external_provider_requires_allow_egress: inspect the extraction destination and rerun with --allow-egress')
        result = {'mode': 'synthetic-extraction-probe', 'corpus_requests': 0,
            'provider': metadata, 'result': probe_llm(cfg)}
    else:
        from .providers import describe_profile, resolve_profile, verify_profile
        profile = resolve_profile(cfg, args.profile)
        require_egress(profile, args.allow_egress)
        result = {'mode': 'synthetic-probe', 'corpus_requests': 0,
            'profile': describe_profile(profile), 'result': verify_profile(profile)}
    print(json.dumps(result, default=str, sort_keys=True))
    return 0


def run_index(args, cfg):
    from dataclasses import asdict, is_dataclass
    from . import db, indexes, store
    from .providers import describe_profile, resolve_profile
    from .service.context import CURRENT
    if cfg.service_mode == 'client' or CURRENT.get() is not None:
        raise ValueError('local_database_owner_required: administer generations on the database-owning installation')
    if args.index_cmd == 'build':
        if not 1 <= args.batch_size <= 32:
            raise ValueError('batch size must be 1 through 32')
        if not args.dry_run and not args.allow_corpus:
            raise ValueError('explicit_allow_corpus_required: inspect with --dry-run, then use --allow-corpus for one bounded batch')
    with db.connect(cfg, role='owner') as connection:
        if args.index_cmd == 'status' or (args.index_cmd == 'build' and args.dry_run):
            connection.execute('SET TRANSACTION READ ONLY')
        if args.index_cmd == 'status':
            result = indexes.status(connection, cfg, args.name)
        else:
            if args.index_cmd == 'create':
                profile = resolve_profile(cfg, args.profile)
            else:
                current = indexes.status(connection, cfg, args.name)
                profile = resolve_profile(cfg, current['profile_name'])
            if args.index_cmd == 'build' and args.dry_run:
                result = {'mode': 'build-dry-run', 'corpus_requests': 0,
                    'coverage': current, 'profile': describe_profile(profile),
                    'max_batch_inputs': min(args.batch_size, profile.max_batch, current['remaining'])}
            else:
                require_egress(profile, args.allow_egress)
                if args.index_cmd == 'create':
                    result = store.create_embedding_index(connection, cfg, args.name, args.profile)
                elif args.index_cmd == 'build':
                    result = store.build_embedding_index(connection, cfg, args.name,
                        limit=args.batch_size, allow_corpus=args.allow_corpus)
                else:
                    result = store.select_embedding_index(connection, cfg, args.name,
                        rollback=args.index_cmd == 'rollback')
    print(json.dumps(result, default=lambda value: asdict(value) if is_dataclass(value) else str(value), sort_keys=True))
    return 0


def require_egress(profile, allowed):
    """A literal loopback endpoint needs no additional external-egress flag."""
    import ipaddress
    from urllib.parse import urlsplit
    host = urlsplit(profile.url).hostname
    local = host == 'localhost'
    try:
        local = local or ipaddress.ip_address(host).is_loopback
    except (ValueError, TypeError):
        pass
    if not local and not allowed:
        raise ValueError('external_provider_requires_allow_egress: inspect the destination and rerun with --allow-egress')
