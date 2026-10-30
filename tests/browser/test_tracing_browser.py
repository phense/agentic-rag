"""The real UI filters, pages, opens details, exports and matches the real CLI."""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

import httpx
import pytest
playwright=pytest.importorskip('playwright.sync_api')

from tests.service.test_scope import service_store
from tests.service.test_api import app_fixture,headers,KEYS
from tests.service.http_server import server
from tests.browser.test_dashboard_browser import sign_in


def test_traces_browser_and_cli_use_same_scoped_projection(service_store,tmp_path):
    cfg,_=service_store;app,_=app_fixture(tmp_path,replace(cfg,service_mode='server'))
    app.allowed_hosts.append('127.0.0.1')
    with server(app) as url,playwright.sync_playwright() as p:
        identity=httpx.get(url+'/v1/capabilities',headers=headers(KEYS[0]),trust_env=False).headers['x-rag-request-id']
        token=tmp_path/'client.key';token.write_text(KEYS[0]);token.chmod(0o600)
        config=tmp_path/'client.toml'
        config.write_text('[service]\nmode="client"\nurl='+json.dumps(url)+'\ntoken_file='+json.dumps(str(token))+'\nspool_dir='+json.dumps(str(tmp_path/'spool'))+'\n')
        argv=[sys.executable,'-c','from agentic_rag.cli import main; raise SystemExit(main())','service','--config',str(config),'traces','--request-id',identity]
        cli=subprocess.run(argv,capture_output=True,text=True,timeout=15)
        assert cli.returncode==0,cli.stderr
        exported=json.loads(cli.stdout)
        assert exported['total']==1 and exported['rows'][0]['request_id']==identity
        detail=subprocess.run(argv[:-2]+['--detail',identity],capture_output=True,text=True,timeout=15)
        assert detail.returncode==0,detail.stderr
        assert json.loads(detail.stdout)['trace']==exported['rows'][0]
        for _ in range(12):assert httpx.get(url+'/v1/capabilities',headers=headers(KEYS[0]),trust_env=False).status_code==200
        browser=p.chromium.launch(headless=True)
        try:
            page=browser.new_page(viewport={'width':1440,'height':1080});errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(url+'/dashboard/');sign_in(page,'alice','correct horse synthetic password')
            page.get_by_role('navigation').get_by_role('button',name='Request tracing').click()
            page.get_by_role('heading',name='Request tracing',exact=True).wait_for()
            page.get_by_label('Request ID',exact=True).fill(identity)
            page.get_by_role('button',name='Filter traces',exact=True).click()
            page.get_by_text('1 visible',exact=True).wait_for()
            page.get_by_role('button',name='Inspect request '+identity,exact=True).click()
            page.get_by_role('heading',name='Request metadata',exact=True).wait_for()
            assert page.get_by_text(identity,exact=True).is_visible()
            assert page.get_by_text('capabilities',exact=True).is_visible()
            page.get_by_role('button',name='Back to request tracing').click()
            page.get_by_role('heading',name='Request tracing',exact=True).wait_for()
            page.get_by_label('Rows per page').select_option('10')
            page.get_by_role('button',name='Filter traces').click()
            page.get_by_role('button',name='Next traces',exact=True).click()
            page.get_by_role('button',name='Previous traces',exact=True).wait_for()
            page.screenshot(path=str(tmp_path/'traces.png'),full_page=True)
            page.get_by_role('button',name='Sign out',exact=True).click()
            page.get_by_role('button',name='Sign in',exact=True).wait_for()
            sign_in(page)
            page.get_by_role('navigation').get_by_role('button',name='Request tracing').click()
            page.get_by_role('heading',name='Request tracing',exact=True).wait_for()
            page.get_by_label('Request ID',exact=True).fill(identity)
            page.get_by_role('button',name='Filter traces').click()
            page.get_by_text('1 visible',exact=True).wait_for()
            with page.expect_download() as downloaded:page.get_by_role('button',name='Export this page').click()
            download=downloaded.value;destination=tmp_path/'traces-export.json';download.save_as(destination)
            assert json.loads(destination.read_text())['rows']==exported['rows']
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            assert not errors,errors
        finally:browser.close()
