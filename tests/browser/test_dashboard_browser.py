"""Real browser→HTTP→session/RLS/queue checks; provider boundaries stay synthetic."""
from dataclasses import replace
import os
from pathlib import Path

import pytest

playwright=pytest.importorskip('playwright.sync_api')
from agentic_rag import db
from agentic_rag.service.api import create_app
from tests.service.test_scope import service_store
from tests.service.test_api import app_fixture


from tests.service.http_server import server

def sign_in(page,user='admin',password='synthetic administrator password'):
    page.get_by_label('Username',exact=True).fill(user)
    page.get_by_label('Password',exact=True).fill(password)
    page.get_by_role('button',name='Sign in',exact=True).click()
    page.get_by_role('heading',name='Your knowledge, connected.').wait_for()


def test_desktop_scoped_search_sources_and_mobile_navigation(service_store,tmp_path):
    cfg,docs=service_store
    app,_=app_fixture(tmp_path,replace(cfg,service_mode='server'))
    app.allowed_hosts.append('127.0.0.1')
    artifacts=Path(os.environ.get('RAG_BROWSER_ARTIFACT_DIR',tmp_path));artifacts.mkdir(parents=True,exist_ok=True)
    with server(app) as url,playwright.sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1080})
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(url+'/dashboard/');sign_in(page,'alice','correct horse synthetic password')
        assert page.get_by_text('foreign',exact=False).count()==0
        page.screenshot(path=str(artifacts/'dashboard-overview.png'),full_page=True)
        page.get_by_role('button',name='Browse knowledge').click()
        page.get_by_role('heading',name='Knowledge library').wait_for()
        page.get_by_label('Search your knowledge').fill('Synthetic protected evidence allowed')
        page.get_by_role('button',name='Search',exact=True).click()
        page.get_by_role('heading',name='Search results').wait_for(timeout=20000)
        page.get_by_role('button',name='allowed',exact=True).click()
        page.get_by_role('heading',name='Original sources & review').wait_for(timeout=20000)
        assert page.get_by_text('Synthetic protected evidence allowed',exact=True).count()==1
        assert 'Synthetic protected evidence foreign' not in page.locator('main').inner_text()
        page.get_by_text('Evidence, assertions and provenance',exact=True).click()
        page.get_by_role('button',name='Back to knowledge').click()
        page.get_by_role('heading',name='Knowledge library').wait_for()
        page.set_viewport_size({'width':390,'height':844});page.reload()
        page.get_by_role('heading',name='Your knowledge, connected.').wait_for()
        page.get_by_role('button',name='Toggle navigation').click()
        page.get_by_role('navigation').get_by_role('button',name='Knowledge').click()
        page.get_by_role('heading',name='Knowledge library').wait_for()
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        page.screenshot(path=str(artifacts/'dashboard-mobile.png'),full_page=True)
        # Keyboard users reach the skip link and main content.
        page.keyboard.press('Control+Home');page.keyboard.press('Tab')
        assert page.locator(':focus').count()==1
        assert not errors,errors
        browser.close()


def test_admin_enrollment_rotation_and_resumable_setup(service_store,tmp_path,monkeypatch):
    cfg,_=service_store
    from agentic_rag import llm,embed,query_cache
    monkeypatch.setattr(llm,'run_structured',lambda *a,**k:{'ok':True})
    monkeypatch.setattr(embed,'_embed_texts',lambda texts,cfg,**k:[[0.0]*1024 for _ in texts])
    monkeypatch.setattr(query_cache,'model_digest',lambda cfg:'synthetic-browser-model-identity')
    app,path=app_fixture(tmp_path,replace(cfg,service_mode='server'))
    path.write_text(path.read_text().replace('[users.alice]','[users.alice]\nsession_teams=["owner_team"]').replace('[machines.vm1]','[machines.vm1]\nsession_teams=["other_team"]'))
    app.allowed_hosts.append('127.0.0.1')
    from tests.service.test_api import KEYS
    token=tmp_path/'discovery.key';token.write_text(KEYS[0]);token.chmod(0o600)
    with server(app) as discovery:
        configured=replace(cfg,service_mode='server',service_auth_file=path,service_url=discovery,service_token_file=token)
        dashboard_app=create_app(configured,path,allowed_hosts=['127.0.0.1'])
        with server(dashboard_app) as url,playwright.sync_playwright() as p:
            _admin_enrollment_browser(cfg,path,url,p)


