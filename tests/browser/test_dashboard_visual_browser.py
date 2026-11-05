"""RAG-108: sampled administrator views on desktop and narrow screens.

Synthetic data only. The audit is design-independent: text contrast (WCAG 1.4.3),
touch-target size on narrow screens (WCAG 2.5.8), visible keyboard focus with
sufficient contrast (WCAG 2.4.7/1.4.11), no horizontal page overflow and one
distinct active navigation entry. Screenshots and measured metrics are written to
``RAG_BROWSER_ARTIFACT_DIR`` (or the test's temporary directory).
"""
from dataclasses import replace
import json
import os
from pathlib import Path

import httpx
import pytest

playwright = pytest.importorskip('playwright.sync_api')
from agentic_rag import db, store
from tests.browser.test_dashboard_browser import sign_in
from tests.service.http_server import server
from tests.service.test_api import KEYS, app_fixture, headers
from tests.service.test_evidence_transports import evidence_store  # noqa: F401  (fixture)

DESKTOP = {'width': 1440, 'height': 1000}
MOBILE = {'width': 390, 'height': 844}

# Returns measurable presentation facts for the current view.
AUDIT = r"""
() => {
  const parse = value => {
    const m = /rgba?\(([^)]+)\)/.exec(value || '');
    if (!m) return null;
    const p = m[1].split(/[\s,\/]+/).filter(Boolean).map(Number);
    return {rgb: p.slice(0, 3), a: p.length > 3 ? p[3] : 1};
  };
  const blend = (top, under) => top.rgb.map((v, i) => v * top.a + under[i] * (1 - top.a));
  const background = node => {
    const layers = [];
    for (let n = node; n; n = n.parentElement) {
      const c = parse(getComputedStyle(n).backgroundColor);
      if (c && c.a > 0) { layers.push(c); if (c.a >= 1) break; }
    }
    let out = [255, 255, 255];
    for (const layer of layers.reverse()) out = blend(layer, out);
    return out;
  };
  const lum = rgb => {
    const [r, g, b] = rgb.map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
  const visible = node => {
    const s = getComputedStyle(node), r = node.getBoundingClientRect();
    return s.visibility !== 'hidden' && s.display !== 'none' && r.width > 0 && r.height > 0 && node.getClientRects().length > 0;
  };
  const name = node => node.tagName.toLowerCase() + (node.className && typeof node.className === 'string' ? '.' + node.className.trim().split(/\s+/).join('.') : '');
  const contrast = [];
  let checked = 0;
  for (const node of document.querySelectorAll('body *')) {
    if (!visible(node) || node.closest('[aria-hidden="true"],:disabled,.skip')) continue;
    const text = [...node.childNodes].filter(c => c.nodeType === 3).map(c => c.textContent).join('').trim();
    if (!text) continue;
    const s = getComputedStyle(node);
    const fg = parse(s.color);
    if (!fg) continue;
    let opacity = 1;
    for (let n = node; n; n = n.parentElement) opacity *= Number(getComputedStyle(n).opacity);
    const bg = background(node);
    const color = blend({rgb: fg.rgb, a: fg.a * opacity}, bg);
    const size = parseFloat(s.fontSize), bold = Number(s.fontWeight) >= 700;
    const required = size >= 24 || (size >= 18.66 && bold) ? 3 : 4.5;
    const value = ratio(color, bg);
    checked++;
    if (value + 1e-6 < required) contrast.push({element: name(node), text: text.slice(0, 40), ratio: Math.round(value * 100) / 100, required});
  }
  const targets = [];
  for (const node of document.querySelectorAll('button,select,a[href],input:not([type=checkbox]):not([type=hidden]),label.check,summary')) {
    if (!visible(node) || node.classList.contains('skip')) continue;
    if (node.tagName === 'A' && node.closest('p,small,li')) continue;  // inline text links are exempt
    const r = node.getBoundingClientRect();
    if (r.width < 24 || r.height < 24) targets.push({element: name(node), text: (node.textContent || node.name || '').trim().slice(0, 30), width: Math.round(r.width), height: Math.round(r.height)});
  }
  const current = [...document.querySelectorAll('nav [aria-current="page"]')];
  const others = [...document.querySelectorAll('nav button:not([aria-current="page"])')];
  return {
    checked_text_elements: checked,
    contrast_failures: contrast,
    small_targets: targets,
    horizontal_overflow: document.documentElement.scrollWidth > window.innerWidth,
    active_navigation: current.map(n => n.textContent.trim()),
    active_distinct: current.length === 1 && others.length > 0
      ? getComputedStyle(current[0]).backgroundColor !== getComputedStyle(others[0]).backgroundColor
      : null,
  };
}
"""

