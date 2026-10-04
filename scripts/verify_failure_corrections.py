#!/usr/bin/env python3
"""Controlled public fixtures through the private, provider-free correction API.

Import ``rehearse(cfg, private_dir=NEW_ABSOLUTE_DIRECTORY)`` from the main
verification driver. The directory stays outside Git, mode0700; private artifacts
remain mode0600. Only aggregate metrics leave this helper. No canonical database
is opened: isolated_database owns creation, migration and verified cleanup.
"""
from __future__ import annotations

from contextlib import ExitStack
import json
from pathlib import Path
from unittest.mock import patch

from psycopg import sql

from agentic_rag import db, embed, embedding_reuse, llm, neural_rerank, store
from agentic_rag.benchmark import corrections
from agentic_rag.benchmark.database import isolated_database

PROJECT='/synthetic/failure-corrections'
DOMAIN='general'
MAX_FAMILIES=12  # Two exact cases each, plus three negative families: below32.


def _require(condition):
    if not condition:raise ValueError('controlled correction rehearsal invariant failed')


def _inventory(conn):
    tables=conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' "
        "AND table_type='BASE TABLE' ORDER BY table_name").fetchall()
    return {r['table_name']:{row['row'] for row in conn.execute(sql.SQL('SELECT to_jsonb(t)::text AS row FROM {} t')
        .format(sql.Identifier(r['table_name'])))} for r in tables}


def _save(conn,cfg,entity,attribute,value,event,*,relation='replacement',role='user',complete=True,confirmed=True):
    source=f'public-correction:{entity}:{attribute}:{event}'
    result=store.save_assertion(conn,cfg,entity=entity,attribute=attribute,value=value,
        event_at=event,relation=relation,domain=DOMAIN,project=PROJECT,actor='benchmark',
        evidence={'namespace':'public-controlled','source_id':source,'role':role,
            'quote':f'{entity} {attribute} is now {value}', 'complete':complete})
    _require(result.disposition==('accepted' if role=='user' else 'review'))
    if confirmed:
        store.review_claim(conn,result.doc_id,state='confirmed',reason='Explicit public fixture user confirmation',actor='benchmark')
    return result.doc_id


def _family(conn,cfg,index):
    target=f'Public Correction Service {index}';alias=f'Public Former Service {index}'
    expected={}
    for entity,attribute,old,new in ((target,'port',str(6000+index),str(8000+index)),
                                    (alias,'capacity',str(200+index),str(400+index))):
        _save(conn,cfg,entity,attribute,old,'2026-01-01T00:00:00Z',relation='assertion')
        document=_save(conn,cfg,entity,attribute,new,'2026-02-01T00:00:00Z')
        expected[document]=(entity,attribute,new)
    relation=store.save_entity_alias(conn,cfg,alias=alias,target=target,domain=DOMAIN,project=PROJECT,
        effective_at='2026-03-01T00:00:00Z',confirm=True,actor='benchmark',
        evidence={'namespace':'public-controlled','source_id':f'public-alias:{index}','role':'user',
            'quote':f'{alias} is the same service as {target}','complete':True})
    _require(relation['state']=='accepted')
    return expected


def _candidate_summary(path,aggregate):
    """Read the actual private candidate; export only aggregate selection fields."""
    try:
        candidate=json.loads(corrections._private_path(path,existing=True).read_bytes())
        candidate=corrections._verify_private_candidate(path,candidate)
        _require(candidate['artifact_sha256']==aggregate['candidate_sha256'])
        _require(candidate['profile']==aggregate['chosen'] and candidate['dev']==aggregate['dev'])
        _require(aggregate['status']=='sealed' and aggregate['heldout_evaluations']==1)
        return dict(chosen=aggregate['chosen'],profiles=aggregate['profiles'],dev=aggregate['dev'],
            heldout=aggregate['heldout'],dev_families=aggregate['dev_families'],
            test_families=aggregate['test_families'],heldout_evaluations=aggregate['heldout_evaluations'],
            candidate_readback_verified=True)
    except (OSError,ValueError,KeyError,TypeError):
        raise ValueError('controlled private candidate readback failed') from None


