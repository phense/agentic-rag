"""Department teams share knowledge/logs; session IDs never grant access."""
import json
from dataclasses import replace
import pytest
import psycopg
from agentic_rag import db
from agentic_rag.service.context import request_scope

from starlette.testclient import TestClient

from agentic_rag.service.auth import hash_key,Policy
from .test_api import app_fixture,headers,KEYS
from .test_checkpoint_api import packet
from .test_worker_fencing import owned,window

TEAM_KEY='itcolleague.synthetic-team-colleague-key'


def team_app(tmp_path,cfg):
    app,policy=app_fixture(tmp_path,cfg)
    text=policy.read_text().replace('[users.alice]','[users.alice]\nsession_teams=["it"]')
    text=text.replace('[users.bob]','[users.bob]\nsession_teams=["accounting"]')
    text+='''\n[users.colleague]
session_teams=["it"]
read_domains=["alpha"]
write_domains=["alpha"]
read_projects=["/projects/a"]
write_projects=["/projects/a"]
[machines.other_it]
user="colleague"
keys={itcolleague="'''+hash_key(TEAM_KEY)+'''"}
read_domains=["alpha"]
write_domains=["alpha"]
read_projects=["/projects/a"]
write_projects=["/projects/a"]
'''
    policy.write_text(text)
    return app,policy


def test_it_team_reads_each_others_sessions_without_sharing_mutation_authority(owned,tmp_path):
    cfg,_=owned;app,policy=team_app(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        saved=client.post('/v1/windows',headers=headers(KEYS[0]),json=window())
        assert saved.status_code==202,saved.text
        receipt=saved.json()['receipt']
        knowledge=client.post('/v1/tools/memory_save',headers=headers(KEYS[0]),json={
            'domain':'alpha','project':'/projects/a','title':'Shared IT team procedure','body':'Synthetic shared IT procedure.'})
        assert knowledge.status_code==200,knowledge.text
        assert client.post('/v1/tools/memory_search',headers=headers(TEAM_KEY),json={
            'query':'Shared IT team procedure','strategy':'lexical'}).json()['results']
        checkpoint=packet();checkpoint['session_id']=window()['session_id']
        assert client.post('/v1/checkpoints',headers=headers(KEYS[0]),json=checkpoint).status_code==200
        sessions=client.get('/v1/sessions',headers=headers(TEAM_KEY))
        assert sessions.status_code==200,sessions.text
        rows=sessions.json()['sessions'];assert len(rows)==1
        session=rows[0]['session_id']
        log=client.get('/v1/sessions/'+session+'/windows',headers=headers(TEAM_KEY))
        assert log.status_code==200,log.text
        assert len(log.json()['windows'])==1
        assert log.json()['windows'][0]['window']['text']==window()['window']['text']
        assert '_principal' not in log.text and 'sha256$' not in log.text and '_original_principal' not in log.text
        shared=client.get('/v1/sessions/'+session+'/checkpoint',headers=headers(TEAM_KEY))
        assert shared.status_code==200 and shared.json()['checkpoint']['handoff']==checkpoint['handoff']
        assert client.get('/v1/sessions/'+session+'/windows',headers=headers(KEYS[2])).status_code==404
        assert client.get('/v1/sessions/'+session+'/checkpoint',headers=headers(KEYS[2])).status_code==404
        assert client.get('/v1/sessions',headers=headers(KEYS[2])).json()['sessions']==[]
        # Shared observation does not let a colleague cancel/reauthorize another
        # user's accepted job or append to their namespaced stream.
        assert client.post('/v1/jobs/'+receipt+'/cancel',headers=headers(TEAM_KEY)).status_code==404
        assert client.post('/v1/jobs/'+receipt+'/retry',headers=headers(TEAM_KEY)).status_code==404
        own=client.post('/v1/windows',headers=headers(TEAM_KEY),json=window())
        assert own.status_code==202 and own.json()['receipt']!=receipt
        assert len(client.get('/v1/sessions',headers=headers(KEYS[0])).json()['sessions'])==2
        first_page=client.get('/v1/sessions?limit=1',headers=headers(TEAM_KEY)).json()
        second_page=client.get('/v1/sessions',params={'limit':1,'before':first_page['next']},headers=headers(TEAM_KEY)).json()
        assert len(second_page['sessions'])==1 and first_page['sessions'][0]['session_id']!=second_page['sessions'][0]['session_id']
        assert client.get('/v1/sessions?limit=101',headers=headers(TEAM_KEY)).status_code==400
        assert client.get('/v1/sessions/'+session+'/windows?limit=5',headers=headers(TEAM_KEY)).status_code==400
        # A read-only IT profile can observe team state without acquiring writes.
        assert client.get('/v1/sessions/'+session+'/windows',headers=headers(KEYS[3])).status_code==200
        # Leavers cannot see the team; retained IT history remains available to
        # current members, independent of the original author's current account.
        policy.write_text(policy.read_text().replace('session_teams=["it"]','session_teams=[]',1))
        assert len(client.get('/v1/sessions',headers=headers(TEAM_KEY)).json()['sessions'])==2
        colleague_session=next(row['session_id'] for row in client.get('/v1/sessions',headers=headers(TEAM_KEY)).json()['sessions'] if row['session_id']!=session)
        assert client.get('/v1/sessions/'+colleague_session+'/windows',headers=headers(KEYS[0])).status_code==404


def test_machine_can_narrow_but_not_invent_team_membership(owned,tmp_path):
    cfg,_=owned;_,policy=team_app(tmp_path,cfg)
    text=policy.read_text().replace('[machines.vm1]','[machines.vm1]\nsession_teams=["accounting"]')
    policy.write_text(text)
    assert Policy.load(policy).authenticate_key(KEYS[0]).session_teams==frozenset()


def test_team_visibility_never_grants_sql_old_row_write_or_foreign_publication(owned,tmp_path):
    cfg,_=owned;app,policy=team_app(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        assert client.post('/v1/windows',headers=headers(KEYS[0]),json=window()).status_code==202
        checkpoint=packet();checkpoint['session_id']=window()['session_id']
        assert client.post('/v1/checkpoints',headers=headers(KEYS[0]),json=checkpoint).status_code==200
    colleague=Policy.load(policy).authenticate_key(TEAM_KEY)
    cfg=replace(cfg,service_auth_file=policy)
    with request_scope(colleague,cfg),db.connect(cfg,role='writer') as conn:
        for table in ('service_windows','service_streams','continuation_checkpoints'):
            assert conn.execute('SELECT count(*) n FROM '+table).fetchone()['n']==1
        assert conn.execute("UPDATE service_windows SET owner_namespace=%s RETURNING id",(colleague.namespace,)).fetchall()==[]
        assert conn.execute("UPDATE service_streams SET owner_namespace=%s RETURNING session_id",(colleague.namespace,)).fetchall()==[]
        assert conn.execute("UPDATE continuation_checkpoints SET handoff='tampered' RETURNING id").fetchall()==[]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute('''INSERT INTO service_session_access(session_id,owner_namespace,project,teams,actor)
                VALUES (%s,%s,%s,%s,%s)''',(colleague.session_id('spoof'),colleague.namespace,'/projects/a',json.dumps(['accounting']),colleague.actor))
        conn.rollback()
