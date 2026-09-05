"""Owned disposable local database; no caller-selected cleanup target."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import os
import re
import uuid

import psycopg
from psycopg import sql

from .. import db


def validate_name(name: str) -> None:
    if not re.fullmatch(r'rag_bench_[0-9a-f]{24}', name):
        raise ValueError('refusing non-owned benchmark database name')


def cleanup(cfg, name: str, ownership: str) -> None:
    validate_name(name)
    if cfg.db_name != name:
        raise ValueError('benchmark cleanup configuration mismatch')
    connection = db.connect(cfg, role='owner')
    try:
        row = connection.execute('SELECT owner_id FROM benchmark_ownership').fetchone()
        if row is None or row['owner_id'] != ownership:
            raise ValueError('benchmark ownership marker mismatch; refusing cleanup')
    finally:
        connection.close()
    with psycopg.connect(db.dsn(cfg, 'owner', dbname='postgres'), autocommit=True) as admin:
        admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))


@contextmanager
def isolated_database(cfg):
    if any(os.environ.get(key) for key in ['PGHOST', 'PGHOSTADDR', 'PGSERVICE', 'PGSERVICEFILE']):
        raise ValueError('unset PGHOST, PGHOSTADDR, PGSERVICE and PGSERVICEFILE for the local benchmark')
    if (cfg.db_host not in {'', 'localhost', '127.0.0.1', '::1'}
            and not re.fullmatch(r'/[a-zA-Z0-9_./-]+', cfg.db_host)):
        raise ValueError('benchmark default requires a local PostgreSQL host')
    name = 'rag_bench_' + uuid.uuid4().hex[:24]
    ownership = uuid.uuid4().hex
    validate_name(name)
    isolated = replace(cfg, db_name=name, db_host=cfg.db_host or '127.0.0.1')
    with psycopg.connect(db.dsn(isolated, 'owner', dbname='postgres'), autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        # Until the marker is committed, this creator connection owns the only
        # cleanup authority: CREATE succeeded for this exact randomly generated name.
        try:
            c = db.connect(isolated, role='owner')
            try:
                c.execute('CREATE TABLE benchmark_ownership(owner_id text PRIMARY KEY)')
                c.execute('INSERT INTO benchmark_ownership VALUES (%s)', (ownership,))
                c.commit()
            finally:
                c.close()
        except BaseException:
            admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
            raise
    try:
        db.init_db(isolated)
        yield isolated
    finally:
        cleanup(isolated, name, ownership)
