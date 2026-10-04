"""Bounded public native-provider prompt comparison; never a live prompt loader."""
from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import tempfile
import time
from unittest.mock import patch

from .. import db, mining, store
from ..validity import parse_time
from .database import isolated_database
from .identity import local_model,model_guard
from .runner import source_hash

PROMPTS = ('source', 'correction-v1')


def select(rows):
    """Use development evidence only; fewer unsafe outputs dominate recall."""
    def score(prompt):
        values = [r for r in rows if r['prompt'] == prompt]
        return (sum(r['unsafe'] for r in values) + sum(bool(r['error']) for r in values),
                -sum(r['user_correct'] for r in values), PROMPTS.index(prompt))
    return min(PROMPTS, key=score)


def _fixture(family):
    number = int(family[-1]); value = str(9840 + number + (10 if family.startswith('test') else 0))
    entity = 'nebula-' + family
    entries = [dict(uuid=family+'-user',type='user',timestamp='2026-03-01T00:00:00Z',
        message=dict(role='user',content=f'{entity} port is now {value}.')),
        dict(uuid=family+'-assistant',type='assistant',timestamp='2026-03-01T00:01:00Z',
            message=dict(role='assistant',content=f'Suggestion: {entity} port could be9991. This is unapproved.')),
        dict(uuid=family+'-hypothetical',type='user',timestamp='2026-03-01T00:02:00Z',
            message=dict(role='user',content=f'If a future prototype were deployed, {entity} port could be9900. This is hypothetical, not a current change.'))]
    return entity,value,entries


def _measure(cfg, family, prompt):
    entity,value,events = _fixture(family)
    row=dict(family=family,prompt=prompt,user_correct=False,unsafe=0,error=None,
        expected_user_facts=1,prohibited_suggestion_facts=2,provider_calls=0,prompt_chars=0,
        provider_token_cost=None,indexed_chunks=0,replay_identical=False,ms=None)
    with isolated_database(cfg) as owned, tempfile.TemporaryDirectory(prefix='rag-public-mining-') as name:
        path=Path(name)/'public.jsonl';path.write_text('\n'.join(json.dumps(e) for e in events)+'\n')
        consumed=mining.read_window(str(path),after_uuid=None,max_chars=owned.mine_max_digest_chars,per_block=owned.mine_per_block_chars)
        user_source=consumed.events[0]
        user_quote=user_source['text'].removeprefix('[user] ')
        row['source_input_sha256']=sha256(path.read_bytes()).hexdigest()
        with db.connect(owned,role='owner') as owner:
            owner.execute('GRANT SELECT ON benchmark_ownership TO rag_writer')
            owner.commit()
        with db.connect(owned,role='writer') as connection:
            old=store.save_assertion(connection,owned,entity=entity,attribute='port',value='9011',
                event_at='2026-01-01T00:00:00Z',domain='general',project='/synthetic/mining/'+family,
                evidence=dict(namespace='public-mining-fixture',source_id=family+'-old',role='user',quote=f'{entity} port is now9011'))
            if old.disposition!='accepted':raise ValueError('public source fixture was not accepted')
            original=mining.run_structured
            def counted(text,*args,**kwargs):
                row['provider_calls']+=1;row['prompt_chars']+=len(text)+len(kwargs.get('system') or '')
                return original(text,*args,**kwargs)
            start=time.perf_counter()
            try:
                with patch.object(mining,'run_structured',counted):
                    result=mining.mine_session(connection,owned,session_id='public-'+family,
                        transcript_path=str(path),last_uuid=None,project='/synthetic/mining/'+family,
                        benchmark_prompt=None if prompt=='source' else prompt)
                row['ms']=round((time.perf_counter()-start)*1000,3)
                facts=connection.execute('SELECT a.*,d.project_scope,d.domain FROM fact_assertions a JOIN documents d ON d.id=a.document_id WHERE a.document_id<>%s',(old.doc_id,)).fetchall()
                def gold(f):
                    chunks=connection.execute('SELECT id,content FROM chunks WHERE document_id=%s ORDER BY idx',(f['document_id'],)).fetchall()
                    return (f['entity']==entity and f['attribute']=='port' and f['value']==value
                        and f['relation']=='replacement' and f['disposition']=='accepted'
                        and f['event_at']==parse_time(user_source['timestamp'])
                        and f['evidence'].get('role')=='user' and f['domain']=='general'
                        and f['project_scope']=='/synthetic/mining/'+family
                        and f['evidence'].get('source_id')==user_source['source_id']
                        and f['evidence'].get('quote')==user_quote and f['evidence'].get('complete') is True
                        and f['evidence'].get('grounding')=='explicit_statement'
                        and len(chunks)==1 and value in chunks[0]['content'])
                row['user_correct']=any(gold(f) for f in facts)
                row['unsafe']=sum(f['disposition']=='accepted' and not gold(f) for f in facts)
                row['assertion_outputs']=[dict(entity=f['entity'],attribute=f['attribute'],value=f['value'],
                    disposition=f['disposition'],relation=f['relation'],source_role=f['evidence'].get('role')) for f in facts]
                row['missing_chunk_vectors']=connection.execute('SELECT count(*) n FROM chunks WHERE document_id<>%s AND embedding IS NULL',(old.doc_id,)).fetchone()['n']
                row['indexed_chunks']=connection.execute('SELECT count(*) n FROM chunks WHERE document_id<>%s',(old.doc_id,)).fetchone()['n']
                before=connection.execute('SELECT count(*) n FROM documents').fetchone()['n']
                def forbidden(*args,**kwargs):raise AssertionError('accepted extraction must replay without model')
                with patch.object(mining,'run_structured',forbidden):
                    replay=mining.mine_session(connection,owned,session_id='public-'+family,
                        transcript_path=str(path),last_uuid=None,project='/synthetic/mining/'+family,
                        benchmark_prompt='correction-v1')
                row['replay_identical']=json.loads(json.dumps(asdict(replay)))==json.loads(json.dumps(asdict(result))) and connection.execute('SELECT count(*) n FROM documents').fetchone()['n']==before
                if not row['replay_identical']:raise AssertionError('accepted replay changed original result')
            except Exception as exc:
                row['user_correct']=False
                row['error']=type(exc).__name__  # Content never enters an error label.
                row['ms']=round((time.perf_counter()-start)*1000,3)
    return row


