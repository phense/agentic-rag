#!/usr/bin/env python3
"""Loopback-only signed webhook example; persist IDs, never canonical payloads.

Run with the installed agentic-rag Python. See docs/webhooks.md. This receiver
demonstrates deduplication/order bookkeeping, not arbitrary downstream effects.
"""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import sqlite3
import stat
import uuid

from agentic_rag.service.auth import protected_file
from agentic_rag.webhook_delivery import verify_signature


def load_keys(paths):
    keys = {}
    for path in paths:
        item = json.loads(protected_file(path, max_bytes=2048))
        identity, key = item['key_id'], bytes.fromhex(item['key_hex'])
        if not isinstance(identity, str) or not identity.startswith('wh1:') or len(key) != 32:
            raise ValueError('invalid receiver key file')
        if identity in keys and keys[identity] != key:
            raise ValueError('conflicting receiver keys')
        keys[identity] = key
    return keys


def database(path):
    # Its enclosing operator-owned private directory is a prerequisite.
    path = path.expanduser().absolute()
    parent = path.parent.stat()
    if parent.st_uid != os.getuid() or parent.st_mode & 0o077:
        raise ValueError('receiver directory must be owner-only')
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('receiver database must be an owner-only regular file') from None
    else:
        os.close(descriptor)
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE IF NOT EXISTS accepted(event_id TEXT PRIMARY KEY, digest TEXT NOT NULL)')
    conn.execute('CREATE TABLE IF NOT EXISTS latest(resource TEXT PRIMARY KEY, version INTEGER NOT NULL)')
    conn.commit()
    return conn


def handler(keys, conn):
    class Receiver(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *args):
            pass  # No bodies, signatures or credential material in access logs.

        def reply(self, code, disposition=None):
            self.send_response(code)
            self.send_header('Content-Length', '0')
            self.send_header('Connection', 'close')
            if disposition:
                self.send_header('X-Example-Disposition', disposition)
            self.end_headers()
            self.close_connection = True

        def do_POST(self):
            if self.path != '/events':
                return self.reply(404)
            try:
                if self.headers.get('Transfer-Encoding') is not None:
                    raise ValueError('unsupported framing')
                lengths = self.headers.get_all('Content-Length', [])
                if len(lengths) != 1:
                    raise ValueError('invalid framing')
                length = int(lengths[0])
                if not 1 <= length <= 4096:
                    raise ValueError('invalid length')
                body = self.rfile.read(length)
                if len(body) != length:
                    raise ValueError('incomplete body')
                names = ('X-RAG-Key-Id', 'X-RAG-Timestamp', 'X-RAG-Signature')
                if any(len(self.headers.get_all(name, [])) != 1 for name in names):
                    return self.reply(401)
                headers = {name: self.headers[name] for name in names}
                key = keys.get(headers['X-RAG-Key-Id'])
                if key is None or not verify_signature(key, body, headers):
                    return self.reply(401)
                event = json.loads(body)
                identity = str(uuid.UUID(event['event_id']))
                version = event['resource_version']
                if event.get('event_version') != 1 or type(version) is not int or not 0 < version < 2**63:
                    raise ValueError('invalid event version')
                resource = json.dumps([event['scope'], event['resource_id']], sort_keys=True)
                digest = hashlib.sha256(body).hexdigest()
                with conn:
                    prior = conn.execute('SELECT digest FROM accepted WHERE event_id=?', (identity,)).fetchone()
                    if prior is not None:
                        if prior[0] != digest:
                            return self.reply(409)
                        disposition = 'duplicate'
                    else:
                        latest = conn.execute('SELECT version FROM latest WHERE resource=?', (resource,)).fetchone()
                        disposition = 'older' if latest and latest[0] >= version else 'accepted'
                        conn.execute('INSERT INTO accepted VALUES (?,?)', (identity, digest))
                        if disposition == 'accepted':
                            conn.execute('INSERT INTO latest VALUES (?,?) ON CONFLICT(resource) DO UPDATE SET version=excluded.version',
                                         (resource, version))
                # Acknowledge only after the durable dedup/order transaction commits.
                self.reply(204, disposition)
            except (ValueError, TypeError, KeyError, TimeoutError):
                self.reply(400)
            except sqlite3.Error:
                self.reply(503)

    return Receiver


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key-file', action='append', required=True, type=Path)
    parser.add_argument('--database', required=True, type=Path)
    parser.add_argument('--port', required=True, type=int)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or len(args.key_file) > 32:
        parser.error('port must be 1..65535; at most32 private key files')
    os.umask(0o077)
    keys = load_keys(args.key_file)
    conn = database(args.database)
    try:
        with HTTPServer(('127.0.0.1', args.port), handler(keys, conn)) as server:
            print(json.dumps({'listening': '127.0.0.1', 'port': args.port}), flush=True)
            server.serve_forever()
    finally:
        conn.close()


if __name__ == '__main__':
    main()
