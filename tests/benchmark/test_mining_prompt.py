from dataclasses import replace
from unittest.mock import Mock
import pytest
from agentic_rag.config import Config
from agentic_rag import mining


def test_prompt_candidate_rejects_canonical_before_any_query():
    conn=Mock()
    with pytest.raises(ValueError,match='owned'):
        mining.mine_session(conn,Config(),session_id='public',transcript_path='absent',
            last_uuid=None,project='/synthetic/evaluation/a',benchmark_prompt='correction-v1')
    conn.execute.assert_not_called()


def test_unknown_prompt_rejected_before_any_query():
    conn=Mock()
    with pytest.raises(ValueError,match='prompt'):
        mining.mine_session(conn,Config(db_name='rag_bench_'+'a'*24),session_id='public',
            transcript_path='absent',last_uuid=None,project='/synthetic/evaluation/a',benchmark_prompt='unreviewed')
    conn.execute.assert_not_called()


def test_prompt_candidate_rejects_missing_owner_marker():
    conn=Mock();conn.execute.return_value.fetchall.return_value=[]
    with pytest.raises(ValueError,match='ownership'):
        mining.mine_session(conn,Config(db_name='rag_bench_'+'a'*24),session_id='public',
            transcript_path='absent',last_uuid=None,project='/synthetic/evaluation/a',benchmark_prompt='correction-v1')
    conn.commit.assert_not_called()