def _admin_enrollment_browser(cfg,path,url,p):
        browser=p.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1440,'height':1080})
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(url+'/dashboard/');sign_in(page)
        response=page.request.get(url+'/v1/capabilities',headers={'authorization':'Bearer one.synthetic-long-random-machine-secret','x-rag-protocol':'1','x-rag-client-version':'0.6.11','x-rag-client-capabilities':'protocol1,queued_tools1'})
        assert response.status==200
        page.get_by_role('navigation').get_by_role('button',name='Clients & access').click()
        page.get_by_text('Reported capabilities: protocol1,queued_tools1',exact=True).wait_for()
        vm=page.get_by_role('row').filter(has_text='vm1 · alice')
        vm.get_by_text('Configured teams: other_team',exact=True).wait_for(timeout=2000)
        assert vm.get_by_text('Effective teams: none',exact=True).count()==1
        page.get_by_role('button',name='Enroll a VM').click()
        page.get_by_label('Stable ID').fill('browser_vm')
        page.get_by_label('Display label').fill('Browser rehearsal VM')
        page.get_by_label('Owner user ID').fill('alice')
        page.get_by_label('Readable domains').fill('alpha')
        page.get_by_label('Readable projects').fill('/projects/a')
        page.get_by_role('button',name='Preview change',exact=True).click()
        try:page.get_by_role('button',name='Apply policy change',exact=True).or_(page.locator('.error')).wait_for(timeout=5000)
        except Exception:
            raise AssertionError(page.locator('main').inner_text()+' VALIDATION '+str(page.locator('form').evaluate('(form)=>Array.from(form.elements).map(x=>({name:x.name,value:x.type===\"password\"?\"[private]\":x.value,valid:x.checkValidity?.()}))')))
        assert page.locator('.error').count()==0,page.locator('main').inner_text()
        page.get_by_role('button',name='Apply policy change',exact=True).click()
        page.get_by_role('button',name='Return to clients').click()
        page.get_by_role('row').filter(has_text='Browser rehearsal VM').get_by_role('button',name='Manage').click()
        page.get_by_label('New key ID').fill('browser_key')
        page.get_by_role('button',name='Generate credential').click()
        page.get_by_role('button',name='Apply policy change').click()
        page.get_by_text('Save this credential now — shown once').wait_for()
        assert page.locator('.secret code').inner_text().startswith('browser_key.')
        page.get_by_role('button',name='I saved it').click()
        assert page.locator('.secret').count()==0
        page.get_by_role('navigation').get_by_role('button',name='Setup assistant').click()
        page.get_by_role('button',name='Upgrade an existing local store').click()
        page.get_by_text('Existing knowledge found.',exact=False).wait_for()
        for title in ['Database & schema','Required permissions','Embedding access','Provider access','Client / server compatibility']:
            page.locator('.check-row').filter(has_text=title).get_by_role('button',name='Run check').click()
            page.locator('.check-row').filter(has_text=title).get_by_text('verified',exact=True).wait_for(timeout=15000)
        page.get_by_role('button',name='Complete setup',exact=True).click()
        page.get_by_role('button',name='Setup complete',exact=True).wait_for()
        page.reload();page.get_by_role('heading',name='Your knowledge, connected.').wait_for()
        page.get_by_role('navigation').get_by_role('button',name='Setup assistant').click()
        page.get_by_role('button',name='Setup complete',exact=True).wait_for()
        # Expiry must return the actual browser to login.
        with db.connect(cfg) as conn:conn.execute("UPDATE service_sessions SET expires_at=now()-interval '1 second' WHERE user_id='admin'")
        page.get_by_role('navigation').get_by_role('button',name='Overview').click()
        page.get_by_role('button',name='Sign in',exact=True).wait_for()
        assert not errors,errors
        browser.close()


