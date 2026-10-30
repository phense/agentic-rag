"""Forty real HTTP keep-alive connections must not create per-connection workers/state."""
import asyncio
from collections import Counter
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

from agentic_rag import db
from .test_scope import service_store
from .test_api import app_fixture,KEYS


def process_sample(pid):
    values={}
    for line in Path(f'/proc/{pid}/smaps_rollup').read_text().splitlines():
        if line.startswith(('Pss:','Rss:')):values[line.split(':')[0].lower()+'_kib']=int(line.split()[1])
    values['fds']=len(list(Path(f'/proc/{pid}/fd').iterdir()))
    values['threads']=len(list(Path(f'/proc/{pid}/task').iterdir()))
    return values


def test_forty_keepalive_connections_have_bounded_retained_resources(service_store,tmp_path):
    cfg,_=service_store
    _,policy=app_fixture(tmp_path,cfg)
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(128)
    port=listener.getsockname()[1]
    code='''import socket,sys
from pathlib import Path
import uvicorn
from agentic_rag.config import Config
from agentic_rag.service.api import create_app
cfg=Config(db_name=sys.argv[1],ollama_url='http://127.0.0.1:1',rerank_url='http://127.0.0.1:1')
app=create_app(cfg,Path(sys.argv[2]))
server=uvicorn.Server(uvicorn.Config(app,workers=1,loop='asyncio',http='h11',access_log=False,log_level='error',timeout_keep_alive=30,limit_concurrency=128,backlog=64))
server.run(sockets=[socket.socket(fileno=int(sys.argv[3]))])
'''
    child=subprocess.Popen([sys.executable,'-c',code,cfg.db_name,str(policy),str(listener.fileno())],
        pass_fds=(listener.fileno(),),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    listener.close()
    try:
        with db.connect(cfg) as conn:
            def footprint():
                return dict(conn.execute('''SELECT
                    (SELECT count(*) FROM service_streams) streams,
                    (SELECT count(*) FROM service_windows) windows,
                    (SELECT count(*) FROM mining_queue) jobs,
                    pg_database_size(current_database()) bytes''').fetchone())
            before=footprint();conn.commit()
        async def exercise():
            async def connect():return await asyncio.open_connection('127.0.0.1',port)
            async def request(connection,*,mcp=False):
                reader,writer=connection
                body=json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'memory_domains','arguments':{}}}).encode() if mcp else b''
                first='POST /mcp/ro/ HTTP/1.1' if mcp else 'GET /v1/capabilities HTTP/1.1'
                writer.write((first+'\r\nHost: 127.0.0.1\r\nAuthorization: Bearer '+KEYS[0]+'\r\nX-RAG-Protocol: 1\r\nAccept: application/json, text/event-stream\r\nContent-Type: application/json\r\nContent-Length: '+str(len(body))+'\r\nConnection: keep-alive\r\n\r\n').encode()+body)
                await writer.drain()
                header=await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'),10)
                size=next(int(line.split(b':',1)[1]) for line in header.split(b'\r\n') if line.lower().startswith(b'content-length:'))
                await asyncio.wait_for(reader.readexactly(size),10)
                return int(header.split(b' ')[1])
            warm=None
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                try:
                    warm=await connect()
                    if await request(warm)==200:break
                except (OSError,asyncio.TimeoutError,asyncio.IncompleteReadError):
                    if child.poll() is not None:raise AssertionError('synthetic service exited')
                    await asyncio.sleep(.05)
                finally:
                    if warm:warm[1].close();await warm[1].wait_closed();warm=None
            else:raise AssertionError('synthetic service did not start')
            baseline=process_sample(child.pid)
            connections=[];samples=[];codes=Counter();successful=set();started=time.monotonic()
            try:
                for _ in range(40):
                    connection=await connect();connections.append(connection)
                    assert await request(connection)==200
                idle=process_sample(child.pid)
                # Default4,000 authenticated REST/MCP requests; longer isolated
                # rehearsals can raise the finite wave count explicitly.
                # Capacity rejection is deliberate; callers retry instead of buffering
                # an unlimited number of extraction/inference requests in RAM.
                waves=int(os.environ.get('RAG_RESOURCE_WAVES','100'))
                assert 25<=waves<=10000
                for wave in range(waves):
                    order=list(range(40));shift=(wave*8)%40;order=order[shift:]+order[:shift]
                    results=await asyncio.gather(*(request(connections[i],mcp=bool(i%2)) for i in order))
                    successful.update(i for i,status in zip(order,results) if status==200)
                    codes.update(results)
                    samples.append(process_sample(child.pid))
                    await asyncio.sleep(.02)
                assert codes[200]>0 and set(codes)<={200,429}
                assert len(successful)==40
                assert idle['pss_kib']-baseline['pss_kib']<32768
                assert max(s['pss_kib'] for s in samples)-baseline['pss_kib']<65536
                assert samples[-1]['pss_kib']-samples[4]['pss_kib']<16384
                assert max(s['fds'] for s in samples)<=baseline['fds']+56
                assert max(s['threads'] for s in samples)<=baseline['threads']+10
            finally:
                for _,writer in connections:writer.close()
                await asyncio.gather(*(writer.wait_closed() for _,writer in connections),return_exceptions=True)
            await asyncio.sleep(.1)
            released=process_sample(child.pid)
            assert released['fds']<=baseline['fds']+4
            # Repeated connection turnover must also release sockets/state.
            for _ in range(100):
                connection=await connect()
                assert await request(connection)==200
                connection[1].close();await connection[1].wait_closed()
            await asyncio.sleep(.1)
            churned=process_sample(child.pid)
            assert churned['fds']<=baseline['fds']+4
            return {'connections':40,'requests':40*waves,'churn_connections':100,'successful_clients':len(successful),
                'elapsed_seconds':round(time.monotonic()-started,3),'status_counts':dict(codes),'baseline':baseline,'idle40':idle,
                'peak_pss_kib':max(s['pss_kib'] for s in samples),'first_plateau':samples[4],
                'last_plateau':samples[-1],'released':released,'after_churn':churned,'samples':samples}
        result=asyncio.run(exercise())
        with db.connect(cfg) as conn:
            after=dict(conn.execute('''SELECT (SELECT count(*) FROM service_streams) streams,
                (SELECT count(*) FROM service_windows) windows,(SELECT count(*) FROM mining_queue) jobs,
                pg_database_size(current_database()) bytes''').fetchone())
            # PostgreSQL may retain the final closed backend briefly. Refresh
            # the statistics snapshot while allowing a finite teardown grace;
            # the invariant remains exactly one measuring connection.
            deadline=time.monotonic()+2
            while True:
                conn.commit()
                backends=conn.execute('SELECT count(*) n FROM pg_stat_activity WHERE datname=current_database()').fetchone()['n']
                if backends==1 or time.monotonic()>=deadline:break
                time.sleep(.02)
        assert {k:after[k] for k in ('streams','windows','jobs')}=={k:before[k] for k in ('streams','windows','jobs')}
        assert after['bytes']-before['bytes']<=1048576
        assert backends==1  # only this measuring connection remains
        result.update(database_before=before,database_after=after,idle_database_backends=backends)
        report=Path(os.environ.get('RAG_RESOURCE_REPORT',str(tmp_path/'resources.json')))
        report.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,sort_keys=True))
    finally:
        child.terminate()
        try:child.wait(timeout=10)
        except subprocess.TimeoutExpired:child.kill();child.wait()