def run(cfg, *, output: Path, model=False, progress=None):
    if model is not True:raise ValueError('explicit model authorization flag is required')
    expected_model=local_model(cfg)
    frozen_source=source_hash()
    prompt_hashes={prompt:sha256((mining.SYSTEM+mining.BENCHMARK_PROMPTS.get(prompt,'')).encode()).hexdigest() for prompt in PROMPTS}
    def guard():
        model_guard(cfg,expected_model)
        current={prompt:sha256((mining.SYSTEM+mining.BENCHMARK_PROMPTS.get(prompt,'')).encode()).hexdigest() for prompt in PROMPTS}
        if source_hash()!=frozen_source or current!=prompt_hashes:
            raise ValueError('prompt/source changed during mining comparison')
    output=Path(output)
    if output.exists():raise ValueError('choose a new public mining report directory')
    output.mkdir(parents=True)
    revision=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    development=[]
    for family in ('dev-0','dev-1'):
        for prompt in PROMPTS:
            guard()
            development.append(_measure(cfg,family,prompt))
            guard()
            if progress:progress('public development mining case completed')
    chosen=select(development)
    prompt_hash=sha256((mining.SYSTEM+mining.BENCHMARK_PROMPTS.get(chosen,'')).encode()).hexdigest()
    candidate=dict(version=1,public=True,synthetic=True,selection_split='dev',selected_prompt=chosen,
        selected_prompt_sha256=prompt_hash,prompt_sha256=prompt_hashes,source_revision=revision,
        development_families=['dev-0','dev-1'],
        profiles=list(PROMPTS),development=development,production_applied=False)
    encoded=json.dumps(candidate,sort_keys=True,separators=(',',':')).encode()
    (output/'candidate.json').write_bytes(encoded+b'\n')
    sealed=sha256(encoded).hexdigest()
    heldout=[]
    for family in ('test-0','test-1'):
        # Identical public inputs in fresh owned storage. Retain ties as baseline.
        for route,prompt in (('baseline','source'),('candidate',chosen)):
            guard()
            heldout.append(dict(_measure(cfg,family,prompt),route=route))
            guard()
            if progress:progress('public held-out mining case completed')
    guard()
    assert sha256((output/'candidate.json').read_bytes().rstrip(b'\n')).hexdigest()==sealed
    report=dict(version=1,source_revision=revision,source_sha256=frozen_source,embedding_identity=expected_model,
        prompt_sha256=prompt_hashes,provider=cfg.llm_provider,model=cfg.llm_model,
        candidate_sha256=sealed,selected_prompt=chosen,development=development,heldout=heldout,
        provider_calls=sum(r['provider_calls'] for r in development+heldout),
        cleanup='verified',production_application_writes=0,
        limits='Eight bounded actual configured-provider public calls maximum. Two independent families per split; no statistical gain/general model accuracy claim. Billing/token cost unavailable; prompt characters and resulting chunks recorded. Every provider failure remains a miss.')
    (output/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    return report
