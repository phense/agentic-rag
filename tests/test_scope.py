from dataclasses import replace
import subprocess
from pathlib import Path

import pytest
from agentic_rag import domains,store,search


def test_normalization_preserves_pin_subdirectory_and_maps_worktrees(tmp_path):
    from agentic_rag.scope import project_id, path_anchor, selection
    root=tmp_path/'repo';root.mkdir()
    subprocess.run(['git','init','-q',str(root)],check=True)
    subprocess.run(['git','-C',str(root),'-c','user.name=Test','-c','user.email=test@example.invalid','commit','-qm','initial','--allow-empty'],check=True)
    wt=tmp_path/'linked'
    subprocess.run(['git','-C',str(root),'worktree','add','-qb','linked',str(wt)],check=True)
    (root/'nested').mkdir();(wt/'nested').mkdir()
    alias=tmp_path/'alias';alias.symlink_to(wt,target_is_directory=True)
    assert project_id(str(alias/'nested'))==str(root)
    assert path_anchor(str(alias/'nested'))==str(root/'nested')
    assert str(root) in selection(str(alias/'nested'))
    assert selection(None,'global')==['global']
    assert selection(None,'all') is None
    with pytest.raises(ValueError):selection(None,'project')


def test_scoped_search_global_unknown_and_update(conn,cfg):
    from agentic_rag.scope import selection
    cfg=replace(cfg,ollama_url='http://127.0.0.1:1')
    domains.add_domain(conn,'scope-test')
    def save(title,**kw):return store.save_document(conn,cfg,title=title,body='ScopeCollisionError',domain='scope-test',dtype='signal',**kw)
    a=save('A',project='/scope/a');save('B',project='/scope/b');save('Global',scope='global');save('Unknown')
    hits,_=search.search(conn,cfg,'ScopeCollisionError',project='/scope/a')
    assert {h.title for h in hits}=={'A','Global'}
    assert {h.title for h in search.search(conn,cfg,'ScopeCollisionError',scope='global')[0]}=={'Global'}
    assert len(search.search(conn,cfg,'ScopeCollisionError',scope='all')[0])==4
    store.save_document(conn,cfg,title='A updated',body='ScopeCollisionError',domain='scope-test',dtype='signal',doc_id=a.doc_id)
    assert conn.execute('SELECT project_scope FROM documents WHERE id=%s',(a.doc_id,)).fetchone()['project_scope']=='/scope/a'


def test_pin_wildcards_and_foreign_project_never_match(conn):
    from agentic_rag import pins
    domains.add_domain(conn,'scope-test')
    pins.add_pin(conn,body='parent',scope='/scope')
    pins.add_pin(conn,body='a',scope='/scope/a_1')
    pins.add_pin(conn,body='b',scope='/scope/b')
    pins.add_pin(conn,body='global')
    assert {p.body for p in pins.matching_pins(conn,'/scope/aX1/sub')}=={'parent','global'}
    assert {p.body for p in pins.matching_pins(conn,'/scope/a_1/sub')}=={'a','parent','global'}


def test_scope_filters_before_candidate_limit_and_graph_recursion(conn,cfg):
    from agentic_rag import graph
    cfg=replace(cfg,ollama_url='http://127.0.0.1:1')
    domains.add_domain(conn,'scope-test')
    def save(title,project,body='ScopeCollisionError',edges=None):
        return store.save_document(conn,cfg,title=title,body=body,domain='scope-test',dtype='signal',project=project,edges=edges)
    for i in range(55):save(f'Foreign {i}','/scope/b',body='ScopeCollisionError '*10)
    a=save('A','/scope/a');z=save('Z','/scope/a')
    b=save('Bridge B','/scope/b',edges=[store.EdgeSpec('references',a.slug),store.EdgeSpec('references',z.slug)])
    hits,_=search.search(conn,cfg,'ScopeCollisionError',project='/scope/a',k=2)
    assert {h.slug for h in hits}=={a.slug,z.slug}
    assert graph.path(conn,a.doc_id,z.doc_id)
    assert graph.path(conn,a.doc_id,z.doc_id,project='/scope/a')==[]
    assert graph.neighbors(conn,a.doc_id,depth=3,project='/scope/a')==[]