def rehearse(cfg, *, private_dir):
    """Use a NEW private directory; return counts only after owned cleanup succeeds."""
    private=Path(private_dir)
    _require(not private.exists())
    corrections._private_path(private/'labels-2.json')  # Validate before database creation.
    private.mkdir(parents=True,mode=0o700)
    corrections._private_path(private/'labels-2.json')
    network_attempts=[]
    def forbidden(*args,**kwargs):
        network_attempts.append(True)
        raise ValueError('inference is forbidden in the controlled correction rehearsal')
    # Gateways deliberately retain missing-vector jobs; no worker/provider is run.
    with ExitStack() as stack:
        stack.enter_context(patch.object(store,'try_embed_texts',return_value=None))
        stack.enter_context(patch.object(embedding_reuse,'model_digest',return_value=None))
        for module,name in ((embed,'_client'),(embed,'embed_texts'),(llm,'run_structured'),(neural_rerank,'order')):
            stack.enter_context(patch.object(module,name,forbidden))
        owned=stack.enter_context(isolated_database(cfg))
        expected={};negative_ids=set();family_count=0
        with db.connect(owned,role='writer') as conn:
            for name,options in (('Assistant',dict(role='assistant',confirmed=False)),
                                 ('Unreviewed',dict(confirmed=False)),('Incomplete',dict(complete=False))):
                negative_ids.add(_save(conn,owned,f'Public Negative {name}','port','9990',
                    '2026-02-01T00:00:00Z',**options))
        for index in range(MAX_FAMILIES):
            with db.connect(owned,role='writer') as conn:expected.update(_family(conn,owned,index))
            family_count+=1
            if family_count<2:continue
            with db.connect(owned,role='reader') as conn:originals=_inventory(conn)
            labels=private/f'labels-{family_count}.json'
            exported=corrections.export_confirmed_corrections(owned,domain=DOMAIN,project=PROJECT,limit=32,output_path=labels)
            payload=corrections._validate_export(json.loads(corrections._private_path(labels,existing=True).read_bytes()))
            cases=payload['cases'];_require(exported['cases']==len(expected) and not exported['limited'])
            _require(exported['withheld_families']==2)  # Assistant disposition is review, so it is not a root.
            _require({c['document_id'] for c in cases}==set(expected) and not negative_ids.intersection(c['document_id'] for c in cases))
            _require(all((c['entity'],c['attribute'],c['value'])==expected[c['document_id']] and len(c['history'])==2 for c in cases))
            identities={c['identity_family'] for c in cases};_require(len(identities)==family_count)
            _require(all(len([c for c in cases if c['identity_family']==identity])==2 and
                len({c['split_family'] for c in cases if c['identity_family']==identity})==1 for identity in identities))
            with db.connect(owned,role='reader') as conn:_require(_inventory(conn)==originals)
            if {c['split'] for c in cases}=={'dev','test'}:break
        _require(family_count>=2 and {c['split'] for c in cases}=={'dev','test'})
        output=private/'evaluation.json'
        evaluated=corrections.evaluate_export(owned,export_path=labels,output_path=output)
        selection=_candidate_summary(private/'evaluation.json.candidate.json',evaluated['optimization'])
        _require(evaluated['cases']==len(expected) and evaluated['supported']==len(expected))
        _require(evaluated['wrong_scope']==evaluated['stale']==evaluated['failed_cases']==0)
        _require(evaluated['provider_calls']==evaluated['application_writes']==0 and not network_attempts)
        report=json.loads(corrections._private_path(output,existing=True).read_bytes())
        _require(report['summary']==evaluated and report['artifact_sha256']==corrections._hash(
            {k:v for k,v in report.items() if k!='artifact_sha256'}))
        with db.connect(owned,role='reader') as conn:
            _require(_inventory(conn)==originals)
            audit_rows=conn.execute('SELECT count(*) AS n FROM audit_log').fetchone()['n']
            _require(audit_rows>0)
        result=dict(public_controlled_fixtures=True,private_artifact_contract=True,
            eligible_corrections=len(expected),identity_families=family_count,negative_fixtures=3,
            negative_labels=0,exported_cases=exported['cases'],withheld_families=exported['withheld_families'],
            entity={k:v for k,v in evaluated.items() if k!='optimization'},selection=selection,
            original_rows_preserved=True,audit_rows_preserved=audit_rows,inference_attempts=0,
            embedding_vectors_generated=0)
    result['owned_cleanup_verified']=True
    return result
