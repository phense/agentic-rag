#!/usr/bin/env python3
"""Encode exact frozen canonical chunks and lifecycle probes, offline.

This separate pass does not replace the frozen raw-body experiment. Outputs
may be replayed only for identical model, role and input bytes in the owned
database lifecycle rehearsal; replay timings are never model timings.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import time

from benchmark_embeddings import assert_owned_listener, deny_network, http, normalized, require_free_port, verify_files, write


def worker(args):
    out=Path(args.output);out.mkdir(mode=0o700)
    spec_path=Path(args.inputs);spec_bytes=spec_path.read_bytes();spec=json.loads(spec_bytes)
    snapshot=Path(args.model_dir)
    descriptor=spec['model_identities'][args.model]
    width=descriptor['dimensions'];daemon=None;daemon_log=None
    result={'schema':1,'status':'failed','model':args.model,'descriptor':descriptor,
        'input_sha256':hashlib.sha256(spec_bytes).hexdigest(),
        'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'started':datetime.now(timezone.utc).isoformat(),'observations':[]}
    vectors={'documents':{},'queries':{},'auxiliary':{}}
    began=time.perf_counter()
    try:
        if args.model=='bge':
            data=(snapshot/'manifests/registry.ollama.ai/library/bge-m3-q8/latest').read_bytes()
            if hashlib.sha256(data).hexdigest()!=descriptor['digest']:raise ValueError('BGE manifest identity')
            manifest=json.loads(data)
            for layer in [manifest['config'],*manifest['layers']]:
                p=snapshot/'blobs'/layer['digest'].replace(':','-')
                with p.open('rb') as stream:
                    if hashlib.file_digest(stream,'sha256').hexdigest()!=layer['digest'].split(':')[1]:
                        raise ValueError('BGE blob identity')
            require_free_port()
            daemon_log=(out/'ollama.log').open('w')
            daemon=subprocess.Popen(['/usr/local/bin/ollama','serve'],stdout=daemon_log,stderr=subprocess.STDOUT,
                env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':str(out),'OLLAMA_MODELS':str(snapshot),
                     'OLLAMA_HOST':'127.0.0.1:11583','OLLAMA_NUM_PARALLEL':'1',
                     'OLLAMA_MAX_LOADED_MODELS':'1','OLLAMA_NO_CLOUD':'1'})
            for _ in range(100):
                if daemon.poll() is not None:raise RuntimeError('owned BGE daemon exited')
                try:
                    tags=http('http://127.0.0.1:11583','/api/tags')
                    assert_owned_listener(daemon);break
                except OSError:time.sleep(.1)
            else:raise RuntimeError('owned BGE readiness deadline')
            if not any(m['digest']==descriptor['digest'] for m in tags['models']):raise ValueError('BGE discovery identity')
            def encode(texts,purpose):
                response=http('http://127.0.0.1:11583','/api/embed',{'model':descriptor['model'],'input':texts,
                    'truncate':False,'keep_alive':'10m','options':{'num_thread':2}})
                # Ollama enforces truncate=False. Its response does not expose per-input token lengths.
                return response['embeddings'],{'prompt_eval_count_total':response.get('prompt_eval_count'),
                    'truncation':'server rejects rather than truncates','token_lengths':None}
        else:
            manifest=json.loads((snapshot.parent/(args.model+'-manifest.json')).read_text())
            if manifest['revision']!=descriptor['revision'] or manifest['repo']!=descriptor['repo']:
                raise ValueError('Jina pinned repository/revision')
            verify_files(snapshot,manifest);deny_network()
            import torch
            from transformers import AutoModel
            torch.set_num_threads(2);torch.set_num_interop_threads(1)
            model=AutoModel.from_pretrained(str(snapshot),trust_remote_code=True,modality='text',
                task='retrieval',dtype=torch.float32,local_files_only=True).eval()
            if model._modality!='text':raise ValueError('unexpected modality')
            def encode(texts,purpose):
                prefix='Query: ' if purpose=='query' else 'Document: '
                lengths=[len(x) for x in model.tokenizer([prefix+t for t in texts],truncation=False)['input_ids']]
                if max(lengths)>spec['max_tokens']:raise ValueError('would truncate canonical input')
                with torch.inference_mode():
                    values=model.encode(texts,task='retrieval',prompt_name=purpose,max_length=spec['max_tokens']).float().tolist()
                return values,{'token_lengths':lengths,'truncated_inputs':0}
        result['load_seconds']=time.perf_counter()-began
        for group in ('documents','queries','auxiliary'):
            rows=spec[group]
            # Query purpose is explicit; auxiliary records carry their own role.
            offset=0
            while offset<len(rows):
                first=rows[offset];purpose=first.get('purpose','query' if group=='queries' else 'document')
                batch=[]
                for row in rows[offset:offset+spec['batch_size']]:
                    if row.get('purpose','query' if group=='queries' else 'document')!=purpose:break
                    batch.append(row)
                started=time.perf_counter();values,info=encode([r['text'] for r in batch],purpose)
                if len(values)!=len(batch):raise ValueError('incomplete inference batch')
                for row,value in zip(batch,values):
                    normalized(value,width)
                    vectors[group][row['id']]=value
                observation={'group':group,'ids':[r['id'] for r in batch],'purpose':purpose,
                    'input_sha256':[hashlib.sha256(r['text'].encode()).hexdigest() for r in batch],
                    'seconds':time.perf_counter()-started,**info}
                result['observations'].append(observation)
                write(out/'vectors.json',vectors);write(out/'result.json',result)
                offset+=len(batch)
        if args.model!='bge':verify_files(snapshot,manifest)
        if spec_path.read_bytes()!=spec_bytes:raise ValueError('frozen inputs changed')
        result['status']='complete'
    except Exception as exc:
        result['failure']={'class':type(exc).__name__,'message':str(exc)[:1000]};raise
    finally:
        if daemon is not None:
            try:
                assert_owned_listener(daemon)
                http('http://127.0.0.1:11583','/api/embed',{'model':descriptor['model'],'input':[],'keep_alive':0})
            except Exception:pass
            daemon.terminate()
            try:daemon.wait(timeout=15)
            except subprocess.TimeoutExpired:daemon.kill();daemon.wait(timeout=5)
            daemon_log.close()
        result.update(finished=datetime.now(timezone.utc).isoformat(),wall_seconds=time.perf_counter()-began,
            cpu_self_seconds=time.process_time(),peak_self_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
            completed={g:len(v) for g,v in vectors.items()},planned={g:len(spec[g]) for g in vectors})
        write(out/'result.json',result)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',choices=('bge','small','nano'),required=True)
    for name in ('inputs','model-dir','output'):parser.add_argument('--'+name,required=True)
    worker(parser.parse_args())