def test_curation_requires_equal_known_scopes(conn,cfg):
    from agentic_rag import curation
    cfg=replace(cfg,ollama_url='http://127.0.0.1:1')
    domains.add_domain(conn,'scope-test')
    def save(title,**kw):return store.save_document(conn,cfg,title=title,body='identical source fact',domain='scope-test',dtype='memory',**kw)
    a=save('A',project='/scope/a');a2=save('A2',project='/scope/a')
    b=save('B',project='/scope/b',actor='mining',edges=[store.EdgeSpec('contradicts',a.slug,evidence='foreign assertion')])
    u=save('U');u2=save('U2')
    assert curation._refute_candidates(conn,20)==[]
    assert curation._merge_exact_duplicates(conn,20)==1
    assert conn.execute("SELECT count(*) AS n FROM documents WHERE status='active'").fetchone()['n']==4
    assert curation.review_report(conn,cfg)['unknown_scope_count']==2


def test_audited_legacy_mapping_and_rollback(conn,cfg,monkeypatch):
    from agentic_rag import scope
    cfg=replace(cfg,ollama_url='http://127.0.0.1:1')
    domains.add_domain(conn,'scope-test')
    a=store.save_document(conn,cfg,title='Legacy A',body='fact',domain='scope-test',dtype='memory')
    # Model a pre-migration row; test fixture setup is deliberately direct SQL.
    conn.execute("UPDATE documents SET provenance=%s::jsonb WHERE id=%s",('{"project":"/scope/a"}',a.doc_id));conn.commit()
    original=store.set_project_scope
    def fail(*a,**k):
        original(*a,**k)
        raise RuntimeError('simulated crash during backfill')
    monkeypatch.setattr(store,'set_project_scope',fail)
    with pytest.raises(RuntimeError):scope.backfill(conn)
    assert conn.execute('SELECT project_scope FROM documents WHERE id=%s',(a.doc_id,)).fetchone()['project_scope']=='unknown'
    monkeypatch.setattr(store,'set_project_scope',original)
    assert scope.backfill(conn)['documents_mapped']==1
    assert scope.backfill(conn)['documents_mapped']==0
    row=conn.execute('SELECT project_scope,provenance FROM documents WHERE id=%s',(a.doc_id,)).fetchone()
    assert row['project_scope']=='/scope/a' and row['provenance']=={'project':'/scope/a'}
    assert conn.execute("SELECT count(*) AS n FROM audit_log WHERE op='set_project_scope'").fetchone()['n']==1


def test_prompt_recall_and_startup_share_project_policy(conn,cfg,hook_env):
    import io,json
    from agentic_rag import pins
    from agentic_rag.hooks import prompt_recall,session_start
    cfg=replace(cfg,ollama_url='http://127.0.0.1:1')
    domains.add_domain(conn,'scope-test')
    for title,kwargs in [('Allowed A',{'project':'/scope/a'}),('Foreign B',{'project':'/scope/b'}),('Shared',{'scope':'global'}),('Unknown',{})]:
        store.save_document(conn,cfg,title=title,body='ScopeCollisionError',domain='scope-test',dtype='signal',**kwargs)
    pins.add_pin(conn,body='ScopeCollisionError PIN B',scope='/scope/b')
    pins.add_pin(conn,body='ScopeCollisionError PIN A',scope='/scope/a')
    pins.add_pin(conn,body='ScopeCollisionError PIN GLOBAL')
    out=io.StringIO()
    prompt_recall.run({'prompt':'ScopeCollisionError','cwd':'/scope/a/sub'},out)
    ctx=json.loads(out.getvalue())['hookSpecificOutput']['additionalContext']
    assert 'Allowed A' in ctx and 'Shared' in ctx and 'PIN A' in ctx and 'PIN GLOBAL' in ctx
    assert 'Foreign B' not in ctx and 'Unknown' not in ctx and 'PIN B' not in ctx
    context=session_start.build_context(conn,cfg,'/scope/a/sub')
    assert 'Allowed A' in context and 'Shared' in context and 'Foreign B' not in context and 'Unknown' not in context


