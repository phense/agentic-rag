"""Protected durable outbox. Pending input is never evicted to make room."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import time


class SpoolFull(RuntimeError):
    pass


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)


class Spool:
    def __init__(self,path,partition,*,max_items=2000,max_bytes=16*1024*1024):
        self.path,self.partition=Path(path),partition
        self.max_items,self.max_bytes=max_items,max_bytes
        if not isinstance(partition,str) or not 1<=len(partition)<=256 or not 1<=max_items<=100000 or not 1024<=max_bytes<=1024**3:
            raise ValueError('invalid spool limits/partition')
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        info=self.path.parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or (os.name!='nt' and (info.st_uid!=os.getuid() or info.st_mode&0o077)):
            raise ValueError('spool directory permissions must be owner-only')
        fd=os.open(self.path,os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or (os.name!='nt' and (info.st_uid!=os.getuid() or info.st_mode&0o077)):
                raise ValueError('spool file permissions must be owner-only')
        finally:
            os.close(fd)
        self.conn=sqlite3.connect(self.path,timeout=.25)
        self.conn.row_factory=sqlite3.Row
        self.conn.execute('PRAGMA journal_mode=DELETE')
        self.conn.execute('PRAGMA synchronous=FULL')
        self.conn.executescript('''
          CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY,partition TEXT NOT NULL,session TEXT NOT NULL,
            kind TEXT NOT NULL,payload TEXT NOT NULL,bytes INTEGER NOT NULL,state TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,next_attempt REAL NOT NULL DEFAULT 0,error TEXT,created REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS cursors(partition TEXT,session TEXT,cursor TEXT NOT NULL,PRIMARY KEY(partition,session));
          CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY,partition TEXT,receipt TEXT,created REAL);
          CREATE TABLE IF NOT EXISTS contexts(partition TEXT,session TEXT,project TEXT,text TEXT,created REAL,
            PRIMARY KEY(partition,session,project));
          CREATE TABLE IF NOT EXISTS sources(partition TEXT,session TEXT,project TEXT,raw BLOB,
            PRIMARY KEY(partition,session));
          CREATE TABLE IF NOT EXISTS checkpoints(partition TEXT,session TEXT,payload TEXT,
            PRIMARY KEY(partition,session));
          CREATE TABLE IF NOT EXISTS health(partition TEXT PRIMARY KEY,code TEXT);
        ''')

    def __enter__(self): return self
    def __exit__(self,*args): self.conn.close()

    def cursor(self,session):
        row=self.conn.execute('SELECT cursor FROM cursors WHERE partition=? AND session=?',(self.partition,session)).fetchone()
        return row['cursor'] if row else ''

    def enqueue(self,kind,session,payload):
        if kind not in {'window','checkpoint','boundary'} or not isinstance(session,str) or not 1<=len(session)<=256:
            raise ValueError('invalid spool input')
        text=canonical(payload)
        size=len(text.encode())
        identity=hashlib.sha256(canonical([self.partition,kind,session,payload]).encode()).hexdigest()
        self.conn.execute('BEGIN IMMEDIATE')
        try:
            if self.conn.execute('SELECT 1 FROM outbox WHERE id=? UNION ALL SELECT 1 FROM receipts WHERE id=?',(identity,identity)).fetchone():
                self.conn.rollback()
                return identity
            if kind=='window' and (payload.get('input_cursor')!=self.cursor(session) or not payload.get('output_cursor') or payload['output_cursor']==payload['input_cursor']):
                raise ValueError('conflicting or missing predecessor cursor')
            count,total=self.conn.execute('SELECT count(*),COALESCE(sum(bytes),0) FROM outbox').fetchone()
            total+=self.conn.execute('SELECT COALESCE(sum(length(raw)),0) FROM sources').fetchone()[0]
            total+=self.conn.execute('SELECT COALESCE(sum(length(CAST(payload AS BLOB))),0) FROM checkpoints').fetchone()[0]
            if count>=self.max_items or total+size>self.max_bytes or size>1048576:
                raise SpoolFull('spool capacity exceeded; pending input retained')
            if kind=='window':
                if not self.conn.execute('SELECT 1 FROM cursors WHERE partition=? AND session=?',(self.partition,session)).fetchone() and self.conn.execute('SELECT count(*) FROM cursors').fetchone()[0]>=2000:
                    raise SpoolFull('spool session capacity exceeded; pending input retained')
                self.conn.execute('INSERT INTO cursors VALUES(?,?,?) ON CONFLICT(partition,session) DO UPDATE SET cursor=excluded.cursor',(self.partition,session,payload['output_cursor']))
            self.conn.execute('INSERT INTO outbox(id,partition,session,kind,payload,bytes,created) VALUES(?,?,?,?,?,?,?)',(identity,self.partition,session,kind,text,size,time.time()))
            if kind=='checkpoint':self._remember_checkpoint(payload)
            self.conn.commit()
            return identity
        except BaseException:
            self.conn.rollback()
            raise

    def pending(self):
        return [dict(row) for row in self.conn.execute('SELECT * FROM outbox WHERE partition=? ORDER BY created,rowid',(self.partition,))]

    def due(self):
        # Never overtake an earlier item in the same session (including blocked work).
        return [dict(row) for row in self.conn.execute('''SELECT * FROM outbox a WHERE partition=?
          AND state='pending' AND next_attempt<=? AND NOT EXISTS(SELECT 1 FROM outbox b
            WHERE b.partition=a.partition AND b.session=a.session AND b.rowid<a.rowid)
          ORDER BY created,rowid''',(self.partition,time.time()))]

    def ack(self,identity,receipt):
        if len(canonical(receipt))>4096: raise ValueError('invalid receipt')
        with self.conn:
            row=self.conn.execute('SELECT 1 FROM outbox WHERE id=? AND partition=?',(identity,self.partition)).fetchone()
            if not row: return
            self.conn.execute('INSERT OR REPLACE INTO receipts VALUES(?,?,?,?)',(identity,self.partition,canonical(receipt),time.time()))
            self.conn.execute('DELETE FROM outbox WHERE id=? AND partition=?',(identity,self.partition))
            self.conn.execute('DELETE FROM receipts WHERE id NOT IN (SELECT id FROM receipts ORDER BY created DESC LIMIT 256)')

    def fail(self,identity,code,*,blocked=False):
        # Retain only a stable code, never an HTTP/provider exception body or token.
        if not isinstance(code,str) or not code.replace('_','').isalnum() or len(code)>80: code='upload_failed'
        with self.conn:
            row=self.conn.execute('SELECT attempts FROM outbox WHERE id=? AND partition=?',(identity,self.partition)).fetchone()
            if row:
                attempt=min(row['attempts']+1,31)
                self.conn.execute('UPDATE outbox SET state=?,attempts=?,next_attempt=?,error=? WHERE id=? AND partition=?',('blocked' if blocked else 'pending',attempt,time.time()+min(3600,2**attempt),code,identity,self.partition))

    def retry_blocked(self):
        with self.conn:
            self.conn.execute("UPDATE outbox SET state='pending',next_attempt=0 WHERE partition=?",(self.partition,))

    def cache(self,session,project,text):
        if not isinstance(text,str) or len(text)>10000: raise ValueError('context cache limit')
        with self.conn:
            self.conn.execute('INSERT OR REPLACE INTO contexts VALUES(?,?,?,?,?)',(self.partition,session,project or '',text,time.time()))
            self.conn.execute('DELETE FROM contexts WHERE rowid NOT IN (SELECT rowid FROM contexts ORDER BY created DESC LIMIT 64)')

    def cached(self,session,project):
        row=self.conn.execute('SELECT text FROM contexts WHERE partition=? AND session=? AND project=?',(self.partition,session,project or '')).fetchone()
        return row['text'] if row else None

    def capture_source(self,session,project,raw):
        if not isinstance(raw,bytes) or not isinstance(session,str) or not 1<=len(session)<=256:
            raise ValueError('invalid local source')
        self.conn.execute('BEGIN IMMEDIATE')
        try:
            prior=self.conn.execute('SELECT raw,project FROM sources WHERE partition=? AND session=?',(self.partition,session)).fetchone()
            if prior and (prior['project']!=project or not raw.startswith(prior['raw'])):
                raise ValueError('source changed; buffered input retained; explicit recovery required')
            total=self.conn.execute('SELECT COALESCE(sum(length(raw)),0) FROM sources').fetchone()[0]
            source_total=total-len(prior['raw'] if prior else b'')+len(raw)
            total+=self.conn.execute('SELECT COALESCE(sum(bytes),0) FROM outbox').fetchone()[0]
            total+=self.conn.execute('SELECT COALESCE(sum(length(CAST(payload AS BLOB))),0) FROM checkpoints').fetchone()[0]
            reserve=min(1048576,self.max_bytes//4)
            if source_total>self.max_bytes-reserve or total-len(prior['raw'] if prior else b'')+len(raw)>self.max_bytes or (not prior and self.conn.execute('SELECT count(*) FROM sources').fetchone()[0]>=self.max_items):
                raise SpoolFull('source spool capacity exceeded; original and buffered input must be retained')
            self.conn.execute('INSERT OR REPLACE INTO sources VALUES(?,?,?,?)',(self.partition,session,project,raw))
            self.conn.commit()
        except BaseException:
            self.conn.rollback();raise

    def sources(self):
        return [dict(r) for r in self.conn.execute('SELECT session,project,raw FROM sources WHERE partition=? ORDER BY rowid',(self.partition,))]

    def _remember_checkpoint(self,packet):
        text=canonical(packet)
        prior=self.conn.execute('SELECT length(CAST(payload AS BLOB)) FROM checkpoints WHERE partition=? AND session=?',(self.partition,packet['session_id'])).fetchone()
        total=self.conn.execute('SELECT COALESCE(sum(length(CAST(payload AS BLOB))),0) FROM checkpoints').fetchone()[0]
        total+=self.conn.execute('SELECT COALESCE(sum(bytes),0) FROM outbox').fetchone()[0]
        total+=self.conn.execute('SELECT COALESCE(sum(length(raw)),0) FROM sources').fetchone()[0]
        if total-(prior[0] if prior else 0)+len(text.encode())>self.max_bytes or (not prior and self.conn.execute('SELECT count(*) FROM checkpoints').fetchone()[0]>=self.max_items):
            raise SpoolFull('checkpoint cache full; durable input retained')
        self.conn.execute('INSERT OR REPLACE INTO checkpoints VALUES(?,?,?)',(self.partition,packet['session_id'],text))

    def latest_checkpoint(self,session):
        row=self.conn.execute("SELECT payload FROM outbox WHERE partition=? AND session=? AND kind='checkpoint' ORDER BY rowid DESC LIMIT 1",(self.partition,session)).fetchone()
        if row is None:row=self.conn.execute('SELECT payload FROM checkpoints WHERE partition=? AND session=?',(self.partition,session)).fetchone()
        return json.loads(row['payload']) if row else None

    def note(self,code):
        if not isinstance(code,str) or len(code)>80 or not code.replace('_','').isalnum():raise ValueError('invalid status code')
        with self.conn:
            self.conn.execute('INSERT OR REPLACE INTO health VALUES(?,?)',(self.partition,code))
            self.conn.execute('DELETE FROM health WHERE rowid NOT IN (SELECT rowid FROM health ORDER BY rowid DESC LIMIT 64)')

    def status(self):
        row=self.conn.execute("SELECT count(*) pending,COALESCE(sum(state='blocked'),0) blocked,COALESCE(sum(bytes),0) bytes FROM outbox WHERE partition=?",(self.partition,)).fetchone()
        error=self.conn.execute('SELECT code FROM health WHERE partition=?',(self.partition,)).fetchone()
        return {**dict(row),'error':error['code'] if error else None,
            'source_bytes':self.conn.execute('SELECT COALESCE(sum(length(raw)),0) FROM sources WHERE partition=?',(self.partition,)).fetchone()[0]}