def test_client_spool_disk_plateaus_after_bounded_receipts_and_cache(tmp_path):
    from agentic_rag.service.spool import Spool,SpoolFull
    import pytest
    path=tmp_path/'private'/'spool.sqlite'
    with Spool(path,'synthetic-client',max_items=8,max_bytes=65536) as spool:
        for n in range(8):
            spool.enqueue('window','blocked-'+str(n),{'input_cursor':'','output_cursor':'c1','text':'retained'+str(n)})
        with pytest.raises(SpoolFull):spool.enqueue('window','overflow',{'input_cursor':'','output_cursor':'c1'})
        retained=[(row['id'],row['payload']) for row in spool.pending()]
        for n in range(400):
            spool.cache('session-'+str(n),'/project','bounded cached context '+str(n)+'x'*1000)
        assert [(row['id'],row['payload']) for row in spool.pending()]==retained
        assert spool.conn.execute('SELECT count(*) FROM contexts').fetchone()[0]==64
        for row in spool.pending():spool.ack(row['id'],{'receipt':'synthetic-ack'})
        def churn(start,end):
            before=spool.cursor('active')
            for n in range(start,end):
                after='cursor-'+str(n)
                item=spool.enqueue('window','active',{'input_cursor':before,'output_cursor':after,'text':'x'*1000})
                spool.ack(item,{'receipt':'bounded-'+str(n)})
                spool.cache('session-'+str(n),'/project','x'*1000)
                before=after
        churn(0,400)
        first_size=path.stat().st_size
        churn(400,1200)
        last_size=path.stat().st_size
        assert spool.pending()==[]
        assert spool.conn.execute('SELECT count(*) FROM receipts').fetchone()[0]==256
        assert spool.conn.execute('SELECT count(*) FROM contexts').fetchone()[0]==64
        assert last_size-first_size<=65536
        assert last_size<2*1024*1024
        print(json.dumps({'spool_warm_bytes':first_size,'spool_final_bytes':last_size,'churned_uploads':1200}))


def test_repeated_diagnostics_have_finite_retention(tmp_path,monkeypatch):
    from agentic_rag import worker
    from agentic_rag.hooks import common
    monkeypatch.setattr(worker,'LOG_PATH',tmp_path/'worker.log')
    monkeypatch.setattr(common,'HOOK_LOG',tmp_path/'hooks.log')
    for _ in range(600):
        worker._log('x'*8192)
        common.log_hook_error('synthetic','y'*8192)
    for name in ('worker','hooks'):
        files=list(tmp_path.glob(name+'.log*'))
        assert len(files)<=4
        assert sum(path.stat().st_size for path in files)<=4*1048576