def test_near_duplicate_candidate_cannot_cross_project(conn,cfg,monkeypatch):
    from agentic_rag import mining
    cfg=replace(cfg,ollama_url='http://127.0.0.1:1')
    domains.add_domain(conn,'scope-test')
    doc=store.save_document(conn,cfg,title='B',body='fact',domain='scope-test',dtype='memory',project='/scope/b')
    vector='['+','.join(['0.1']*1024)+']'
    conn.execute('UPDATE chunks SET embedding=%s::halfvec WHERE document_id=%s',(vector,doc.doc_id))
    monkeypatch.setattr(mining,'try_embed_texts',lambda *a:[[.1]*1024])
    assert mining._near_duplicate(conn,cfg,'fact','fact','scope-test',project='/scope/a') is None
    assert mining._near_duplicate(conn,cfg,'fact','fact','scope-test',project='/scope/b')==doc.slug
    assert mining._near_duplicate(conn,cfg,'fact','fact','scope-test') is None


def test_scope_repair_preserves_freshness_and_conflicting_legacy_stays_unknown(conn,cfg):
    from agentic_rag.scope import backfill
    cfg=replace(cfg,ollama_url='http://127.0.0.1:1');domains.add_domain(conn,'scope-test')
    a=store.save_document(conn,cfg,title='A',body='fact',domain='scope-test',dtype='memory')
    old=conn.execute('SELECT updated_at FROM documents WHERE id=%s',(a.doc_id,)).fetchone()['updated_at']
    store.set_project_scope(conn,a.doc_id,project='/scope/a')
    assert conn.execute('SELECT updated_at FROM documents WHERE id=%s',(a.doc_id,)).fetchone()['updated_at']==old
    b=store.save_document(conn,cfg,title='Ambiguous',body='fact',domain='scope-test',dtype='memory',provenance={'project':'/scope/a'},meta={'project':'/scope/b'})
    assert conn.execute('SELECT project_scope FROM documents WHERE id=%s',(b.doc_id,)).fetchone()['project_scope']=='unknown'
    assert backfill(conn)['unknown']==[{'slug':b.slug,'reason':'conflicting project metadata'}]


def test_nested_git_repo_is_not_outer_project_but_parent_pins_apply(tmp_path,monkeypatch):
    from agentic_rag.scope import selection,pin_paths
    outer=tmp_path/'outer';outer.mkdir()
    subprocess.run(['git','init','-q',str(outer)],check=True)
    nested=outer/'nested';nested.mkdir()
    subprocess.run(['git','init','-q',str(nested)],check=True)
    # Foreign git environment must not override the caller's project.
    monkeypatch.setenv('GIT_DIR',str(outer/'.git'))
    assert selection(str(nested))==['global',str(nested)]
    assert str(outer) in pin_paths(str(nested))


