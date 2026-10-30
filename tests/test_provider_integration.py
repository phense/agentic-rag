"""R061-R01: persisted CLI interruption, bounded resume and catch-up rollback."""
from hashlib import sha256
import json

import httpx
from psycopg import sql

from agentic_rag import cli, db, providers, query_cache, search, store
from agentic_rag.config import load_config


def _snapshot(cfg, tables=None):
    """Fresh readonly connection; hashes retain IDs, timestamps and vector bytes."""
    with db.connect(cfg) as connection:
        connection.execute('SET TRANSACTION READ ONLY')
        connection.execute("SET LOCAL TIME ZONE 'UTC'")
        if tables is None:
            tables=[r['tablename'] for r in connection.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
        result={}
        for table in tables:
            rows=[r['value'] for r in connection.execute(sql.SQL(
                'SELECT to_jsonb(t)::text value FROM public.{} t ORDER BY to_jsonb(t)::text COLLATE "C"'
            ).format(sql.Identifier(table)))]
            encoded=json.dumps(rows,separators=(',',':')).encode()
            result[table]={'rows':rows,'sha256':sha256(encoded).hexdigest()}
        return result


def _sequences(cfg):
    with db.connect(cfg) as connection:
        return connection.execute("SELECT sequencename,last_value FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename").fetchall()


def test_cli_resume_and_catchup_rollback_preserve_post_cutover_writes(conn,cfg,tmp_path,monkeypatch,capsys):
    # Mutations this catches: implicit commits, replaying completed batches,
    # provider fallback, trusting stale coverage, or restoring a stale DB snapshot.
    conn.commit()  # All subsequent CLI commands open and close their own connection.
    config=tmp_path/'recovery.toml'
    config.write_text(f'''[db]
name = "{cfg.db_name}"
[ollama]
url = "http://127.0.0.1:1"
[embedding_profiles.a]
provider = "ollama"
model = "recover-a"
revision = "{'a'*64}"
url = "http://127.0.0.1:17444"
dimensions = 2
max_batch = 1
[embedding_profiles.b]
provider = "ollama"
model = "recover-b"
revision = "{'b'*64}"
url = "http://127.0.0.1:17444"
dimensions = 3
max_batch = 1
''')
    monkeypatch.setenv('AGENTIC_RAG_CONFIG',str(config))
    configured=load_config()
    assert configured.embed_dim==1024 and configured.embed_model=='bge-m3'
    assert configured.embedding_profiles['a'].dimensions==2
    assert configured.embedding_profiles['b'].dimensions==3

    # Only legacy inference/discovery is replaced. Managed profile identity,
    # response validation and all PostgreSQL/CLI behavior remain real.
    monkeypatch.setattr(store,'try_embed_texts',lambda texts,cfg:[[0.,1.]+[0.]*1022 for _ in texts])
    monkeypatch.setattr(query_cache,'model_digest',lambda cfg:None)
    state={'fail':False,'operation':(), 'requests':[], 'corpus':[], 'allowed':set()}
    dimensions={'recover-a':2,'recover-b':3}
    def handler(request):
        assert request.url.host=='127.0.0.1' and request.url.port==17444
        if request.url.path=='/api/tags':
            state['requests'].append({'method':'GET','operation':state['operation']})
            return httpx.Response(200,json={'models':[
                {'name':'recover-a:latest','digest':'a'*64},
                {'name':'recover-b:latest','digest':'b'*64}]})
        assert request.url.path=='/api/embed' and request.method=='POST'
        body=json.loads(request.content)
        model=body['model'];texts=body['input']
        assert model in dimensions and len(texts)==1
        record={'method':'POST','operation':state['operation'],'model':model,
                'texts':texts,'dimensions':dimensions[model],'failed':state['fail']}
        state['requests'].append(record)
        if state['operation'][:2]==('index','build'):
            assert all(text in state['allowed'] for text in texts)
            state['corpus'].append(record)
        if state['fail']:
            return httpx.Response(503,json={'error':'RECOVERY_PRIVATE_RESPONSE_SENTINEL'})
        vectors=[]
        for text in texts:
            # Allows fixed synthetic lifecycle probes while proving the new
            # post-cutover source requires generation A for semantic retrieval.
            near='POSTCUTOVER' in text or text=='latentnovel'
            vectors.append(([1.,0.] if near else [0.,1.])+[0.]*(dimensions[model]-2))
        return httpx.Response(200,json={'embeddings':vectors})
    transport=httpx.MockTransport(handler)
    monkeypatch.setattr(providers,'_http_client',lambda **kw:httpx.Client(transport=transport,**kw))

    def command(*args,expected=0):
        state['operation']=tuple(args)
        result=cli.main(list(args))
        captured=capsys.readouterr()
        assert result==expected,(args,captured.out,captured.err)
        assert 'RECOVERY_PRIVATE_RESPONSE_SENTINEL' not in captured.out+captured.err
        return captured

    def index_status(name):
        return json.loads(command('index','status',name).out)

    def current_sources():
        with db.connect(configured) as connection:
            return connection.execute('SELECT c.id,c.content,c.document_id,d.slug FROM chunks c JOIN documents d ON d.id=c.document_id ORDER BY c.id').fetchall()

    def active_name():
        with db.connect(configured) as connection:
            row=connection.execute('SELECT g.name FROM embedding_selection s JOIN embedding_generations g ON g.id=s.generation_id').fetchone()
            return row['name'] if row else None

    def rollback_audits():
        with db.connect(configured) as connection:
            return connection.execute("SELECT to_jsonb(a)::text value FROM audit_log a WHERE op='index_rollback' ORDER BY id").fetchall()

    command('domain','add','general')
    for title,slug,body in [('First source','recovery-first','FIRST original grounded evidence.'),
                            ('Second source','recovery-second','SECOND original grounded evidence.')]:
        command('save','--title',title,'--slug',slug,'--body',body,'--domain','general','--dtype','reference','--scope','global')
    initial_sources=current_sources()
    assert len(initial_sources)==2
    state['allowed']={r['content'] for r in initial_sources}
    source_tables=['documents','chunks','edges','pins','claim_records','claim_evidence',
        'fact_assertions','assertion_sources','knowledge_sources','mining_queue','continuation_checkpoints','mining_batches']
    originals=_snapshot(configured,source_tables)
    original_audits=_snapshot(configured,['audit_log'])['audit_log']['rows']

    generation_a=json.loads(command('index','create','space-a','--profile','a').out)
    assert generation_a['dimensions']==2 and active_name() is None
    first=json.loads(command('index','build','space-a','--batch-size','1','--allow-corpus').out)
    assert (first['written'],first['indexed'],first['remaining'])==(1,1,1)
    # A separate status command/connection proves the batch survived its process boundary.
    assert index_status('space-a')['indexed']==1
    with db.connect(configured) as connection:
        preserved_vector=connection.execute('SELECT chunk_id,source_hash,embedding::text vector,indexed_at FROM embedding_vectors WHERE generation_id=%s',(generation_a['id'],)).fetchone()
    before_failure=_snapshot(configured);before_sequences=_sequences(configured)
    state['fail']=True
    failed=command('index','build','space-a','--batch-size','1','--allow-corpus',expected=3)
    assert 'temporarily unavailable' in failed.err or 'transient' in failed.err
    state['fail']=False
    assert _snapshot(configured)==before_failure
    assert _sequences(configured)==before_sequences
    assert active_name() is None
    failed_inputs=[r for r in state['corpus'] if r['failed']]
    assert len(failed_inputs)==1  # No automatic retries or fallback inference.

    resumed=json.loads(command('index','build','space-a','--batch-size','1','--allow-corpus').out)
    assert (resumed['written'],resumed['remaining'])==(1,0)
    with db.connect(configured) as connection:
        assert connection.execute('SELECT chunk_id,source_hash,embedding::text vector,indexed_at FROM embedding_vectors WHERE generation_id=%s AND chunk_id=%s',
            (generation_a['id'],preserved_vector['chunk_id'])).fetchone()==preserved_vector
    successful_a=[r for r in state['corpus'] if r['model']=='recover-a' and not r['failed']]
    assert len(successful_a)==2 and {r['texts'][0] for r in successful_a}==state['allowed']
    assert failed_inputs[0]['texts']==successful_a[-1]['texts']
    command('index','activate','space-a')
    assert active_name()=='space-a'
    assert _snapshot(configured,source_tables)==originals

    generation_b=json.loads(command('index','create','space-b','--profile','b').out)
    assert generation_b['dimensions']==3 and generation_b['id']!=generation_a['id']
    while index_status('space-b')['remaining']:
        batch=json.loads(command('index','build','space-b','--batch-size','1','--allow-corpus').out)
        assert batch['written']==1
    command('index','activate','space-b')
    assert active_name()=='space-b'
    assert _snapshot(configured,source_tables)==originals

    command('save','--title','Post cutover source','--slug','recovery-postcutover',
        '--body','POSTCUTOVER novel rollback retention evidence.','--domain','general','--dtype','reference','--scope','global')
    complete_sources=current_sources()
    new_sources=[r for r in complete_sources if r['slug']=='recovery-postcutover']
    assert len(new_sources)==1 and len(complete_sources)==3
    assert {r['id'] for r in initial_sources}<={r['id'] for r in complete_sources}
    after_new_save=_snapshot(configured,source_tables)
    all_saved_audits=_snapshot(configured,['audit_log'])['audit_log']['rows']
    assert set(original_audits)<=set(all_saved_audits)
    state['allowed']={r['content'] for r in complete_sources}

    # Canonical evidence remains usable while the selected managed index is stale.
    lexical=json.loads(command('search','novel rollback retention','--strategy','lexical','--rerank','off','--scope','global','--json').out)
    assert str(new_sources[0]['document_id']) in {r['document_id'] for r in lexical['results']}
    before_refusal=_snapshot(configured);before_refusal_sequences=_sequences(configured)
    command('index','rollback','space-a',expected=1)
    assert active_name()=='space-b' and rollback_audits()==[]
    assert _snapshot(configured)==before_refusal
    assert _sequences(configured)==before_refusal_sequences
    assert index_status('space-a')['remaining']==1
    command('index','build','space-a','--batch-size','1','--allow-corpus')
    assert index_status('space-a')['remaining']==0
    command('index','rollback','space-a')
    assert active_name()=='space-a' and len(rollback_audits())==1
    assert not index_status('space-b')['active']
    assert index_status('space-b')['remaining']==1  # Retained, not restored over new canonical writes.
    assert _snapshot(configured,source_tables)==after_new_save
    assert set(all_saved_audits)<=set(_snapshot(configured,['audit_log'])['audit_log']['rows'])
    assert current_sources()==complete_sources
    assert all(set(originals[t]['rows'])<=set(after_new_save[t]['rows']) for t in source_tables)
    retained_originals=json.loads(command('search','original grounded evidence','--strategy','lexical',
        '--context','off','--rerank','off','--scope','global','--json').out)
    assert {r['document_id'] for r in retained_originals['results']}=={str(r['document_id']) for r in initial_sources}
    assert {r['chunk_id'] for r in retained_originals['results']}=={str(r['id']) for r in initial_sources}
    completed_a=[r for r in state['corpus'] if r['model']=='recover-a' and not r['failed']]
    assert len(completed_a)==3 and {r['texts'][0] for r in completed_a}==state['allowed']

    # Query text is absent from canonical sources: this hit requires caught-up A vectors.
    monkeypatch.setattr(search,'try_embed_texts',lambda *a:(_ for _ in ()).throw(AssertionError('managed query used legacy inference')))
    queried_from=len(state['requests'])
    semantic=json.loads(command('search','latentnovel','--strategy','hybrid','--context','off','--rerank','off','--scope','global','-k','1','--json').out)
    assert not semantic['warnings']
    assert [r['document_id'] for r in semantic['results']]==[str(new_sources[0]['document_id'])]
    hit=semantic['results'][0]
    assert hit['chunk_id']==str(new_sources[0]['id'])
    assert new_sources[0]['content'][hit['snippet_start']:hit['snippet_end']]==hit['snippet']
    query_posts=[r for r in state['requests'][queried_from:] if r['method']=='POST']
    assert len(query_posts)==1 and query_posts[0]['model']=='recover-a' and query_posts[0]['dimensions']==2
    assert all(len(r['texts'])<=1 for r in state['corpus'])
