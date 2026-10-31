"""RAG-063: real browser evidence drilldown, stale-decision refresh and source action."""
from dataclasses import replace
import os
from pathlib import Path

import pytest

playwright = pytest.importorskip('playwright.sync_api')
from agentic_rag import db, store
from tests.service.http_server import server
from tests.service.test_api import app_fixture
from tests.service.test_evidence_transports import evidence_store  # noqa: F401  (fixture)
from tests.browser.test_dashboard_browser import sign_in


def test_evidence_drilldown_conflict_refresh_and_source_decision(evidence_store, tmp_path):
    cfg, own, foreign, shared_key, own_key = evidence_store
    app, _ = app_fixture(tmp_path, replace(cfg, service_mode='server'))
    app.allowed_hosts.append('127.0.0.1')
    artifacts = Path(os.environ.get('RAG_BROWSER_ARTIFACT_DIR', tmp_path))
    artifacts.mkdir(parents=True, exist_ok=True)
    with server(app) as url, playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(url + '/dashboard/')
        sign_in(page, 'alice', 'correct horse synthetic password')
        page.get_by_role('button', name='Browse knowledge').click()
        page.get_by_role('button', name='own', exact=True).click()
        page.get_by_role('heading', name='Original sources & review').wait_for(timeout=20000)
        page.get_by_text('Independent verification: none', exact=False).wait_for(timeout=20000)
        main = page.locator('main')
        assert page.get_by_text('Shared synthetic statement', exact=True).count() == 1
        assert page.get_by_text('Own synthetic statement', exact=True).count() == 1
        text = main.inner_text()
        assert 'Event time' in text and 'User source event' in text
        # Opaque references only: no recorded host namespace/source event identifiers as navigation.
        assert main.locator('a').count() == 0
        assert 'event-own' not in page.locator('.source').first.inner_text()
        page.get_by_role('button', name='Decision history').click()
        page.get_by_text('attach', exact=False).first.wait_for(timeout=20000)
        page.screenshot(path=str(artifacts / 'evidence-drilldown.png'), full_page=True)
        # Someone else changes the evidence after this page was inspected.
        with db.connect(cfg) as conn:
            store.review_claim(conn, own, state='unreviewed', reason='concurrent legacy change')
        form = page.locator('form', has=page.get_by_role('heading', name='Review this claim'))
        form.get_by_label('Reason, grounded in the original sources').fill('Checked both quotes')
        form.get_by_role('button', name='Apply audited review').click()
        page.get_by_text('This evidence changed after you opened it', exact=False).wait_for(timeout=20000)
        with db.connect(cfg) as conn:
            assert conn.execute("SELECT review_state FROM claim_records WHERE document_id=%s", (own,)).fetchone()['review_state'] == 'unreviewed'
        page.get_by_role('button', name='Reload evidence').click()
        page.get_by_role('heading', name='Review this claim').wait_for(timeout=20000)
        form = page.locator('form', has=page.get_by_role('heading', name='Review this claim'))
        form.get_by_label('Reason, grounded in the original sources').fill('Checked both quotes again')
        form.get_by_role('button', name='Apply audited review').click()
        page.get_by_text('Review saved through the audited gateway.', exact=True).wait_for(timeout=20000)
        page.get_by_role('heading', name='Review this claim').wait_for(timeout=20000)
        own_card = page.locator('.source', has_text='Own synthetic statement')
        own_card.get_by_text('Change this source’s trust', exact=True).click()
        own_card.get_by_label('Reason for this source decision').fill('Withdrawn in synthetic test')
        own_card.get_by_role('button', name='Apply to this source').click()
        page.get_by_text('Source decision saved through the audited gateway.', exact=True).wait_for(timeout=20000)
        page.locator('.source', has_text='Own synthetic statement').get_by_text('Trust: removed', exact=True).wait_for(timeout=20000)
        shared_card = page.locator('.source', has_text='Shared synthetic statement')
        shared_card.get_by_text('Change this source’s trust', exact=True).click()
        shared_card.get_by_label('Reason for this source decision').fill('Shared, outside write scope')
        shared_card.get_by_role('button', name='Apply to this source').click()
        page.get_by_text('Nothing was changed.', exact=False).wait_for(timeout=20000)
        page.screenshot(path=str(artifacts / 'evidence-actions.png'), full_page=True)
        assert not errors, errors
        browser.close()
    with db.connect(cfg) as conn:
        states = {r['source_key']: r['state'] for r in conn.execute('SELECT source_key,state FROM knowledge_sources')}
        rows = conn.execute("SELECT concurrency FROM claim_history WHERE operation='review' ORDER BY revision").fetchall()
    assert states == {shared_key: 'active', own_key: 'removed'}
    assert [r['concurrency'] for r in rows] == ['legacy', 'strict']


def test_dashboard_can_page_through_all_recorded_decisions(evidence_store, tmp_path):
    """A finite first history page must not hide earlier decisions permanently."""
    cfg, own, *_ = evidence_store
    with db.connect(cfg) as conn:
        for n in range(22):
            store.review_claim(conn, own, state='unreviewed', reason='oldest retained decision' if n == 0 else f'Later decision {n}')
    app, _ = app_fixture(tmp_path, replace(cfg, service_mode='server'))
    app.allowed_hosts.append('127.0.0.1')
    with server(app) as url, playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url + '/dashboard/')
            sign_in(page, 'alice', 'correct horse synthetic password')
            page.get_by_role('button', name='Browse knowledge').click()
            page.get_by_role('button', name='own', exact=True).click()
            page.get_by_role('button', name='Decision history').click()
            page.get_by_text('Later decision 21', exact=True).wait_for(timeout=20000)
            assert page.get_by_text('oldest retained decision', exact=True).count() == 0
            page.get_by_role('button', name='Load earlier decisions').click(timeout=3000)
            page.get_by_text('oldest retained decision', exact=True).wait_for(timeout=20000)
            assert page.get_by_role('button', name='Load earlier decisions').count() == 0
        finally:
            browser.close()