def test_additive_legacy_migration_and_reader_privileges(cfg,tmp_path,monkeypatch):
    import shutil
    import psycopg
    from agentic_rag import db,pins,scope
    from agentic_rag.benchmark.database import isolated_database
    old=tmp_path/'sql';old.mkdir()
    for file in db.SQL_DIR.glob('*.sql'):
        if file.name < '010':shutil.copyfile(file,old/file.name)
    initialize=db.init_db
    monkeypatch.setattr(db,'init_db',lambda config:initialize(config,sql_dir=old))
    with isolated_database(cfg) as isolated:
        with db.connect(isolated,role='owner') as connection:
            row=connection.execute("INSERT INTO documents(slug,domain,dtype,title,body,provenance) VALUES ('old','general','memory','Old','fact','{\"project\":\"/scope/a\"}') RETURNING id,updated_at").fetchone()
            connection.execute("INSERT INTO pins(body,scope) VALUES ('old pin','/scope/a')")
            connection.commit()
            assert db.apply_migrations(connection,db.SQL_DIR)==['010_project_scope.sql']
            assert db.apply_migrations(connection,db.SQL_DIR)==[]
            assert scope.backfill(connection)['documents_mapped']==1
            actual=connection.execute('SELECT updated_at,provenance,project_scope FROM documents WHERE id=%s',(row['id'],)).fetchone()
            assert actual['updated_at']==row['updated_at']
            assert actual['provenance']=={'project':'/scope/a'}
            assert actual['project_scope']=='/scope/a'
            assert pins.matching_pins(connection,'/scope/a/sub')[0].body=='old pin'
        with db.connect(isolated,role='reader') as reader:
            assert reader.execute('SELECT project_scope FROM documents').fetchone()['project_scope']=='/scope/a'
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                store.set_project_scope(reader,str(row['id']),scope='global')


def test_mcp_and_cli_selection_contracts(conn,cfg,hook_env,capsys):
    import json
    from agentic_rag import mcp_server,cli
    domains.add_domain(conn,'scope-test')
    mcp_server.memory_save('Project A','ScopeCollisionError','scope-test',project='/scope/a')
    mcp_server.memory_save('Project B','ScopeCollisionError','scope-test',project='/scope/b')
    mcp_server.memory_save('Global','ScopeCollisionError','scope-test',scope='global')
    assert {h['title'] for h in mcp_server.memory_search('ScopeCollisionError',project='/scope/a')['results']}=={'Project A','Global'}
    assert cli.main(['search','ScopeCollisionError','--project','/scope/b','--json'])==0
    result=json.loads(capsys.readouterr().out)
    assert {h['title'] for h in result['results']}=={'Project B','Global'}
    with pytest.raises(ValueError):mcp_server.memory_search('ScopeCollisionError',project='/scope/a',scope='all')


def test_explicit_repair_remains_authoritative_on_later_content_update(conn,cfg):
    cfg=replace(cfg,ollama_url='http://127.0.0.1:1');domains.add_domain(conn,'scope-test')
    source={'project':'/scope/a'}
    doc=store.save_document(conn,cfg,title='Original',body='fact',domain='scope-test',dtype='memory',provenance=source)
    store.set_project_scope(conn,doc.doc_id,project='/scope/b')
    store.save_document(conn,cfg,doc_id=doc.doc_id,title='Edited',body='new fact',domain='scope-test',dtype='memory',provenance=source)
    actual=conn.execute('SELECT project_scope,provenance FROM documents WHERE id=%s',(doc.doc_id,)).fetchone()
    assert actual['project_scope']=='/scope/b'
    assert actual['provenance']==source


def test_git_timeout_does_not_expand_to_parent_project(tmp_path,monkeypatch):
    from agentic_rag import scope
    nested=tmp_path/'outer'/'nested';nested.mkdir(parents=True)
    def timeout(*args,**kwargs):raise subprocess.TimeoutExpired('git',1)
    monkeypatch.setattr(scope.subprocess,'run',timeout)
    assert scope.selection(str(nested))==['global',str(nested)]


