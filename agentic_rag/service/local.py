"""Local durable capture and offline continuation; never opens the knowledge DB."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile

from ..continuity.capture import capture_snapshot_seed
from ..continuity.model import bound_handoff
from ..mining_window import read_window
from ..scope import project_id
from ..secrets import strip_secrets_json
from .client import RemoteClient
from .spool import SpoolFull


def project(payload):
    return project_id(payload['cwd']) if payload.get('cwd') else 'unknown'


def capture_transcript(cfg,payload):
    path=Path(payload['transcript_path'])
    with RemoteClient(cfg) as client,path.open('rb') as stream:
        # A bounded snapshot, not a pointer to a file that may disappear after Stop.
        raw=stream.read(client.spool.max_bytes+1)
        if len(raw)>client.spool.max_bytes:
            client.spool.note('source_capacity_exceeded')
            raise SpoolFull('transcript exceeds local buffer; retain source and run service spool recovery')
        try:client.spool.capture_source(payload['session_id'],project(payload),raw)
        except (SpoolFull,ValueError):
            client.spool.note('source_capture_failed');raise
        client.spool.note('source_captured')


def stage_sources(client,*,max_windows=8):
    staged=0
    for source in client.spool.sources():
        # read_window retains original line hashes and redacts prose before upload.
        fd,path=tempfile.mkstemp(prefix='source-',dir=client.spool.path.parent)
        try:
            with os.fdopen(fd,'wb') as stream:stream.write(source['raw'])
            for _ in range(max_windows-staged):
                before=client.spool.cursor(source['session'])
                window=read_window(path,after_uuid=before or None)
                if window.warnings:client.spool.note('source_input_needs_completion_or_repair')
                if not window.last_uuid or window.last_uuid==before:break
                value=asdict(window)
                value.pop('last_uuid')
                value['events']=[{**event,'role':event['role'] or 'unknown'} for event in value['events']]
                value['warnings']=list(value['warnings'])[:16]
                client.stage_window({'version':1,'session_id':source['session'],'project':source['project'],
                    'input_cursor':before,'output_cursor':window.last_uuid,'window':value})
                staged+=1
                if not window.has_more:break
        finally:
            os.unlink(path)
        if staged>=max_windows:break
    return staged


def pre_compact(cfg,payload):
    snapshot=asdict(capture_snapshot_seed({**payload,'hook_event_name':'PreCompact'}))
    session=snapshot.pop('session_id');snapshot.pop('project_root')
    snapshot['artifacts']=list(snapshot['artifacts']);snapshot['warnings']=list(snapshot['warnings'])
    snapshot,_=strip_secrets_json(snapshot)
    packet={'version':1,'session_id':session,'project':project(payload),'snapshot':snapshot,'handoff':None,'compacted':False}
    with RemoteClient(cfg) as client:
        identity=client.stage_checkpoint(packet)  # durable before optional repository/network work
    return identity


def post_compact(cfg,payload):
    with RemoteClient(cfg) as client:
        packet=client.spool.latest_checkpoint(payload['session_id'])
        if not packet or packet['snapshot']['trigger']!=payload.get('trigger'):return
        turn=payload.get('turn_id')
        if turn and packet['snapshot']['turn_id']!=turn:return
        packet['compacted']=True
        summary=payload.get('compact_summary')
        if isinstance(summary,str) and summary.strip():
            packet['handoff']=bound_handoff(summary,max_chars=min(8000,cfg.checkpoint_handoff_max_chars))
        client.stage_checkpoint(packet)


def context(cfg,payload,*,prompt=None):
    with RemoteClient(cfg) as client:
        session=payload.get('session_id') or ''
        text=client.context(session,project(payload),prompt=prompt)
        if prompt is None:
            status=client.spool.status()
            warning=''
            if status['pending'] or status['error'] not in {None,'source_captured'}:
                warning=f"⚠️ agentic-rag upload: {status['pending']} pending, {status['blocked']} blocked; {status['error'] or 'input_retained'}.\n"
            packet=client.spool.latest_checkpoint(session)
            if packet and packet['project']==project(payload):
                snapshot=packet['snapshot']
                handoff=packet.get('handoff')
                detail=handoff or json.dumps({'cursor':snapshot['cursor'],'turn_id':snapshot['turn_id'],
                    'trigger':snapshot['trigger'],'warnings':snapshot['warnings']},ensure_ascii=False)
                # Keep continuation ahead of lower-priority cached context in a 10k hook.
                text=('## Durable local checkpoint (advisory)\n'+detail+'\n'+text)[:10000]
            text=warning+text[:max(0,10000-len(warning))]
        return text
