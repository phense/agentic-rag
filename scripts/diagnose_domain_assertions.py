#!/usr/bin/env python3
"""Read-only aggregate diagnosis; never print private keys, IDs or evidence."""
import json

from agentic_rag import db
from agentic_rag.config import load_config


def report(cfg):
    with db.connect(cfg, role='reader') as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        mixed = conn.execute(
            'SELECT count(*) n FROM edges e JOIN documents s ON s.id=e.src_id '
            'JOIN documents d ON d.id=e.dst_id JOIN fact_assertions sa ON sa.document_id=s.id '
            'JOIN fact_assertions da ON da.document_id=d.id '
            "WHERE e.predicate IN ('supersedes','extends') AND s.domain<>d.domain"
        ).fetchone()['n']
        return {'cross_domain_temporal_edges': mixed,
                'historical_duplicate_domain_attribution': 'unverified: original source domain may be absent',
                'history_rewritten': False}


def main():
    try:
        print(json.dumps(report(load_config()), sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({'error': type(exc).__name__, 'details': 'omitted'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
