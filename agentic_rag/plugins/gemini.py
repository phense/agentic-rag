"""Gemini CLI JSON/JSONL recording adapter, separate from Antigravity.

PreCompress and SessionEnd are advisory/best effort in Gemini. Capture also at
completed turns and BeforeModel. Resume at the next BeforeAgent, not an invented
PostCompress event. Recording users and BeforeAgent inputs may be synthetic host/hook text.
Keep all Gemini prose advisory until the host provides an authorship discriminator.
"""
from __future__ import annotations
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from ..config import load_config
from ..hooks import common
from ..secrets import strip_secrets
from ..service.spool import Spool, canonical
from .package import _write

MAX_SOURCE = 16*1024*1024


def normalize(raw,session):
    if not isinstance(raw,bytes) or len(raw)>MAX_SOURCE:raise ValueError('Gemini recording exceeds source limit')
    try:
        value=json.loads(raw)
    except (ValueError,UnicodeDecodeError):
        if not raw.endswith(b'\n'):raise ValueError('incomplete Gemini JSONL recording') from None
        value=None
    if isinstance(value,dict) and isinstance(value.get('messages'),list):
        if value.get('sessionId')!=session:raise ValueError('Gemini recording session mismatch')
        records=value['messages']
    elif isinstance(value,dict) and value.get('sessionId')==session and 'messages' not in value:
        records=[value]  # actual new-session JSONL begins with metadata only
    elif value is None:
        records=[json.loads(line) for line in raw.splitlines() if line.strip()]
        headers=[r for r in records if isinstance(r,dict) and 'sessionId' in r]
        if not headers or headers[0].get('sessionId')!=session:raise ValueError('Gemini recording session mismatch')
    else:raise ValueError('unsupported Gemini recording')
    output=[];latest={}
    def append(record):
        if not isinstance(record,dict):raise ValueError('invalid Gemini record')
        kind=record.get('type');identity=record.get('id')
        if kind not in {'user','gemini'}:return
        if not isinstance(identity,str) or not identity or len(identity)>256:raise ValueError('invalid Gemini message identity')
        latest[identity]=record
        content=record.get('content','')
        if isinstance(content,list):content='\n'.join(text for part in content if (text := part.get('text','') if isinstance(part,dict) else part if isinstance(part,str) else ''))
        if not isinstance(content,str):raise ValueError('invalid Gemini prose')
        if not content.strip():return
        digest=hashlib.sha256(canonical([identity,kind,content]).encode()).hexdigest()
        output.append({'uuid':'gemini:'+identity+':'+digest,'type':'assistant',
            'source_origin':'unverified_user_history' if kind=='user' else 'model',
            'timestamp':record.get('timestamp'),'original_id':identity,'original_sha256':hashlib.sha256(canonical(record).encode()).hexdigest(),
            'message':{'role':'assistant','content':content}})
    for record in records:
        if not isinstance(record,dict):raise ValueError('invalid Gemini recording')
        if '$patch' in record:
            patch=record['$patch']
            if not isinstance(patch,dict):raise ValueError('unsupported Gemini patch')
            updates=patch.get('updates',[patch] if 'id' in patch else [])
            if not isinstance(updates,list):raise ValueError('unsupported Gemini patch')
            for update in updates:
                if not isinstance(update,dict):raise ValueError('unsupported Gemini patch')
                prior=latest.get(update.get('id'))
                if prior and 'content' in update:append({**prior,'content':update['content']})
        else:append(record)
    return output


