"""Large legacy content must be rejected before loading it into the API process."""
import asyncio
from dataclasses import replace
import pytest
from agentic_rag import db,store
from agentic_rag.service.engine import invoke,ServiceError
from .test_scope import service_store,principal


def test_remote_get_refuses_large_legacy_body_without_changing_local_contract(service_store,monkeypatch):
    cfg,docs=service_store
    monkeypatch.setattr(store,'try_embed_texts',lambda *a,**k:None)
    with db.connect(cfg) as conn:
        store.save_document(conn,cfg,doc_id=docs['allowed'],title='Large legacy record',body='x'*(1024*1024),domain='alpha',dtype='memory',project='/projects/a')
    try:
        with pytest.raises(ServiceError,match='result_too_large'):
            asyncio.run(invoke('memory_get',{'id_or_slug':'allowed'},principal(),cfg))
        with db.connect(cfg) as conn:assert len(store.get_document(conn,'allowed')['body'])==1024*1024
    finally:
        with db.connect(cfg) as conn:
            store.save_document(conn,cfg,doc_id=docs['allowed'],title='allowed',body='Synthetic protected evidence allowed',domain='alpha',dtype='memory',project='/projects/a')


@pytest.mark.parametrize('count',[0,1000,1001])
def test_remote_rows_preserve_native_values_order_and_exact_row_limit(service_store,count):
    # Guarded projection must keep UUID/time/null types and caller ordering;
    # the first row beyond the published 1000-row budget must reject the result.
    from datetime import datetime,timezone
    from uuid import UUID
    from agentic_rag.service.context import request_scope
    from agentic_rag.service.read_limits import rows
    cfg,docs=service_store
    query='SELECT %s::uuid identity,%s::timestamptz event_at,g.i position,NULL::text note FROM generate_series(1,%s) g(i) ORDER BY g.i DESC'
    with request_scope(principal(),cfg,read_only=True),db.connect(cfg,role='reader') as conn:
        if count>1000:
            with pytest.raises(ServiceError,match='result_too_large'):
                rows(conn,query,(docs['allowed'],'2026-10-01T00:00:00Z',count))
        else:
            result=rows(conn,query,(docs['allowed'],'2026-10-01T00:00:00Z',count))
            assert len(result)==count
            if count:
                assert result[0]=={'identity':UUID(docs['allowed']),'event_at':datetime(2026,10,1,tzinfo=timezone.utc),'position':1000,'note':None}
                assert result[-1]['position']==1
