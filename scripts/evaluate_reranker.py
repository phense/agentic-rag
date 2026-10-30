"""Evaluate built-in public fixtures against an explicitly started local reranker."""
import argparse
import json
from pathlib import Path

from agentic_rag.benchmark.rerank_evaluation import run
from agentic_rag.config import Config


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',required=True)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--tiny-url',help='Optional separately pinned local Jina tiny comparison')
    parser.add_argument('--owned-pg-data',required=True,type=Path)
    parser.add_argument('--socket-dir',required=True)
    parser.add_argument('--runtime-manifest',required=True,type=Path)
    parser.add_argument('--repeats',type=int,default=2)
    args=parser.parse_args()
    result=run(Config(db_host=args.socket_dir,ollama_url='http://127.0.0.1:1',rerank_url=args.url),output=args.output,
        repeats=args.repeats,tiny_url=args.tiny_url,owned_pg_data=args.owned_pg_data,runtime_manifest=args.runtime_manifest,
        progress=lambda split,identity:print(json.dumps({'split':split,'finished':identity}),flush=True))
    print(json.dumps({'choice':result['candidate']['choice'],'heldout':{
        p:v['summary'] for p,v in result['heldout']['profiles'].items()}},indent=2))


if __name__=='__main__':main()