def capture(cfg,payload):
    session=payload.get('session_id')
    if not isinstance(session,str) or not 1<=len(session)<=256:raise ValueError('missing Gemini session')
    path=Path(payload['transcript_path'])
    error=None;records=[]
    try:
        with path.open('rb') as source:raw=source.read(MAX_SOURCE+1)
        records=normalize(raw,session)
    except (OSError,ValueError) as exc:error=exc
    prompt=payload.get('_observed_prompt')
    if isinstance(prompt,str) and prompt.strip():
        prompt=strip_secrets(prompt)[0]
        identity=hashlib.sha256(canonical([session,payload.get('prompt_id'),records[-1]['uuid'] if records else None,prompt]).encode()).hexdigest()
        records.append({'uuid':'gemini-input:'+identity,'type':'assistant','source_origin':'BeforeAgent.ambiguous_input',
            'timestamp':payload.get('timestamp'),'message':{'role':'assistant','content':prompt}})
    from ..service.local import project
    if cfg.service_mode=='client':
        from ..service.client import RemoteClient
        with RemoteClient(cfg) as client:
            partition=client.partition
    else:partition='gemini-local'
    with Spool(cfg.service_spool_dir/'spool.sqlite',partition) as spool:
        prior=next((r for r in spool.sources() if r['session']==session),None)
        normalized=prior['raw'] if prior else b''
        seen={json.loads(line)['uuid'] for line in normalized.splitlines()}
        new=[record for record in records if record['uuid'] not in seen]
        normalized+=b''.join((canonical(record)+'\n').encode() for record in new)
        spool.capture_source(session,project(payload),normalized)
        # A bounded mirror lets the existing local mining/checkpoint parser keep
        # its original DTOs. Pending evidence remains in the private spool.
        mirror=cfg.service_spool_dir/'gemini'/(hashlib.sha256((partition+session).encode()).hexdigest()+'.jsonl')
        if mirror.is_symlink() or mirror.parent.is_symlink():raise ValueError('Gemini mirror path conflict')
        _write(mirror,normalized)
    if error is not None:raise error  # observed input is durable even if history is malformed
    return {**payload,'transcript_path':str(mirror),'client':'claude'},records


def checkpoint(cfg,payload,records):
    from ..service.local import pre_compact
    from ..continuity.capture import capture_snapshot_seed
    from ..continuity import store
    trigger=payload.get('trigger')
    if trigger not in {'manual','auto'}:raise ValueError('invalid compression trigger')
    if cfg.service_mode=='client':
        pre_compact(cfg,payload)
        from ..service.client import RemoteClient
        with RemoteClient(cfg) as client:
            packet=client.spool.latest_checkpoint(payload['session_id'])
            tail='\n'.join('['+r['message']['role']+'] '+r['message']['content'] for r in records[-6:])
            packet['handoff']='Retained original conversation tail (advisory; extraction may be queued):\n'+strip_secrets(tail)[0][-6000:]
            client.stage_checkpoint(packet)
    else:
        from .. import db
        seed=capture_snapshot_seed({**payload,'hook_event_name':'PreCompact'})
        with db.connect(cfg,role='writer') as conn:
            saved=store.upsert_snapshot(conn,seed,update_existing=False)
            tail='\n'.join('['+r['message']['role']+'] '+r['message']['content'] for r in records[-6:])
            store.attach_handoff(conn,saved.id,'Retained original conversation tail (advisory):\n'+strip_secrets(tail)[0][-6000:],max_chars=cfg.checkpoint_handoff_max_chars)


def dispatch(event,payload,stdout):
    if event not in {'SessionStart','BeforeAgent','BeforeModel','AfterAgent','PreCompress','SessionEnd'}:raise ValueError('unsupported Gemini event')
    cfg=load_config()
    if event=='BeforeAgent':payload={**payload,'_observed_prompt':payload.get('prompt')}
    internal=payload;records=[]
    if payload.get('transcript_path') and (Path(payload['transcript_path']).is_file() or isinstance(payload.get('_observed_prompt'),str)):
        internal,records=capture(cfg,payload)
    if event=='PreCompress':
        checkpoint(cfg,internal,records)
    elif event in {'AfterAgent','SessionEnd'}:
        from ..hooks.transcript_delta import enqueue_transcript_delta
        enqueue_transcript_delta(internal,hook='gemini.'+event)
    elif event in {'SessionStart','BeforeAgent'}:
        if cfg.service_mode=='client':
            from ..service.client import RemoteClient
            from ..service.local import context,post_compact
            with RemoteClient(cfg) as client:packet=client.spool.latest_checkpoint(payload['session_id'])
            if packet and not packet['compacted'] and event=='BeforeAgent':
                post_compact(cfg,{**internal,'trigger':packet['snapshot']['trigger']})
            text=context(cfg,internal)
        else:
            from .. import db
            from ..hooks.session_start import build_context
            with db.connect(cfg,role='writer') as conn:
                text=build_context(conn,cfg,payload.get('cwd'),session_id=payload.get('session_id'),source='resume' if event=='BeforeAgent' else 'startup')
        json.dump({'hookSpecificOutput':{'additionalContext':text[:10000]}},stdout)
    if event in {'AfterAgent','SessionEnd','PreCompress'}:common.spawn_worker()
