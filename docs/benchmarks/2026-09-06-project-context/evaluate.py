"""Synthetic replay of real hook/context readers; no provider or canonical writes."""
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import statistics
import tempfile
import time
from unittest.mock import patch

from agentic_rag import context,context_gate,db,pins,profiles,provider_health,store
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.benchmark.runner import source_hash
from agentic_rag.config import load_config
from agentic_rag.domains import seed_defaults
from agentic_rag.hooks import prompt_recall,session_start

HERE=Path(__file__).resolve().parent
PROJECT='/synthetic/context-a'


def run():
    cases=json.loads((HERE/'cases.json').read_text())
    assert cases['synthetic'] is True
    cfg=replace(load_config(),ollama_url='http://127.0.0.1:1')
    rows=[]
    with tempfile.TemporaryDirectory(prefix='rag-context-eval-') as temporary:
        with isolated_database(cfg) as isolated:
            with db.connect(isolated,role='writer') as writer:
                seed_defaults(writer)
                for item in cases['documents']:
                    kwargs=dict(title=item['title'],body=item['body'],domain='general',dtype=item.get('dtype','memory'),project=item['project'])
                    if item['stated']:
                        store.save_claim(writer,isolated,**kwargs,claim_kind='stated',evidence=[{'namespace':'synthetic-evaluation','source_id':item['id'],'role':'user','quote':item['body'],'complete':True}])
                    else:
                        store.save_document(writer,isolated,**kwargs)
                pins.add_pin(writer,body='Keep exact synthetic pin.\nRetain this condition.')
                store.refresh_profile(writer,isolated,PROJECT)
            with patch.object(prompt_recall,'load_config',lambda:isolated),patch.object(context_gate,'RECEIPT_DIR',Path(temporary)/'receipts'),patch.object(session_start,'WARNING_STATE',Path(temporary)/'absent'),patch.object(provider_health,'read_health',lambda:None):
                with db.connect(isolated,role='reader') as reader:
                    baseline_start=session_start.build_context(reader,isolated,PROJECT)
                    new_start=context.build(reader,isolated,project=PROJECT)['text']
                for case in cases['prompts']:
                    for variant in ('before','after'):
                        durations=[];texts=[];replays=[]
                        for repeat in range(3):
                            payload={'session_id':'synthetic-context','turn_id':f"{case['id']}-{variant}-{repeat}",'cwd':PROJECT,'prompt':case['prompt']}
                            begin=time.perf_counter()
                            if variant=='before':
                                sig=prompt_recall.detect_signature(case['prompt'])
                                with db.connect(isolated,role='reader') as reader:
                                    text=prompt_recall.error_context(reader,isolated,PROJECT,sig) if sig else ''
                                replay=text
                            else:
                                output=io.StringIO();prompt_recall.run(payload,output)
                                text=json.loads(output.getvalue())['hookSpecificOutput']['additionalContext'] if output.getvalue() else ''
                            durations.append((time.perf_counter()-begin)*1000)
                            if variant=='after':
                                output=io.StringIO();prompt_recall.run(payload,output)
                                replay=json.loads(output.getvalue())['hookSpecificOutput']['additionalContext'] if output.getvalue() else ''
                            texts.append(text);replays.append(replay)
                        assert all(len(t)<=4800 for t in texts)
                        assert all('foreign-secret-marker' not in t for t in texts)
                        rows.append({'id':case['id'],'split':case['split'],'variant':variant,'expected':case['expected'],'text':texts[0],
                                     'fired':bool(texts[0]),'useful':bool(case['expected'] and case['expected'] in texts[0]),
                                     'characters':len(texts[0]),'duplicate_expected_occurrences':max(0,texts[0].count(case['expected'])-1) if case['expected'] else 0,
                                     'replay_characters':statistics.mean(len(t) for t in replays),'latency_ms':durations})
    def metrics(items):
        positive=[r for r in items if r['expected']];fired=[r for r in items if r['fired']]
        times=sorted(t for r in items for t in r['latency_ms'])
        return {'queries':len(items),'useful_context_rate':sum(r['useful'] for r in positive)/len(positive) if positive else None,
                'firing_precision':sum(r['useful'] for r in fired)/len(fired) if fired else None,
                'unrelated_injections':sum(r['fired'] for r in items if not r['expected']),
                'context_characters_mean':statistics.mean(r['characters'] for r in items),
                'redundant_replay_characters_mean':statistics.mean(r['replay_characters'] for r in items),
                'redundant_replay_tokens_estimate_mean':statistics.mean(r['replay_characters']/4 for r in items),
                'duplicate_expected_occurrences':sum(r['duplicate_expected_occurrences'] for r in items),
                'latency_p95_ms':times[max(0,int(len(times)*.95+.999)-1)]}
    result={'synthetic':True,'corpus_sha256':hashlib.sha256((HERE/'cases.json').read_bytes()).hexdigest(),'source_sha256':source_hash(),
            'cleanup':'verified','hosted_calls':0,'repetitions_per_query':3,'context_cap':4800,
            'baseline':'existing error-signature recall helper; no regular project gate',
            'rows':rows,'summary':{v:metrics([r for r in rows if r['variant']==v]) for v in ('before','after')},
            'by_split':{s:{v:metrics([r for r in rows if r['variant']==v and r['split']==s]) for v in ('before','after')} for s in ('dev','test')},
            'startup':{'before':baseline_start,'after':new_start,'pin_faithful':all('Keep exact synthetic pin.\nRetain this condition.' in t for t in (baseline_start,new_start))}}
    (HERE/'results.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(result['summary'],indent=2))

if __name__=='__main__':run()
