"""Populated025→026 and exact original-row recovery evidence, disposable DB only."""
import uuid

import pytest
from agentic_rag import db,store
from agentic_rag.service import upgrade
from agentic_rag.service.schema import validate_schema,ServiceSchemaError
from test_maintenance_restore import owned_source


def test_populated025_restore_migrate_retry_and_original_preservation(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'try_embed_texts',lambda *a,**k:None)
    monkeypatch.setattr('agentic_rag.query_cache.model_digest',lambda cfg:'a'*64)
    with owned_source(tmp_path,25) as cfg:
        with db.connect(cfg) as conn:
            conn.execute("INSERT INTO service_streams(session_id,owner_namespace,project,last_cursor) VALUES ('legacy-session','legacy-owner','/synthetic/backup','cursor1')")
            conn.execute("INSERT INTO service_windows(owner_namespace,session_id,input_cursor,output_cursor,content_hash,payload,project) VALUES ('legacy-owner','legacy-session','','cursor1','original-hash','{\"synthetic_original\":true}','/synthetic/backup')")
            conn.execute("INSERT INTO service_requests(id,owner_namespace,team,envelope_hash,authority,permission_hash,tool,arguments,expires_at) VALUES (%s,'legacy-owner','legacy-team','hash','{}','authority','memory_domains','{}',now()+interval '5 minutes')",(uuid.uuid4(),))
        original=upgrade.inventory(cfg,'0.6.12')
        assert original['tables']['service_windows']['rows']==1 and original['tables']['service_requests']['rows']==1
        changed=upgrade.local_upgrade(cfg,'0.6.12',tmp_path/'025-to026.dump',apply=True,writers_stopped=True)
        assert changed['restore_verified'] and changed['original_rows_unchanged']
        assert changed['migrations_applied']==['026_request_tracing.sql','027_provider_indexes.sql','028_reranker_settings.sql','029_source_evidence.sql','030_pattern_synthesis.sql','031_memory_lifecycle.sql','032_extraction_policy.sql']
        assert upgrade.verify_preserved(cfg,original)['unchanged']
        with db.connect(cfg) as conn:
            validate_schema(conn)
            assert conn.execute('SELECT origin_request_id,origin_correlation_id FROM service_windows').fetchone()=={'origin_request_id':None,'origin_correlation_id':None}
            # Omitting an added field must never mask a wrong schema definition.
            conn.execute('ALTER TABLE service_windows ALTER COLUMN origin_request_id TYPE text USING origin_request_id::text')
            with pytest.raises(ValueError,match='origin_schema'):upgrade._verify(conn,original,preserved=True)
            conn.rollback()
        retry=upgrade.local_upgrade(cfg,'0.6.12',tmp_path/'026-retry.dump',apply=True,writers_stopped=True)
        assert retry['migrations_applied']==[] and retry['restore_verified'] and retry['original_rows_unchanged']
        current=upgrade.verified_backup(cfg,'0.6.13',tmp_path/'026-current.dump')
        assert current['restore_verified']
        print('TRACE_UPGRADE',{'original_tables':len(original['tables']),'original_rows':sum(t['rows'] for t in original['tables'].values()),'restores':3,'applied':changed['migrations_applied']})
