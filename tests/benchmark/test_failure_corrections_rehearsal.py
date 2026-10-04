"""Pure boundaries for the controlled private correction rehearsal helper."""
import json

import pytest

from agentic_rag.benchmark import corrections
from agentic_rag.config import Config
from scripts import verify_failure_corrections as rehearsal


def _candidate(tmp_path):
    metrics=corrections._summary([])
    candidate=dict(kind='private-correction-candidate',version=1,synthetic=False,profile='entity',
        profiles=['fts','entity'],context_chars=12000,dev={'fts':metrics,'entity':metrics},
        dev_evidence_sha256='a'*64,source_revision='b'*40,source_sha256='c'*64)
    candidate['artifact_sha256']=corrections._hash(candidate)
    path=tmp_path/'candidate.json';corrections._write_private(path,candidate)
    aggregate=dict(status='sealed',chosen='entity',profiles=2,dev=candidate['dev'],heldout=metrics,
        dev_families=2,test_families=2,heldout_evaluations=1,candidate_sha256=candidate['artifact_sha256'])
    return path,candidate,aggregate


def test_candidate_readback_exports_only_selection_aggregates(tmp_path):
    path,candidate,aggregate=_candidate(tmp_path)
    result=rehearsal._candidate_summary(path,aggregate)
    assert set(result)=={'chosen','profiles','dev','heldout','dev_families','test_families',
        'heldout_evaluations','candidate_readback_verified'}
    assert result['candidate_readback_verified'] and result['chosen']=='entity'
    serialized=json.dumps(result)
    for value in (candidate['source_revision'],candidate['source_sha256'],candidate['dev_evidence_sha256'],candidate['artifact_sha256']):
        assert value not in serialized


def test_candidate_readback_rejects_resealed_drift(tmp_path):
    path,candidate,aggregate=_candidate(tmp_path)
    candidate['profile']='fts'
    candidate['artifact_sha256']=corrections._hash({k:v for k,v in candidate.items() if k!='artifact_sha256'})
    path.write_bytes(corrections._encoded(candidate)+b'\n')
    with pytest.raises(ValueError,match='^controlled private candidate readback failed$'):
        rehearsal._candidate_summary(path,aggregate)


def test_rehearsal_rejects_public_path_before_owned_database(tmp_path,monkeypatch):
    monkeypatch.setattr(rehearsal,'isolated_database',lambda *a,**k:pytest.fail('database reached'))
    repository=tmp_path/'repository';repository.mkdir();(repository/'.git').mkdir()
    with pytest.raises(ValueError,match='Git'):
        rehearsal.rehearse(Config(),private_dir=repository/'artifact')
    assert not (repository/'artifact').exists()
