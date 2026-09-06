from agentic_rag import context_gate as gate


def test_selective_bilingual_project_and_history_questions():
    cases={
        'How do we deploy this project?':'project',
        'Wie starten wir dieses Projekt?':'project',
        'What did we decide about the database earlier?':'history',
        'Was hatten wir zuletzt zum Backup entschieden?':'history',
        'What is the weather in Berlin?':None,
        'Thanks!':None,
        'Thanks for this project':None,
        'Write a poem about memory':None,
        'Remember to buy milk':None,
    }
    for prompt,expected in cases.items():
        assert gate.detect(prompt,'/synthetic/widget')==expected
    assert gate.detect('How do we deploy widget?','/synthetic/widget')=='project'
    assert gate.detect('How do we deploy widget?',None) is None
    assert gate.query('How do we deploy this project?')=='deploy'
    assert gate.query('Wie starten wir dieses Projekt?')=='starten'
    assert gate.query('x | DROP; SELECT!!')=='drop OR select'


def test_real_turn_keys_never_reuse_prompt_identity():
    payload={'session_id':'s1','turn_id':'t1','prompt':'same'}
    key=gate.receipt_key(payload,project='/repo',revision='r1',config='c1',text='emitted')
    assert key
    for field,value in [('turn_id','t2'),('session_id','s2')]:
        assert gate.receipt_key({**payload,field:value},project='/repo',revision='r1',config='c1',text='emitted')!=key
    assert gate.receipt_key(payload,project='/repo',revision='r2',config='c1',text='emitted')!=key
    assert gate.receipt_key(payload,project='/other',revision='r1',config='c1',text='emitted')!=key
    assert gate.receipt_key(payload,project='/repo',revision='r1',config='c2',text='emitted')!=key
    assert gate.receipt_key({'session_id':'s1','prompt':'same'},project='/repo',revision='r1',config='c1',text='emitted') is None


def test_receipts_record_success_only_and_storage_is_bounded(tmp_path,monkeypatch):
    monkeypatch.setattr(gate,'RECEIPT_DIR',tmp_path/'receipts')
    assert not gate.delivered('a'*64)
    gate.record('a'*64)
    assert gate.delivered('a'*64)
    assert not gate.delivered(None)
    for i in range(gate.MAX_RECEIPTS+3):gate.record(f'{i:064x}')
    assert len(list(gate.RECEIPT_DIR.glob('*.receipt')))<=gate.MAX_RECEIPTS
    assert all(p.stat().st_size==0 for p in gate.RECEIPT_DIR.glob('*'))


def test_successful_reemit_renews_expired_receipt(tmp_path,monkeypatch):
    import os,time
    monkeypatch.setattr(gate,'RECEIPT_DIR',tmp_path/'receipts')
    key='a'*64
    gate.record(key)
    path=gate.RECEIPT_DIR/(key+'.receipt')
    old=time.time()-gate.RECEIPT_TTL-1
    os.utime(path,(old,old))
    assert not gate.delivered(key)
    gate.record(key)
    assert gate.delivered(key)
