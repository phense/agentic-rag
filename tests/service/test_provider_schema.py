"""A service must refuse an installation that exposes managed index writes."""
import pytest

from agentic_rag.service.schema import ServiceSchemaError, validate_schema


@pytest.mark.parametrize('change', [
    'ALTER TABLE embedding_vectors DISABLE ROW LEVEL SECURITY',
    'GRANT UPDATE ON embedding_generations TO rag_writer',
    'GRANT UPDATE (generation_id) ON embedding_selection TO rag_reader',
])
def test_service_rejects_managed_index_authority_drift(conn, change):
    validate_schema(conn)
    conn.execute(change)
    with pytest.raises(ServiceSchemaError):
        validate_schema(conn)
