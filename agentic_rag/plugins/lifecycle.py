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
AGY_EVENTS={'SessionStart':'session-start','PreInvocation':'pre-invocation','Stop':'stop'}


_BLOCKED_TYPES={'subagent','maintenance'}
_BLOCKED_FLAGS=(
    'is_sidechain','isSidechain',
    'is_subagent','isSubagent',
    'parent_session_id','parentSessionId','parentConversationId',
    'subagent_id','subagentId',
    'fork','isFork',
    'stop_hook_active','stopHookActive',
)


def eligible(payload):
    return common.is_interactive(payload) and not (
        any(payload.get(key) for key in _BLOCKED_FLAGS)
        or payload.get('agent_type') in _BLOCKED_TYPES
        or payload.get('agentType') in _BLOCKED_TYPES)


@contextmanager
def client_kind(host):
    previous=sys.argv
    sys.argv=['agentic-rag-native','--client',host]
    try:yield
    finally:sys.argv=previous


def dispatch(host,event,payload,stdout):
    if not eligible(payload):
        if host=='antigravity':stdout.write('{}\n')
        return
    if host=='gemini':
        from .gemini import dispatch as gemini
        return gemini(event,payload,stdout)
    if host=='antigravity':
        if event not in AGY_EVENTS:raise ValueError('unsupported native event')
        from ..hooks import agy
        json.dump(agy.run(AGY_EVENTS[event],payload),stdout)
        stdout.write('\n')
        return
    if host not in {'claude','codex'} or event not in EVENTS:raise ValueError('unsupported native event')
    payload={**payload,'client':host}
    with client_kind(host):
        module=importlib.import_module('agentic_rag.hooks.'+EVENTS[event])
        if event in {'Stop','SessionEnd'}:module.run(payload)
        else:module.run(payload,stdout)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--host',choices=['claude','codex','gemini','antigravity'],required=True)
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
        elif args.host=='antigravity':sys.stdout.write('{}\n')
    return 0


if __name__=='__main__':raise SystemExit(main())
