"""Regression for pinned Small's real private-only modality layout."""
from contextlib import nullcontext
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace,ModuleType

import pytest

ROOT=Path(__file__).resolve().parents[2]

@pytest.mark.parametrize('modality',['text','omni'])
@pytest.mark.parametrize('kind',['primary','canonical'])
def test_private_base_modality_contract(tmp_path,monkeypatch,modality,kind):
 monkeypatch.syspath_prepend(str(ROOT/'scripts'))
 script='benchmark_embeddings.py' if kind=='primary' else 'benchmark_embedding_chunks.py'
 spec=importlib.util.spec_from_file_location('actual_worker',ROOT/'scripts'/script)
 api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)
 monkeypatch.setattr(api,'deny_network',lambda:None)
 modeldir=tmp_path/'small';modeldir.mkdir()
 (tmp_path/'small-manifest.json').write_text(json.dumps({'repo':'synthetic-small','revision':'pinned','files':{}}))
 corpus={'documents':[{'id':'d','text':'Public fixture.'}],'queries':[{'id':'q','text':'What fixture?','language':'en','family':'literal','split':'heldout','cross_language':False,'relevance':{'d':2},'required_groups':[['d']]}],'duplicate_pairs':[]}
 cp=tmp_path/'corpus.json';cp.write_text(json.dumps(corpus))
 proto={'corpus_sha256':sha256(cp.read_bytes()).hexdigest(),'models':{'small':{'repo':'synthetic-small','revision':'pinned','dimensions':2}},'ranking':{'dedup_threshold':.95,'smaller_dimensions':[1]}}
 pp=tmp_path/'protocol.json';pp.write_text(json.dumps(proto))
 class Array:
  def __init__(self,n):self.n=n
  def float(self):return self
  def tolist(self):return [[1.,0.] for _ in range(self.n)]
 class Model:
  _modality=modality
  def eval(self):return self
  def encode(self,texts,**kwargs):return Array(len(texts))
  def tokenizer(self,texts,**kwargs):return {'input_ids':[[1,2] for _ in texts]}
  def parameters(self):return iter([SimpleNamespace(dtype='float32',numel=lambda:2)])
  def named_modules(self):return []
 class AutoModel:
  @staticmethod
  def from_pretrained(path,**kwargs):
   assert kwargs['modality']=='text' and kwargs['local_files_only'] is True
   return Model()
 torch=ModuleType('torch');torch.set_num_threads=lambda n:None;torch.set_num_interop_threads=lambda n:None
 torch.float32='float32';torch.inference_mode=nullcontext
 transformers=ModuleType('transformers');transformers.AutoModel=AutoModel
 monkeypatch.setitem(sys.modules,'torch',torch);monkeypatch.setitem(sys.modules,'transformers',transformers)
 if kind=='primary':monkeypatch.setattr(api.importlib.metadata,'version',lambda n:'synthetic')
 args=SimpleNamespace(worker='small',model_dir=str(modeldir),output=str(tmp_path/'out'),corpus=str(cp),protocol=str(pp))
 if kind=='canonical':
  inputs={'model_identities':proto['models'],'max_tokens':8192,'batch_size':4,
          'documents':corpus['documents'],'queries':corpus['queries'],'auxiliary':[]}
  ip=tmp_path/'inputs.json';ip.write_text(json.dumps(inputs));args.model='small';args.inputs=str(ip)
 try:api.worker(args)
 except Exception as exc:
  if modality=='text':pytest.fail('Valid private-only text base was rejected: '+type(exc).__name__)
  assert isinstance(exc,ValueError) and str(exc)=='unexpected modality'
 result=json.loads((tmp_path/'out'/('worker-result.json' if kind=='primary' else 'result.json')).read_text())
 assert result['status']==('complete' if modality=='text' else 'failed')
 assert result['completed']['queries']==(1 if modality=='text' else 0)
