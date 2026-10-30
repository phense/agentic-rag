"""Thin native lifecycle adapter. Host JSON differs; engine, DTOs and spool do not."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import importlib
import json
import sys

from ..hooks import common

EVENTS={'SessionStart':'session_start','UserPromptSubmit':'prompt_recall','Stop':'stop_enqueue',
        'PreCompact':'pre_compact','PostCompact':'post_compact','SessionEnd':'session_end'}


def eligible(payload):
    return common.is_interactive(payload) and not (
        payload.get('is_sidechain') or payload.get('parent_session_id') or payload.get('subagent_id')
        or payload.get('fork') or payload.get('agent_type') in {'subagent','maintenance'}
        or payload.get('stop_hook_active'))


@contextmanager
def client_kind(host):
    previous=sys.argv
    sys.argv=['agentic-rag-native','--client',host]
    try:yield
    finally:sys.argv=previous


def dispatch(host,event,payload,stdout):
    if not eligible(payload):return
    if host=='gemini':
        from .gemini import dispatch as gemini
        return gemini(event,payload,stdout)
    if host not in {'claude','codex'} or event not in EVENTS:raise ValueError('unsupported native event')
    payload={**payload,'client':host}
    with client_kind(host):
        module=importlib.import_module('agentic_rag.hooks.'+EVENTS[event])
        if event in {'Stop','SessionEnd'}:module.run(payload)
        else:module.run(payload,stdout)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--host',choices=['claude','codex','gemini'],required=True)
    parser.add_argument('--event',required=True)
    args=parser.parse_args()
    try:
        # Native hook input itself is finite, including malicious/drifting hosts.
        data=sys.stdin.buffer.read(65537)
        if len(data)>65536:raise ValueError('hook_input_too_large')
        payload=json.loads(data)
        if not isinstance(payload,dict):raise ValueError('invalid_hook_input')
        dispatch(args.host,args.event,payload,sys.stdout)
    except Exception as exc:
        common.log_hook_error('native.'+args.host,type(exc).__name__)
        if args.host=='gemini':json.dump({'systemMessage':'agentic-rag hook delayed; retain original transcript.'},sys.stdout)
    return 0


if __name__=='__main__':raise SystemExit(main())
