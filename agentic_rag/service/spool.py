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
          CREATE TABLE IF NOT EXISTS tool_requests(id TEXT PRIMARY KEY,partition TEXT NOT NULL,
            fingerprint TEXT NOT NULL,envelope TEXT NOT NULL,server_id TEXT,code TEXT,created REAL NOT NULL,last_checked REAL NOT NULL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS health(partition TEXT PRIMARY KEY,code TEXT);
        ''')

        if 'last_checked' not in {r[1] for r in self.conn.execute('PRAGMA table_info(tool_requests)')}:
            self.conn.execute('ALTER TABLE tool_requests ADD COLUMN last_checked REAL NOT NULL DEFAULT 0')

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

    def extraction_states(self,session):
        rows=[json.loads(r['receipt']) for r in self.conn.execute('SELECT receipt FROM receipts WHERE partition=? ORDER BY created DESC LIMIT 256',(self.partition,))]
        return [r for r in rows if r.get('kind')=='window' and r.get('session')==session][:3]

    def receipt_state(self,value):
        if len(canonical(value).encode())>4096:raise ValueError('invalid receipt status')
        with self.conn:
            self.conn.execute("UPDATE receipts SET receipt=? WHERE partition=? AND json_extract(receipt,'$.receipt')=?",(canonical(value),self.partition,value['receipt']))

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

    def stage_request(self,tool,arguments):
        import uuid
        from datetime import datetime,timezone
        fingerprint=hashlib.sha256(canonical([tool,arguments]).encode()).hexdigest()
        envelope=canonical({'idempotency_key':str(uuid.uuid4()),'created_at':datetime.now(timezone.utc).isoformat(),
                            'tool':tool,'arguments':arguments})
        self.conn.execute('BEGIN IMMEDIATE')
        try:
            existing=self.conn.execute('SELECT id FROM tool_requests WHERE partition=? AND fingerprint=?',(self.partition,fingerprint)).fetchone()
            if existing:
                self.conn.rollback()
                return existing['id']
            count,total=self.conn.execute('SELECT count(*),COALESCE(sum(length(CAST(envelope AS BLOB))),0) FROM tool_requests').fetchone()
            if count>=64 or total+len(envelope.encode())>4*1024*1024 or len(envelope.encode())>60*1024:
                raise SpoolFull('request spool full; pending requests retained')
            identity='local.'+str(uuid.uuid4())
            self.conn.execute('INSERT INTO tool_requests(id,partition,fingerprint,envelope,created) VALUES(?,?,?,?,?)',
                              (identity,self.partition,fingerprint,envelope,time.time()))
            self.conn.commit()
            return identity
        except BaseException:
            self.conn.rollback();raise

    def pending_requests(self):
        return [dict(r) for r in self.conn.execute('SELECT * FROM tool_requests WHERE partition=? ORDER BY last_checked,created',(self.partition,))]

    def request_record(self,identity):
        row=self.conn.execute('SELECT * FROM tool_requests WHERE id=? AND partition=?',(identity,self.partition)).fetchone()
        if row is None:raise ValueError('unknown local request')
        return dict(row)

    def request_by_server(self,identity):
        row=self.conn.execute('SELECT id FROM tool_requests WHERE partition=? AND server_id=?',(self.partition,identity)).fetchone()
        return row['id'] if row else None

    def request_touch(self,identity):
        with self.conn:self.conn.execute('UPDATE tool_requests SET last_checked=? WHERE id=? AND partition=?',(time.time(),identity,self.partition))

    def request_ack(self,identity,server_id):
        import uuid
        server_id=str(uuid.UUID(server_id))
        with self.conn:
            self.conn.execute('UPDATE tool_requests SET server_id=?,code=NULL WHERE id=? AND partition=?',(server_id,identity,self.partition))

    def request_finish(self,identity):
        with self.conn:self.conn.execute('DELETE FROM tool_requests WHERE id=? AND partition=?',(identity,self.partition))

    def request_error(self,identity,code):
        if not isinstance(code,str) or not code.replace('_','').isalnum() or len(code)>80:code='request_failed'
        with self.conn:self.conn.execute('UPDATE tool_requests SET code=? WHERE id=? AND partition=?',(code,identity,self.partition))

    def request_summaries(self,limit=8):
        return [dict(r) for r in self.conn.execute("SELECT id,server_id,code,json_extract(envelope,'$.tool') tool FROM tool_requests WHERE partition=? ORDER BY created LIMIT ?",
            (self.partition,min(8,max(0,int(limit)))))]