FOCUS = r"""
() => {
  const node = document.activeElement;
  if (!node || node === document.body) return null;
  const s = getComputedStyle(node);
  const parse = value => (/rgba?\(([^)]+)\)/.exec(value) || [, '0,0,0'])[1].split(/[\s,\/]+/).filter(Boolean).map(Number).slice(0, 3);
  const lum = rgb => { const [r, g, b] = rgb.map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
  let bg = [255, 255, 255];
  for (let n = node.parentElement; n; n = n.parentElement) {
    const m = /rgba?\(([^)]+)\)/.exec(getComputedStyle(n).backgroundColor);
    const p = m ? m[1].split(/[\s,\/]+/).filter(Boolean).map(Number) : [];
    if (p.length && (p.length < 4 || p[3] >= 1)) { bg = p.slice(0, 3); break; }
  }
  const [x, y] = [lum(parse(s.outlineColor)), lum(bg)].sort((a, b) => b - a);
  return {element: node.tagName.toLowerCase() + '.' + node.className, outline_style: s.outlineStyle,
          outline_width: parseFloat(s.outlineWidth), outline_contrast: Math.round((x + 0.05) / (y + 0.05) * 100) / 100};
}
"""


def _artifacts(tmp_path):
    path = Path(os.environ.get('RAG_BROWSER_ARTIFACT_DIR', tmp_path))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _capture(page, name, artifacts, metrics):
    for label, size in (('desktop', DESKTOP), ('mobile', MOBILE)):
        page.set_viewport_size(size)
        page.evaluate('window.scrollTo(0, 0)')
        page.wait_for_timeout(60)
        metrics[name + '-' + label] = page.evaluate(AUDIT)
        page.screenshot(path=str(artifacts / f'{name}-{label}.png'), full_page=True)
    page.set_viewport_size(DESKTOP)


def _focus(page, locator):
    """Reach an element by keyboard so :focus-visible applies as for a real user."""
    locator.focus()
    page.keyboard.press('Shift+Tab')
    page.keyboard.press('Tab')
    return page.evaluate(FOCUS)


def _nav(page, label):
    page.get_by_role('navigation').get_by_role('button', name=label).click()