def test_refute_rechecks_scopes_after_model_response(conn,cfg,monkeypatch):
    from agentic_rag import curation,db
    cfg=replace(cfg,ollama_url='http://127.0.0.1:1');domains.add_domain(conn,'scope-test')
    old=store.save_document(conn,cfg,title='Old A',body='old fact',domain='scope-test',dtype='memory',project='/scope/a')
    store.save_document(conn,cfg,title='Contradiction A',body='contradicting fact',domain='scope-test',dtype='lesson',project='/scope/a',actor='mining',edges=[store.EdgeSpec('contradicts',old.slug,evidence='quote')])
    def model(*args,**kwargs):
        with db.connect(cfg,role='writer') as other:
            store.set_project_scope(other,old.doc_id,project='/scope/b')
        return {'refute':True,'reason':'different evidence','quote':'quote'}
    monkeypatch.setattr(curation,'run_structured',model)
    assert curation._review_refutes(conn,cfg,1,None)==(0,0)
    assert conn.execute('SELECT status FROM documents WHERE id=%s',(old.doc_id,)).fetchone()['status']=='active'
    assert conn.execute("SELECT count(*) AS n FROM audit_log WHERE op IN ('refute','refute_review')").fetchone()['n']==0


def test_explicit_unknown_cannot_be_promoted_by_legacy_backfill(conn,cfg):
    from agentic_rag.scope import backfill
    cfg=replace(cfg,ollama_url='http://127.0.0.1:1');domains.add_domain(conn,'scope-test')
    doc=store.save_document(conn,cfg,title='Quarantined',body='fact',domain='scope-test',dtype='memory',scope='unknown',provenance={'project':'/scope/a'})
    assert backfill(conn)['documents_mapped']==0
    row=conn.execute('SELECT project_scope,scope_explicit FROM documents WHERE id=%s',(doc.doc_id,)).fetchone()
    assert row['project_scope']=='unknown' and row['scope_explicit']


def test_pin_mapping_failure_rolls_back_document_mapping(conn,cfg,monkeypatch):
    from agentic_rag import pins,scope
    cfg=replace(cfg,ollama_url='http://127.0.0.1:1');domains.add_domain(conn,'scope-test')
    doc=store.save_document(conn,cfg,title='Legacy',body='fact',domain='scope-test',dtype='memory')
    conn.execute('UPDATE documents SET provenance=%s::jsonb WHERE id=%s',('{"project":"/scope/a"}',doc.doc_id));conn.commit()
    def failed(*a):raise RuntimeError('pin path unavailable')
    monkeypatch.setattr(pins,'refresh_scope_paths',failed)
    with pytest.raises(RuntimeError):scope.backfill(conn)
    assert conn.execute('SELECT project_scope FROM documents WHERE id=%s',(doc.doc_id,)).fetchone()['project_scope']=='unknown'
    assert conn.execute("SELECT count(*) AS n FROM audit_log WHERE op='set_project_scope'").fetchone()['n']==0


def test_vector_candidate_scope_precedes_limit(conn,cfg,monkeypatch):
    import json
    from agentic_rag import db
    cfg=replace(cfg,ollama_url='http://127.0.0.1:1');domains.add_domain(conn,'scope-test')
    # SQL fixture setup avoids embedding calls; more than one candidate window of B.
    for i in range(55):
        row=conn.execute("INSERT INTO documents(slug,domain,dtype,title,body,project_scope) VALUES (%s,'scope-test','memory','B','irrelevant','/scope/b') RETURNING id",(f'foreign-{i}',)).fetchone()
        conn.execute('INSERT INTO chunks(document_id,idx,content,embedding) VALUES (%s,0,%s,%s::halfvec)',(row['id'],'irrelevant',json.dumps([1.0]+[0.0]*1023)))
    a=store.save_document(conn,cfg,title='Allowed vector A',body='different content',domain='scope-test',dtype='memory',project='/scope/a')
    conn.execute('UPDATE chunks SET embedding=%s::halfvec WHERE document_id=%s',(json.dumps([0.0,1.0]+[0.0]*1022),a.doc_id));conn.commit()
    monkeypatch.setattr(search,'try_embed_texts',lambda *a:[[1.0]+[0.0]*1023])
    with db.connect(cfg,role='reader') as reader:
        hits,_=search.search(reader,cfg,'no lexical matches here',project='/scope/a',k=1)
        assert [h.slug for h in hits]==[a.slug]
