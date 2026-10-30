"""Previewable native packaging with content ownership and retained recovery records."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shlex
import stat
import sys
import tempfile

HOSTS=('claude','codex','gemini')
RECORD='.rag-package.json'


def _json(value):
    return (json.dumps(value,sort_keys=True,indent=2)+'\n').encode()


def files(host, *, python=None, config=None, read_only=False):
    if host not in HOSTS:raise ValueError('unsupported native host; use existing agy/OpenCode adapter')
    python=str(Path(python or sys.executable).absolute())
    prefix=('AGENTIC_RAG_CONFIG='+shlex.quote(str(Path(config).absolute()))+' ') if config else ''
    if host=='gemini':
        events=('SessionStart','BeforeAgent','BeforeModel','AfterAgent','PreCompress','SessionEnd')
    else:
        events=('SessionStart','UserPromptSubmit','Stop','PreCompact','PostCompact','SessionEnd')
    hooks={event:[{'hooks':[{'type':'command',
        'command':prefix+shlex.quote(python)+' -m agentic_rag.plugins.lifecycle --host '+host+' --event '+event,
        'timeout':3000 if host=='gemini' else 3}]}] for event in events}
    mcp={'command':python,'args':['-m','agentic_rag.plugins.mcp']+(['--read-only'] if read_only else []),
         **({'env':{'AGENTIC_RAG_CONFIG':str(Path(config).absolute())}} if config else {})}
    manifest={'name':'agentic-rag','version':'0.6.12','description':'Source-backed knowledge, durable compaction handoffs and bounded queued tools.'}
    result={'hooks/hooks.json':_json({'hooks':{} if read_only else hooks})}
    if host=='gemini':
        manifest['mcpServers']={'agentic-rag':mcp}
        result['gemini-extension.json']=_json(manifest)
    else:
        manifest['mcpServers']='./.mcp.json'
        manifest['hooks']='./hooks/hooks.json'
        result[f'.{host}-plugin/plugin.json']=_json(manifest)
        result['.mcp.json']=_json({'mcpServers':{'agentic-rag':mcp}})
    return result


def _safe(root, relative):
    path=root/relative
    for item in (root,*path.relative_to(root).parents):
        candidate=item if item==root else root/item
        if candidate.is_symlink():raise ValueError('package path conflict: symlink')
    if path.is_symlink() or (path.exists() and not path.is_file()):raise ValueError('package file conflict')
    return path


def _write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,name=tempfile.mkstemp(prefix='.rag-write-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
        directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        if os.path.exists(name):os.unlink(name)


def manage(host,destination,*,action='install',apply=False,python=None,config=None,read_only=None):
    if action not in {'install','update','doctor','uninstall','recover'} or host not in HOSTS:raise ValueError('invalid package operation')
    root=Path(destination).expanduser().absolute()
    # Reject links in every existing ancestor, including ancestors of root.
    if any(item.is_symlink() for item in (root,*root.parents)):raise ValueError('package path conflict: symlink ancestor')
    record=_safe(root,RECORD)
    if record.exists() and record.stat().st_size>65536:raise ValueError('package record too large')
    old=json.loads(record.read_text()) if record.exists() else None
    if old and (old.get('version')!=1 or old.get('host')!=host or not isinstance(old.get('files'),dict)):
        raise ValueError('package ownership record conflict')
    options=(old or {}).get('options',{})
    python=python or options.get('python') or sys.executable
    config=config or options.get('config')
    read_only=options.get('read_only',False) if read_only is None else read_only
    options={'python':str(python),'config':str(config) if config else None,'read_only':read_only}
    proposed=files(host,python=python,config=config,read_only=read_only)
    owned=old.get('files',{}) if old else {}
    if len(owned)>8 or any(name not in proposed for name in owned):raise ValueError('package ownership record conflict')
    if 'pending_files' in (old or {}):
        if action!='recover':raise ValueError('interrupted package operation; preview recover before retry')
        pending=old['pending_files'];recovery=old.get('recovery',{})
        if not isinstance(pending,dict) or not isinstance(recovery,dict) or set(pending)-set(proposed) or set(recovery)!=set(owned):
            raise ValueError('package recovery record conflict')
        for name in set(owned)|set(pending):
            path=_safe(root,name)
            if path.exists() and (path.stat().st_size>32768 or hashlib.sha256(path.read_bytes()).hexdigest() not in {owned.get(name),pending.get(name)}):
                raise ValueError('package recovery conflict: '+name)
            if name in owned and (not isinstance(recovery[name],str) or hashlib.sha256(recovery[name].encode()).hexdigest()!=owned[name]):
                raise ValueError('package recovery content conflict')
        result={'preview':not apply,'host':host,'action':'recover','files':sorted(set(owned)|set(pending))}
        if not apply:return result
        for name in set(owned)|set(pending):
            path=_safe(root,name)
            if name in owned:_write(path,recovery[name].encode())
            elif path.exists():path.unlink()
        _write(record,_json({k:v for k,v in old.items() if k!='pending_files'}))
        return result
    if action=='recover':raise ValueError('no interrupted package operation')
    conflict=[]
    for relative in set(proposed)|set(owned):
        path=_safe(root,relative)
        if path.exists():
            if path.stat().st_size>32768:raise ValueError('package ownership conflict: oversized file')
            if relative not in owned or hashlib.sha256(path.read_bytes()).hexdigest()!=owned[relative]:conflict.append(relative)
        elif relative in owned:conflict.append(relative)
    if conflict:raise ValueError('package ownership conflict: '+', '.join(sorted(conflict)))
    if action=='doctor':
        return {'status':'ok' if old and owned else 'not_installed','host':host,'files':sorted(owned)}
    if action in {'update','uninstall'} and not old:raise ValueError('package is not owned')
    result={'preview':not apply,'host':host,'action':action,'destination':str(root),'files':sorted(proposed if action!='uninstall' else owned)}
    if not apply:return result
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    # Retain a bounded previous generation in the record; it contains package
    # wiring only, no token contents, source buffers or native user memories.
    recovery={name:(root/name).read_text() for name in owned}
    next_files={} if action=='uninstall' else {name:hashlib.sha256(data).hexdigest() for name,data in proposed.items()}
    _write(record,_json({'version':1,'host':host,'files':owned,'pending_files':next_files,'recovery':recovery,'options':(old or {}).get('options',options)}))
    if action=='uninstall':
        for name in owned:(root/name).unlink()
    else:
        for name,data in proposed.items():_write(_safe(root,name),data)
    _write(record,_json({'version':1,'host':host,'files':next_files,'recovery':recovery,'options':options}))
    return result


def add_parser(sub):
    parser=sub.add_parser('plugin',help='preview/manage an owned native plugin package')
    parser.add_argument('action',choices=['install','update','doctor','uninstall','recover'])
    parser.add_argument('--host',choices=HOSTS,required=True)
    parser.add_argument('--destination',type=Path,required=True)
    parser.add_argument('--config',type=Path)
    parser.add_argument('--python',type=Path)
    parser.add_argument('--read-only',action='store_true',default=None)
    parser.add_argument('--apply',action='store_true',help='write the previewed package; host activation remains explicit')


def run(args):
    print(json.dumps(manage(args.host,args.destination,action=args.action,apply=args.apply,
        python=args.python,config=args.config,read_only=args.read_only),sort_keys=True))
    return 0
