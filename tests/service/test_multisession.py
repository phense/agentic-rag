"""Many sessions share a host without sharing department/user authority."""
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
import time

from starlette.testclient import TestClient

from agentic_rag import db, domains, store
from .test_api import app_fixture, headers, KEYS
from .test_worker_fencing import owned, window
from .test_checkpoint_api import packet


def test_24_sessions_on_one_host_keep_user_knowledge_and_checkpoints_separate(owned,tmp_path):
    cfg,_=owned
    with db.connect(cfg) as conn:
        domains.add_domain(conn,'beta')
        it=store.save_document(conn,cfg,title='Private IT operating procedure',body='Synthetic IT-only credential location: env/it-example.env',
                               domain='alpha',dtype='memory',project='/projects/a')
        store.save_document(conn,cfg,title='Private accounting procedure',body='Synthetic finance-only invoice approval procedure',
                                    domain='beta',dtype='memory',project='/projects/b')
    app,policy=app_fixture(tmp_path,cfg)
    policy.write_text(policy.read_text().replace('First synthetic VM','Shared synthetic host').replace('[machines.vm3]','[machines.vm3]\nlabel="Shared synthetic host"'))
    cases=[(key,department,project,index) for key,department,project in [(KEYS[0],'it','/projects/a'),(KEYS[2],'finance','/projects/b')] for index in range(12)]
    responses=Counter();started=time.monotonic()
    with TestClient(app,base_url='https://testserver') as client:
        def accepted(path,key,data):
            # Honor backpressure instead of hammering admission at a fixed50ms
            # interval. Actual durable uploaders likewise back off on429.
            deadline=time.monotonic()+45;attempt=0
            stagger=int(data['session_id'].rsplit('-',1)[-1])*.01
            while True:
                response=client.post(path,headers=headers(key),json=data)
                responses[str(response.status_code)+':'+str(response.json().get('error','accepted'))]+=1
                if response.status_code!=429:return response
                assert time.monotonic()<deadline,f'bounded admission never recovered: {responses}'
                time.sleep(min(1.6,.05*2**min(attempt,5))+stagger)
                attempt+=1
        def submit(case):
            key,department,project,index=case
            source=window();source['session_id']='same-session-'+str(index);source['project']=project
            text=f'[user] Distinct {department} task {index}'
            source['window']['text']=text;source['window']['events'][0]['text']=text
            response=accepted('/v1/windows',key,source)
            assert response.status_code==202,response.text
            checkpoint=packet();checkpoint['session_id']=source['session_id'];checkpoint['project']=project
            checkpoint['snapshot']['cwd']=project;checkpoint['handoff']=f'Continue {department} task {index}.'
            saved=accepted('/v1/checkpoints',key,checkpoint)
            assert saved.status_code==200,saved.text
            return response.json()['receipt']
        with ThreadPoolExecutor(max_workers=24) as pool:
            receipts=list(pool.map(submit,cases))
        assert len(set(receipts))==24
        for case,receipt in zip(cases,receipts):
            key,department,project,index=case
            assert client.get('/v1/jobs/'+receipt,headers=headers(key)).status_code==200
            foreign=KEYS[2] if department=='it' else KEYS[0]
            assert client.get('/v1/jobs/'+receipt,headers=headers(foreign)).status_code==404
            checkpoint=client.get('/v1/checkpoints/same-session-'+str(index),headers=headers(key))
            assert checkpoint.status_code==200
            assert checkpoint.json()['checkpoint']['handoff']==f'Continue {department} task {index}.'
        # A finance question asking for IT credentials cannot override authority.
        denied=client.post('/v1/tools/memory_get',headers=headers(KEYS[2]),json={'id_or_slug':it.doc_id})
        assert denied.status_code==200 and denied.json().get('document') is None
        search=client.post('/v1/tools/memory_search',headers=headers(KEYS[2]),json={'query':'credential env IT operating procedure','strategy':'lexical'})
        assert search.status_code==200 and 'it-example.env' not in search.text
        for key,project,allowed,forbidden in [(KEYS[0],'/projects/a','Private IT operating procedure','Private accounting procedure'),(KEYS[2],'/projects/b','Private accounting procedure','Private IT operating procedure')]:
            context=client.post('/v1/tools/memory_context',headers=headers(key),json={'session_id':'same-session-0','project':project})
            assert context.status_code==200,context.text
            assert allowed in context.text,context.text
            assert forbidden not in context.text
            assert 'it-example.env' not in context.text
        with db.connect(cfg) as conn:
            rows=conn.execute('SELECT owner_namespace,session_id,payload FROM service_windows').fetchall()
            assert len(rows)==24 and len({r['session_id'] for r in rows})==24
            assert len({r['owner_namespace'] for r in rows})==2
            assert {r['payload']['window']['text'] for r in rows}=={f'[user] Distinct {department} task {index}' for _,department,_,index in cases}
            assert conn.execute("SELECT count(*) n FROM mining_queue WHERE kind='source_window'").fetchone()['n']==24
        print('MULTISESSION',{'sessions':24,'users':2,'logical_hosts':1,'accepted_windows':24,'accepted_checkpoints':24,
                              'seconds':round(time.monotonic()-started,3),'upload_responses':dict(responses),'model_calls':0})