def test_sampled_admin_views_are_readable_on_desktop_and_mobile(evidence_store, tmp_path, monkeypatch):
    from tests.service.test_reranker_settings import runtime
    runtime(monkeypatch)
    cfg, own, *_ = evidence_store
    with db.connect(cfg) as conn:
        for n, (title, state) in enumerate([('Deployment checklist for the central service', 'confirmed'),
                                            ('Backup retention decision', 'unreviewed'),
                                            ('Quarterly access review notes', 'unreviewed')]):
            saved = store.save_claim(conn, cfg, title=title, body=f'Synthetic visual fixture {n}: ' + title.lower() + '.',
                                     domain='alpha', dtype='memory', project='/projects/a', claim_kind='stated',
                                     evidence=[{'namespace': 'visual', 'source_id': f'v{n}', 'role': 'user',
                                                'quote': 'Synthetic visual quote ' + str(n), 'complete': True}])
            if state == 'confirmed':
                store.review_claim(conn, saved.doc_id, state='confirmed', reason='Synthetic visual review')
    app, _ = app_fixture(tmp_path, replace(cfg, service_mode='server'))
    app.allowed_hosts.append('127.0.0.1')
    artifacts = _artifacts(tmp_path)
    metrics, focus, keyboard = {}, {}, {}
    with server(app) as url, playwright.sync_playwright() as p:
        for _ in range(3):
            assert httpx.get(url + '/v1/capabilities', headers=headers(KEYS[0]), trust_env=False).status_code == 200
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport=DESKTOP)
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(url + '/dashboard/')
            page.get_by_role('button', name='Sign in', exact=True).wait_for()
            _capture(page, '01-login', artifacts, metrics)
            focus['login-input'] = _focus(page, page.get_by_label('Username', exact=True))
            focus['login-submit'] = _focus(page, page.get_by_role('button', name='Sign in', exact=True))
            page.get_by_label('Username', exact=True).fill('admin')
            page.get_by_label('Password', exact=True).fill('not the synthetic password')
            page.get_by_role('button', name='Sign in', exact=True).click()
            page.get_by_role('alert').wait_for()
            _capture(page, '02-login-error', artifacts, metrics)
            sign_in(page)
            _capture(page, '03-overview', artifacts, metrics)
            focus['nav-button'] = _focus(page, page.get_by_role('navigation').get_by_role('button', name='Overview'))
            focus['quiet-button'] = _focus(page, page.get_by_role('button', name='Browse knowledge'))
            page.get_by_role('button', name='Browse knowledge').click()
            page.get_by_role('heading', name='Knowledge library').wait_for()
            _capture(page, '04-knowledge', artifacts, metrics)
            focus['primary-button'] = _focus(page, page.get_by_role('button', name='Search', exact=True))
            page.get_by_role('button', name='own', exact=True).click()
            page.get_by_text('Independent verification: none', exact=False).wait_for(timeout=20000)
            page.get_by_role('heading', name='Review this claim').wait_for(timeout=20000)
            page.get_by_role('button', name='Decision history').click()
            page.get_by_text('attach', exact=False).first.wait_for(timeout=20000)
            _capture(page, '05-memory-evidence', artifacts, metrics)
            _nav(page, 'Request tracing')
            page.get_by_role('heading', name='Request tracing', exact=True).wait_for()
            _capture(page, '06-traces', artifacts, metrics)
            page.get_by_role('button', name='Inspect request', exact=False).first.click()
            page.get_by_role('heading', name='Request metadata', exact=True).wait_for()
            _capture(page, '07-trace-detail', artifacts, metrics)
            _nav(page, 'Clients & access')
            page.get_by_role('heading', name='Enrolled clients').wait_for()
            _capture(page, '08-clients', artifacts, metrics)
            page.get_by_role('row').filter(has_text='vm1 · alice').get_by_role('button', name='Manage').click()
            page.get_by_role('heading', name='API credentials').wait_for()
            _capture(page, '09-manage-client', artifacts, metrics)
            focus['danger-button'] = _focus(page, page.get_by_role('button', name='Revoke').first)
            _nav(page, 'Settings')
            page.get_by_role('heading', name='Current selection').wait_for()
            _capture(page, '10-settings', artifacts, metrics)
            _nav(page, 'Setup assistant')
            page.get_by_role('button', name='Upgrade an existing local store').click()
            page.get_by_role('button', name='Upgrade an existing local store', pressed=True).wait_for()
            page.get_by_text('Existing knowledge found.', exact=False).wait_for()
            _capture(page, '11-setup', artifacts, metrics)
            page.set_viewport_size(MOBILE)
            page.get_by_role('button', name='Toggle navigation').click()
            page.get_by_role('navigation').wait_for()
            metrics['12-mobile-navigation-mobile'] = page.evaluate(AUDIT)
            page.screenshot(path=str(artifacts / '12-mobile-navigation-mobile.png'))
            toggle = page.get_by_role('button', name='Toggle navigation')
            assert toggle.get_attribute('aria-expanded') == 'true'
            # Keyboard users close the opened navigation with Escape and return to its toggle.
            page.get_by_role('navigation').get_by_role('button', name='Overview').focus()
            page.keyboard.press('Escape')
            keyboard['escape_closes_navigation'] = (
                toggle.get_attribute('aria-expanded') == 'false'
                and page.evaluate("document.activeElement.getAttribute('aria-label')") == 'Toggle navigation'
                and not page.get_by_role('navigation').is_visible())
            assert not errors, errors
        finally:
            browser.close()
            # Written before the assertions so a failing (e.g. baseline) run still leaves evidence.
            (artifacts / 'visual-metrics.json').write_text(json.dumps(
                {'views': metrics, 'focus': focus, 'keyboard': keyboard}, indent=2, sort_keys=True) + '\n')
    failures = {name: m['contrast_failures'] for name, m in metrics.items() if m['contrast_failures']}
    assert not failures, json.dumps(failures, indent=1)[:4000]
    small = {name: m['small_targets'] for name, m in metrics.items() if name.endswith('-mobile') and m['small_targets']}
    assert not small, json.dumps(small, indent=1)[:4000]
    assert not [name for name, m in metrics.items() if m['horizontal_overflow']]
    for name, m in metrics.items():
        if not name.startswith(('01-', '02-')):
            assert len(m['active_navigation']) == 1 and m['active_distinct'], (name, m['active_navigation'])
    assert keyboard == {'escape_closes_navigation': True}, keyboard
    for name, f in focus.items():
        assert f and f['outline_style'] != 'none' and f['outline_width'] >= 2 and f['outline_contrast'] >= 3, (name, f)


@pytest.mark.parametrize('width', [390, 1440])
def test_long_permission_and_status_badges_remain_fully_readable(width):
    """Render the shipped badge/table components; hidden overflow loses scope text."""
    assets = Path(__file__).resolve().parents[2] / 'agentic_rag/service/dashboard_assets'
    script = (assets / 'app.js').read_text()
    helpers = script[script.index('function el('):script.index('function notice(')]
    helpers += script[script.index('function table('):script.index('function statusKind(')]
    values = [
        'alpha-domain-with-a-rather-long-name-for-testing',
        '/projects/customer-integration-platform-with-an-unusually-long-project-scope-name',
        'cancelled_by_operator_after_timeout_long_value',
    ]
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={'width': width, 'height': 844})
            page.set_content('<main class="content"><section class="card" id="knowledge"></section>'
                             '<section class="card" id="traces"></section></main>')
            page.add_style_tag(content=(assets / 'style.css').read_text())
            page.add_script_tag(content=helpers)
            page.evaluate('''values => {
                document.querySelector('#knowledge').append(el('div', {class:'detail-meta'},
                    badge(values[0]), badge(values[1])));
                document.querySelector('#traces').append(table(['Operation', 'Outcome'],
                    [['memory_search', badge(values[2], 'bad')]]));
            }''', values)
            badges = page.locator('.badge')
            assert badges.all_inner_texts() == values
            clipped = badges.evaluate_all('''nodes => nodes.filter(node =>
                node.scrollWidth > node.clientWidth + 1 || node.scrollHeight > node.clientHeight + 1
            ).map(node => ({text:node.textContent, visible:node.clientWidth, needed:node.scrollWidth}))''')
            assert not clipped, clipped
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        finally:
            browser.close()
