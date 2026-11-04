"""Hand-checked post-freeze label and incomplete-run accounting."""
import importlib.util
import hashlib
import json
from types import SimpleNamespace
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[2]


def api(monkeypatch):
    path=ROOT/'scripts/summarize_embedding_benchmark.py'
    assert path.is_file(),'Comparison export is not implemented'
    monkeypatch.syspath_prepend(str(path.parent))
    spec=importlib.util.spec_from_file_location('embedding_report',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    # The bootstrap mathematics has separate literal-oracle tests. Here the
    # contract is whether a comparison is admitted, with which artifact IDs.
    monkeypatch.setattr(module,'paired_comparison',lambda *a,**k:{'fixture_only':True})
    return module


def test_dedup_erratum_is_reported_both_as_frozen_and_excluded(monkeypatch):
    m=api(monkeypatch)
    pairs=[{'id':'identical','left':'one','right':'one','same':True},
           {'id':'paraphrase-32','left':'room schedule','right':'certificate expiration','same':True},
           {'id':'negative','left':'deutsch','right':'different English','same':False}]
    observed=[{'id':'identical','predicted_same':True},
              {'id':'paraphrase-32','predicted_same':False},
              {'id':'negative','predicted_same':True}]
    r=m.duplicate_summary(pairs,observed)
    assert r['as_frozen']=={'n':3,'completed':3,'missing':0,'positive':2,'negative':1,'false_positive':1,'false_negative':1}
    assert r['erratum_excluded']=={'n':2,'completed':2,'missing':0,'positive':1,'negative':1,'false_positive':1,'false_negative':0}
    assert r['pair_types']['identical']['false_negative']==0
    assert r['pair_types']['cross_language_negative']['false_positive']==1
    r=m.duplicate_summary(pairs,observed[:1])
    assert r['as_frozen']['missing']==2 and r['as_frozen']['false_negative']==0
    with pytest.raises(ValueError):m.duplicate_summary(pairs,observed+[observed[0]])


def test_actual_hybrid_empty_results_are_zero_recall_not_missing(monkeypatch):
    m=api(monkeypatch)
    q={'id':'q','language':'de','family':'multi','split':'independent-heldout','cross_language':False,
       'relevance':{'a':2,'b':2},'required_groups':[['a'],['b']]}
    unsupported={**q,'id':'u','relevance':{},'required_groups':[]}
    corpus={'queries':[q,unsupported]}
    r=m.hybrid_quality(corpus,[{'id':'q','hits':[]},{'id':'u','hits':[]}])
    assert r['denominators']=={'planned':2,'supported':1,'unsupported':1,'completed':2,'failed_or_missing':0}
    assert r['observations'][0]['metrics']['recall_at_10']==0
    assert r['observations'][0]['metrics']['mrr']==0
    assert r['observations'][1]['metrics'] is None
    r=m.hybrid_quality(corpus,[{'id':'q','hits':[{'id':'b'},{'id':'z'},{'id':'a'}]}])
    assert r['observations'][0]['metrics']['all_required_at_1']==0
    assert r['observations'][0]['metrics']['all_required_at_3']==1
    assert r['denominators']['failed_or_missing']==1


def test_failed_worker_keeps_available_rankings_but_never_becomes_completed(tmp_path,monkeypatch):
    m=api(monkeypatch)
    fixtures=tmp_path/'fixtures';fixtures.mkdir()
    q={'id':'q','language':'de','family':'literal','split':'heldout','cross_language':False,
       'relevance':{'d':2},'required_groups':[['d']]}
    corpus={'documents':[{'id':'d'}],'queries':[q],'duplicate_pairs':[]}
    (fixtures/'corpus.json').write_text(json.dumps(corpus))
    (fixtures/'protocol.json').write_text(json.dumps({'models':{n:{'dimensions':2} for n in ('bge','nano','small')}}))
    (fixtures/'errata.json').write_text('{}')
    primary=tmp_path/'primary';primary.mkdir();small=tmp_path/'small';small.mkdir()
    for folder in (primary,small):
        (folder/'terminal.json').write_text(json.dumps({'finished':'now','inputs_unchanged':True}))
    for model in ('bge','nano','small'):
        root=small if model=='small' else primary
        target=root/(model+'-r0');target.mkdir()
        (target/'vectors.json').write_text(json.dumps({'documents':{'d':[1.,0.]},'queries':{'q':[1.,0.]}}))
        (root/(model+'-r0-exit.json')).write_text(json.dumps({'exit_code':-15 if model=='small' else 0,'supervisor_stop':'deadline' if model=='small' else None}))
        if model!='small':(target/'worker-result.json').write_text(json.dumps({'status':'complete'}))
    m.run(SimpleNamespace(output=tmp_path/'export',fixtures=fixtures,primary_root=primary,small_root=small,canonical_root=None,hybrid=None))
    report=json.loads((tmp_path/'export/report.json').read_text())
    partial=report['primary']['small']['runs'][0]
    assert partial['status']=='failed'
    assert partial['quality']['denominators']['completed']==1
    assert partial['quality']['observations'][0]['metrics']['mrr']==1
    assert report['primary']['small']['runs'][1]['status']=='unattempted'
    assert partial['dedup']['as_frozen']['completed']==0


def test_public_raw_export_reads_only_allowlisted_files_never_daemon_keys(tmp_path,monkeypatch):
    m=api(monkeypatch);root=tmp_path/'private';root.mkdir()
    (root/'terminal.json').write_text('{"finished":"now"}')
    worker=root/'bge-r0';worker.mkdir()
    (worker/'vectors.json').write_text('{"documents":{}}')
    secret=worker/'.ollama';secret.mkdir()
    (secret/'id_ed25519').write_text('SYNTHETIC-PRIVATE-CANARY')
    (root/'unrelated-private.txt').write_text('SYNTHETIC-PRIVATE-CANARY')
    dest=tmp_path/'public'
    copied=m.publish_raw({'primary':root},dest)
    assert {r['source'] for r in copied}=={'primary/terminal.json','primary/bge-r0/vectors.json'}
    import gzip
    assert gzip.decompress((dest/'primary/bge-r0/vectors.json.gz').read_bytes())==b'{"documents":{}}'
    assert not any('.ollama' in str(p) or 'private.txt' in str(p) for p in dest.rglob('*'))
    assert (secret/'id_ed25519').read_text()=='SYNTHETIC-PRIVATE-CANARY'


def canonical_fixture(tmp_path):
    fixtures=tmp_path/'fixtures';fixtures.mkdir()
    q={'id':'q','language':'de','family':'literal','split':'heldout','cross_language':False,
       'relevance':{'d':2},'required_groups':[['d']]}
    corpus={'documents':[{'id':'d'}],'queries':[q],'duplicate_pairs':[]}
    canonical={**corpus,'model_identities':{}}
    for name,value in [('corpus.json',corpus),('protocol.json',{'models':{n:{'dimensions':256} for n in ('bge','nano','small')}}),
                       ('errata.json',{}),('canonical-inputs-v2.json',canonical)]:
        (fixtures/name).write_text(json.dumps(value))
    digest=hashlib.sha256((fixtures/'canonical-inputs-v2.json').read_bytes()).hexdigest()
    primary=tmp_path/'primary';primary.mkdir();root=tmp_path/'canonical';root.mkdir()
    for p in (primary,root):(p/'terminal.json').write_text(json.dumps({'finished':'now','inputs_unchanged':True}))
    hashes={}
    for model in ('bge','nano','small'):
        target=root/(model+'-r0');target.mkdir()
        (target/'vectors.json').write_text(json.dumps({'documents':{'d':[1.]+[0.]*255},'queries':{'q':[1.]+[0.]*255}}))
        (target/'result.json').write_text(json.dumps({'status':'complete','input_sha256':digest}))
        hashes[model]={name:hashlib.sha256((target/name).read_bytes()).hexdigest() for name in ('result.json','vectors.json')}
    args=SimpleNamespace(output=tmp_path/'export',fixtures=fixtures,primary_root=primary,small_root=primary,canonical_root=root,hybrid=None)
    return args,digest,hashes


def test_unproven_canonical_vectors_are_incomplete_and_never_scored(tmp_path,monkeypatch):
    m=api(monkeypatch);args,digest,hashes=canonical_fixture(tmp_path)
    (args.canonical_root/'nano-r0/result.json').unlink()
    m.run(args);report=json.loads((args.output/'report.json').read_text())
    assert report['canonical']['nano']['status']=='incomplete-no-result'
    assert report['canonical']['nano']['slices']=={}
    assert not any(key.endswith(':nano') for key in report['paired'])
    assert str(args.fixtures/'corpus.json') in report['inputs']
    assert str(args.fixtures/'protocol.json') in report['inputs']


@pytest.mark.parametrize('bad', ['input','vectors','script'])
def test_hybrid_replay_is_bound_to_inputs_vectors_and_rehearsal_code(tmp_path,monkeypatch,bad):
    m=api(monkeypatch);args,digest,hashes=canonical_fixture(tmp_path)
    hybrid={'status':'complete','input_sha256':digest,'models':['bge','nano'],'unrehearsed_models':['small'],
            'replay_inputs':{n:hashes[n] for n in ('bge','nano')},
            'rehearsal_script_sha256':hashlib.sha256((ROOT/'scripts/rehearse_embedding_substitution.py').read_bytes()).hexdigest(),
            'hybrid':{'bge':[{'id':'q','hits':[{'id':'d','score':1}]}],'nano':[]}}
    if bad=='input':hybrid['input_sha256']='0'*64
    if bad=='vectors':hybrid['replay_inputs']['nano']['vectors.json']='0'*64
    if bad=='script':hybrid['rehearsal_script_sha256']='0'*64
    args.hybrid=tmp_path/'hybrid.json';args.hybrid.write_text(json.dumps(hybrid))
    with pytest.raises(ValueError,match='rehearsal|replay'):m.run(args)


def test_absent_hybrid_models_remain_visible_as_unrehearsed(tmp_path,monkeypatch):
    m=api(monkeypatch);args,digest,hashes=canonical_fixture(tmp_path)
    hybrid={'status':'complete','input_sha256':digest,'models':['bge','nano'],'unrehearsed_models':['small'],
            'replay_inputs':{n:hashes[n] for n in ('bge','nano')},
            'rehearsal_script_sha256':hashlib.sha256((ROOT/'scripts/rehearse_embedding_substitution.py').read_bytes()).hexdigest(),
            'hybrid':{'bge':[{'id':'q','hits':[{'id':'d','score':1}]}],'nano':[]}}
    args.hybrid=tmp_path/'hybrid.json';args.hybrid.write_text(json.dumps(hybrid))
    m.run(args);report=json.loads((args.output/'report.json').read_text())
    assert report['hybrid']['small']=={'status':'unrehearsed'}
    assert report['hybrid']['nano']['original']['denominators']['failed_or_missing']==1


def test_allowlisted_symlink_is_rejected_before_any_key_is_read(tmp_path,monkeypatch):
    m=api(monkeypatch);root=tmp_path/'private';root.mkdir();worker=root/'bge-r0';worker.mkdir()
    secret=root/'.ollama';secret.mkdir();(secret/'id_ed25519').write_text('SYNTHETIC-PRIVATE-CANARY')
    (worker/'vectors.json').symlink_to(secret/'id_ed25519')
    with pytest.raises(ValueError,match='symlink'):m.publish_raw({'primary':root},tmp_path/'public')
