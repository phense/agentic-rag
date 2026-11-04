"""Native public fixture plumbing, with only the slow model/daemon replaced."""
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[2]


def api(monkeypatch):
    p=ROOT/'scripts/benchmark_embedding_chunks.py'
    assert p.is_file(), 'Canonical-chunk inference worker is not implemented'
    monkeypatch.syspath_prepend(str(p.parent))
    spec=importlib.util.spec_from_file_location('canonical_chunk_worker',p)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('fail',[False,True])
def test_exact_input_bytes_are_preserved_and_failure_keeps_denominators(tmp_path,monkeypatch,fail):
    m=api(monkeypatch)
    model=tmp_path/'model';blob=model/'blobs'
    blob.mkdir(parents=True)
    data=b'public synthetic model blob';digest=hashlib.sha256(data).hexdigest()
    (blob/('sha256-'+digest)).write_bytes(data)
    model_manifest=json.dumps({'config':{'digest':'sha256:'+digest},'layers':[]}).encode()
    p=model/'manifests/registry.ollama.ai/library/bge-m3-q8/latest';p.parent.mkdir(parents=True);p.write_bytes(model_manifest)
    model_id=hashlib.sha256(model_manifest).hexdigest()
    inputs={'model_identities':{'bge':{'dimensions':2,'digest':model_id,'model':'bge-m3-q8:latest'}},
        'batch_size':4,'documents':[{'id':'d','purpose':'document','text':'# Title\n\nExact body.'}],
        'queries':[{'id':'q','text':'What body?'}],
        'auxiliary':[{'id':'ad','purpose':'document','text':'Fixed probe'},
                     {'id':'aq','purpose':'query','text':'Fixed probe'}]}
    inp=tmp_path/'inputs.json';inp.write_text(json.dumps(inputs));out=tmp_path/'output'
    class Daemon:
        def poll(self):return None
        def terminate(self):pass
        def wait(self,timeout):return 0
    monkeypatch.setattr(m.subprocess,'Popen',lambda *a,**kw:Daemon())
    monkeypatch.setattr(m,'require_free_port',lambda:None)
    monkeypatch.setattr(m,'assert_owned_listener',lambda child:None)
    seen=[]
    def http(origin,path,payload=None):
        assert origin=='http://127.0.0.1:11583'
        if path=='/api/tags':return {'models':[{'digest':model_id}]}
        if payload['input']==[]:return {}
        assert payload['truncate'] is False
        seen.extend(payload['input'])
        if fail and payload['input']==['What body?']:raise TimeoutError('synthetic deadline')
        return {'embeddings':[[1.,0.] for _ in payload['input']],'prompt_eval_count':3}
    monkeypatch.setattr(m,'http',http)
    args=SimpleNamespace(output=str(out),inputs=str(inp),model='bge',model_dir=str(model))
    if fail:
        with pytest.raises(TimeoutError):m.worker(args)
    else:m.worker(args)
    result=json.loads((out/'result.json').read_text())
    assert result['planned']=={'documents':1,'queries':1,'auxiliary':2}
    assert result['completed']==({'documents':1,'queries':0,'auxiliary':0} if fail else {'documents':1,'queries':1,'auxiliary':2})
    assert result['status']==('failed' if fail else 'complete')
    assert seen==(['# Title\n\nExact body.','What body?'] if fail else ['# Title\n\nExact body.','What body?','Fixed probe','Fixed probe'])
    if not fail:
        assert [r['purpose'] for r in result['observations']]==['document','query','document','query']
        vectors=json.loads((out/'vectors.json').read_text())
        assert vectors['documents']=={'d':[1.,0.]}