def test_browser_first_admin_then_scoped_empty_view(service_store,tmp_path):
    """First-run authorization works through the real form and HTTP boundary."""
    from agentic_rag.service.dashboard_policy import arm_bootstrap
    from agentic_rag.service.auth import Policy
    cfg,_=service_store
    path=tmp_path/'first-policy.toml';key=tmp_path/'bootstrap.key'
    arm_bootstrap(path,key)
    app=create_app(replace(cfg,service_auth_file=path),path,allowed_hosts=['127.0.0.1'])
    with server(app) as url,playwright.sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page();page.goto(url+'/dashboard/')
        page.get_by_role('heading',name='Set up secure access').wait_for()
        page.get_by_label('One-time bootstrap token').fill(key.read_text().strip())
        page.get_by_label('Username',exact=True).fill('first_operator')
        page.get_by_label('New password',exact=True).fill('synthetic browser first password')
        page.get_by_role('button',name='Create administrator',exact=True).click()
        page.get_by_text('Administrator created. Sign in to continue.',exact=True).wait_for()
        sign_in(page,'first_operator','synthetic browser first password')
        page.get_by_role('button',name='Browse knowledge').click()
        page.get_by_role('heading',name='Knowledge library').wait_for()
        assert 'Synthetic protected evidence' not in page.locator('main').inner_text()
        assert list(Policy.load(path).users)==['first_operator']
        second=browser.new_page();second.goto(url+'/dashboard/')
        second.get_by_role('button',name='Sign in',exact=True).wait_for()
        assert second.get_by_label('One-time bootstrap token').count()==0
        browser.close()


def test_text_search_explicitly_clears_pending_browse_filter(service_store,tmp_path):
    from agentic_rag import store
    cfg,_=service_store
    with db.connect(cfg) as conn:
        for state in ['unreviewed','confirmed']:
            saved=store.save_claim(conn,cfg,title='Pending filter '+state,body='Synthetic pendingsentinel '+state,domain='alpha',dtype='memory',project='/projects/a',claim_kind='stated',evidence=[{'namespace':'pending-browser','source_id':state,'role':'user','quote':'Synthetic pendingsentinel '+state,'complete':True}])
            if state=='confirmed':store.review_claim(conn,saved.doc_id,state='confirmed',reason='Synthetic verified original')
    app,path=app_fixture(tmp_path,cfg);app.allowed_hosts.append('127.0.0.1')
    with server(app) as url,playwright.sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        try:
            page=browser.new_page();page.goto(url+'/dashboard/');sign_in(page,'alice','correct horse synthetic password')
            page.get_by_role('button',name='Browse knowledge').click()
            page.get_by_role('heading',name='Knowledge library').wait_for()
            pending=page.get_by_label('Pending reviews only');pending.check()
            page.get_by_role('button',name='Search',exact=True).click()
            page.get_by_role('button',name='Pending filter unreviewed',exact=True).wait_for()
            playwright.expect(page.get_by_role('button',name='Pending filter confirmed',exact=True)).to_have_count(0)
            page.get_by_label('Search your knowledge').fill('pendingsentinel')
            assert pending.is_disabled() and not pending.is_checked()
            assert page.get_by_text('Pending-only filtering applies to browsing. Text search clears this selection.',exact=True).is_visible()
            page.get_by_role('button',name='Search',exact=True).click()
            page.get_by_role('heading',name='Search results').wait_for(timeout=20000)
            page.get_by_role('button',name='Pending filter confirmed',exact=True).wait_for()
            page.get_by_label('Search your knowledge').fill('')
            assert pending.is_enabled();pending.check()
            page.get_by_role('button',name='Search',exact=True).click()
            page.get_by_role('heading',name='Memories',exact=True).wait_for()
            playwright.expect(page.get_by_role('button',name='Pending filter confirmed',exact=True)).to_have_count(0)
        finally:browser.close()
