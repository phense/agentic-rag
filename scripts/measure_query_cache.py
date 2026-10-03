#!/usr/bin/env python3
"""Read-only paired MCP inference measurement; exports aggregates, never queries."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import statistics
import sys
import time

os.environ['RAG_READONLY'] = '1'
from agentic_rag import db, embed, mcp_server, query_cache, search
from agentic_rag.config import load_config


def previous(name, path):
    spec = importlib.util.spec_from_file_location('agentic_rag._before_cache_' + name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def measure(before_dir, project, repetitions):
    old_embed = previous('embed', before_dir/'embed.py')
    old_search = previous('search', before_dir/'search.py')
    old_mcp = previous('mcp', before_dir/'mcp_server.py')
    old_mcp.run_search = old_search.search
    calls = Counter()
    for name, module, loader in [('before',old_search,old_embed.try_embed_texts),
                                 ('after',search,search.try_embed_texts)]:
        def counted(*args, _name=name, _loader=loader):
            calls[_name] += 1
            return _loader(*args)
        module.try_embed_texts = counted
    cfg = load_config()
    with db.connect(cfg,role='reader') as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        class Lease:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def __getattr__(self, name): return getattr(conn,name)
        # Same reader snapshot for both paths; excludes connection-open/stdio overhead.
        for module in (old_mcp,mcp_server):
            module._connect = lambda: (cfg,Lease())
        counts = conn.execute('SELECT (SELECT count(*) FROM documents) documents,'
                             '(SELECT count(*) FROM chunks) chunks').fetchone()
        at = datetime.now(timezone.utc).isoformat()
        query = 'Wie werden OAuth-Probleme bei der Newsletter-Erstellung behandelt?'
        cases = [('repeated_mcp_question',{'project':project}),
                 ('same_query_programming_domain',{'project':project,'domain':'programming'}),
                 ('same_query_global_trading_domain',{'scope':'global','domain':'trading'})]
        result = {'source_revision':'f27acd98e04c7c67d66ca374eded071ac47c0416',
            'before_sha256':{name:sha256((before_dir/(name+'.py')).read_bytes()).hexdigest()
                             for name in ['embed','search','mcp_server']},
            'after_sha256':{name:sha256(Path(module.__file__).read_bytes()).hexdigest()
                            for name,module in [('embed',embed),('search',search),('mcp_server',mcp_server),('query_cache',query_cache)]},
            'store_counts':counts, 'model':cfg.embed_model,
            'method':'reader-only repeatable-read snapshot; fixed as_of; alternating pairs; connection/stdio excluded',
            'repetitions_per_route':repetitions,'cases':{}}
        for label, options in cases:
            mcp_server._QUERY_CACHE.clear()
            calls.clear()
            samples={'before':[],'after':[]};first={};equal=0;valid=Counter()
            for iteration in range(repetitions+1):
                signatures={}
                routes=[('before',old_mcp),('after',mcp_server)]
                if iteration%2:routes.reverse()
                for name,module in routes:
                    start=time.perf_counter()
                    response=module.memory_search(query,as_of=at,**options)
                    elapsed=(time.perf_counter()-start)*1000
                    if response['warnings']:
                        raise RuntimeError('Inference unavailable; measurement invalid')
                    signatures[name]=[h['citation'] for h in response['results']]
                    for hit in response['results']:
                        raw=conn.execute('SELECT content FROM chunks WHERE id=%s',
                                         (hit['chunk_id'],)).fetchone()['content']
                        if raw[hit['snippet_start']:hit['snippet_end']] != hit['snippet']:
                            raise RuntimeError('Invalid citation')
                        if options.get('domain') and hit['domain'] != options['domain']:
                            raise RuntimeError('Domain leak')
                    if iteration==0:first[name]=elapsed
                    else:
                        samples[name].append(elapsed)
                        valid[name]+=len(response['results'])
                if iteration and signatures['before']==signatures['after']:equal+=1
            metrics={name:{'first_call_ms':round(first[name],3),
                'p50_ms':round(statistics.median(values),3),
                'p95_ms':round(sorted(values)[max(0,int(len(values)*.95+.999)-1)],3),
                'embedding_calls_including_first':calls[name],
                'validated_citations':valid[name]} for name,values in samples.items()}
            result['cases'][label]={'routes':metrics,'equal_citation_lists':equal,
                'p50_speedup':round(metrics['before']['p50_ms']/metrics['after']['p50_ms'],3)}
            print(json.dumps({'finished_case':label,**result['cases'][label]}),flush=True)
        conn.rollback()
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before-dir',type=Path,required=True)
    parser.add_argument('--project',required=True)
    parser.add_argument('--repetitions',type=int,default=20)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.repetitions<20:parser.error('at least20 paired repetitions required')
    result=measure(args.before_dir,args.project,args.repetitions)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()
