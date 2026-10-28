"""Control installed Google Chrome via local CDP; never launch another browser on failure."""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import random
import re
import sys
import subprocess
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse
import uuid

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CDP = 'http://127.0.0.1:9222'
HOMES = {'taobao': 'https://www.taobao.com/', 'jd': 'https://www.jd.com/',
         'goofish': 'https://www.goofish.com/', '1688': 'https://www.1688.com/',
         'pinduoduo': 'https://mobile.yangkeduo.com/'}


def stamp():
    return datetime.now(timezone.utc).isoformat()


def verify_direct_mode(session):
    try:
        return '--no-proxy-server' in session.send('Browser.getBrowserCommandLine')['arguments']
    except Exception:
        # This CDP command needs --enable-automation, which shows a Chrome infobar.
        # Check the actual browser process without changing webpage features.
        if os.name != 'nt':
            raise RuntimeError('Cannot verify Chrome direct mode on this operating system.')
        processes = session.send('SystemInfo.getProcessInfo')['processInfo']
        pid = next((entry['id'] for entry in processes if entry['type'] == 'browser'), None)
        if not isinstance(pid, int) or pid <= 0:
            raise RuntimeError('Cannot identify the Chrome browser process.')
        command = "$OutputEncoding=[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); " + f"Get-CimInstance Win32_Process -Filter 'ProcessId={pid}' | Select-Object Name,CommandLine | ConvertTo-Json -Compress"
        result = subprocess.run(['powershell.exe', '-NoProfile', '-Command', command],
            capture_output=True, text=True, encoding='utf-8-sig', timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW, check=True)
        process = json.loads(result.stdout)
        if process.get('Name', '').lower() != 'chrome.exe' or not process.get('CommandLine'):
            raise RuntimeError('Cannot verify the Chrome browser process.')
        return bool(re.search(r'(?:^|\s)--no-proxy-server(?:\s|$)', process['CommandLine']))


def atomic_json(file: Path, data):
    file.parent.mkdir(parents=True, exist_ok=True)
    temporary = file.with_name(file.name + f'.{os.getpid()}.{uuid.uuid4().hex}.tmp')
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temporary, file)
    finally:
        temporary.unlink(missing_ok=True)


def load_json(file: Path, default):
    return json.loads(file.read_text(encoding='utf-8')) if file.exists() else default


class OutputLock:
    """Prevent overlapping Python/MCP calls from operating the same shopping session."""
    def __init__(self, out):
        Path(out).mkdir(parents=True, exist_ok=True)
        self.file = open(Path(out) / 'browser.lock', 'a+b')

    def __enter__(self):
        if os.name == 'nt':
            import msvcrt
            self.file.seek(0, 2)
            if not self.file.tell():
                self.file.write(b'0'); self.file.flush()
            self.file.seek(0)
            try:
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                self.file.close()
                raise RuntimeError('Another HuoYan browser operation is running; no new visit was started.') from error
        else:
            import fcntl
            fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return self

    def __exit__(self, *_):
        if os.name == 'nt':
            import msvcrt
            self.file.seek(0)
            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        self.file.close()


def product_identity(value):
    value = str(value).strip()
    url = urlparse(f'https://item.taobao.com/item.htm?id={value}' if value.isdigit() else value)
    if url.scheme not in ('http', 'https') or url.username or url.password or url.port:
        raise ValueError('Invalid product URL.')
    host, query, item_id, site = url.hostname, parse_qs(url.query), None, None
    if host in ('item.taobao.com', 'detail.tmall.com', 'detail.tmall.hk') and url.path == '/item.htm':
        site, item_id = 'taobao', query.get('id', [''])[0]
        canonical = f'https://{host}/item.htm?id={item_id}'
    elif host == 'item.jd.com' and re.fullmatch(r'/\d+\.html', url.path):
        site, item_id = 'jd', re.search(r'\d+', url.path)[0]
        canonical = f'https://{host}/{item_id}.html'
    elif host == 'detail.1688.com' and re.fullmatch(r'/offer/\d+\.html', url.path):
        site, item_id = '1688', re.search(r'\d+', url.path)[0]
        canonical = f'https://{host}/offer/{item_id}.html'
    elif host == 'www.goofish.com' and url.path == '/item':
        site, item_id = 'goofish', query.get('id', [''])[0]
        canonical = f'https://{host}/item?id={item_id}'
    elif host == 'mobile.yangkeduo.com' and url.path == '/goods.html':
        site, item_id = 'pinduoduo', query.get('goods_id', [''])[0]
        canonical = f'https://{host}/goods.html?goods_id={item_id}'
    if not site or not item_id or not item_id.isdigit():
        raise ValueError('Unsupported product URL or missing product ID.')
    return {'key': f'{site}:{item_id}', 'site': site, 'productId': item_id, 'url': canonical}


def dom_script(name):
    text = (ROOT / 'src/core' / name).read_text(encoding='utf-8')
    return '(' + text.split('// HUOYAN_DOM_BEGIN', 1)[1].split('// HUOYAN_DOM_END', 1)[0].strip() + ')'


def inspect(page, operation, **args):
    return page.evaluate(dom_script('itemPage.js'), {'operation': operation, **args})


class Controller:
    def __init__(self, args, browser=None):
        self.args = args
        from .state_store import state_directory
        self.out = state_directory(args)
        self.endpoint = args.get('cdp') or DEFAULT_CDP
        endpoint = urlparse(self.endpoint)
        if endpoint.hostname not in ('127.0.0.1', 'localhost', '::1') or endpoint.username or endpoint.password:
            raise ValueError('Chrome CDP must use a local loopback address without embedded credentials.')
        self.playwright = None
        self.browser = browser
        self.registry_file = self.out / 'product-tabs.json'
        self.registry = load_json(self.registry_file, {'version': 1, 'tabs': {}, 'products': {}})
        self.controls_file = self.out / 'page-controls.json'
        self.home_state_file = ROOT / 'data' / 'navigation-state.json'
        from .tab_focus import TabFocus
        self.focus=TabFocus(self)
        from .tab_budget import TabBudget
        self.tab_budget=TabBudget(self)

    def __enter__(self):
        try:
            if self.browser is None:
                previous_no_proxy = os.environ.get('NO_PROXY')
                os.environ['NO_PROXY'] = ','.join(filter(None, [previous_no_proxy, '127.0.0.1,localhost,::1']))
                try:
                    self.playwright = sync_playwright().start()
                finally:
                    if previous_no_proxy is None:
                        os.environ.pop('NO_PROXY', None)
                    else:
                        os.environ['NO_PROXY'] = previous_no_proxy
                self.browser = self.playwright.chromium.connect_over_cdp(self.endpoint, timeout=10000, no_defaults=True)
                session = self.browser.new_browser_cdp_session()
                try:
                    version = session.send('Browser.getVersion')['product']
                    if not re.match(r'^(?:Headless)?Chrome/', version):
                        raise RuntimeError('Expected Google Chrome; no alternate browser will be used.')
                    if not verify_direct_mode(session):
                        raise RuntimeError('Chrome direct mode is not enabled. Run npm run chrome:cdp.')
                finally:
                    session.detach()
            self.context = self.browser.contexts[0]
            return self
        except Exception:
            self.close()
            raise

    def close(self):
        self.focus.close()
        if self.playwright:
            if self.browser:
                self.browser.close()  # CDP disconnect; not Browser.close protocol command.
            self.playwright.stop()
            self.playwright = None

    def __exit__(self, *_):
        self.close()

    @property
    def pages(self):
        return [p for context in self.browser.contexts for p in context.pages]

    def pause(self, page, low=None, high=None):
        if low is None:
            low, high = self.args.get('delayMin', 12000), self.args.get('delayMax', 25000)
        if low < 0 or high < low:
            raise ValueError('Invalid pause range.')
        milliseconds = random.randint(int(low), int(high))
        remaining=milliseconds
        while remaining>0:
            if getattr(self, 'workflow_check', None):self.workflow_check()
            self.focus.check_wait(page)
            step=min(200,remaining);page.wait_for_timeout(step);remaining-=step
        self.focus.check_wait(page)
        return milliseconds

    def guard(self, page):
        if getattr(self, 'workflow_check', None):self.workflow_check()
        # Inaccessible or navigating pages fail closed, rather than assuming no verification.
        state = page.evaluate('''() => {
          const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>1&&r.height>1&&s.display!=='none'&&s.visibility!=='hidden'};
          const text=(document.body?.innerText||'').slice(0,8000);
          return {blocked:/安全验证|人机验证|滑块验证|验证失败|请登录|请拖动.*滑块/.test(text)
            || [...document.querySelectorAll('iframe[src*="captcha"],iframe[src*="baxia"],[class*="captcha"],[id*="captcha"],[class*="verify"],[id*="verify"]')].some(visible),
            networkError:(text.match(/ERR_[A-Z_]+/)||[])[0]||null};
        }''')
        if re.search(r'login\.taobao|login\.tmall|passport\.jd|risk_handler|login\.1688', page.url):
            state['blocked'] = True
        if state['blocked']:
            raise RuntimeError('Verification/login detected. Stopped without retry; handle it manually in the original tab.')
        if state['networkError']:
            raise RuntimeError(f"Network error: {state['networkError']}; no automatic refresh.")

    def tab_id(self, page):
        session = page.context.new_cdp_session(page)
        try:
            return session.send('Target.getTargetInfo')['targetInfo']['targetId']
        finally:
            session.detach()

    def sync_tabs(self):
        self.registry['tabs'] = {key: value for key, value in self.registry['tabs'].items() if value.get('endpoint') != self.endpoint}
        live = {}
        for page in self.pages:
            try:
                identity = product_identity(page.url)
            except ValueError:
                continue
            tab_id = self.tab_id(page)
            self.registry['tabs'][tab_id] = {'productKey': identity['key'], 'productId': identity['productId'], 'url': page.url, 'endpoint': self.endpoint}
            self.registry['products'].setdefault(identity['key'], {**identity, 'tabIds': []})
            live.setdefault(identity['key'], page)
        for product in self.registry['products'].values():
            product['tabIds'] = []
        for tab_id, tab in self.registry['tabs'].items():
            if tab['productKey'] in self.registry['products']:
                self.registry['products'][tab['productKey']]['tabIds'].append(tab_id)
        atomic_json(self.registry_file, self.registry)
        return live

    def snapshot(self, page):
        self.guard(page)
        self.focus.require(page)
        identity = product_identity(page.url)
        data = page.evaluate(dom_script('productSnapshotDom.js'))
        commerce=page.evaluate(dom_script('commerceEvidenceDom.js'),{'mode':'detail'})
        commerce.update(observedAt=stamp(),selectedSku=data.get('selectedSku',[]))
        product = {'productId': identity['productId'], 'productKey': identity['key'], 'url': page.url,
                   'tabId': self.tab_id(page), 'observedAt': stamp(), **data,'commerce':commerce,
                   'note': 'Visible page text only; missing fields are unverified. Prices depend on SKU and offers.'}
        self.sync_tabs()
        self.registry['products'][identity['key']]['cache'] = product
        self.registry['products'][identity['key']]['url'] = page.url
        atomic_json(self.registry_file, self.registry)
        return product

    def product_page(self, item, fresh=False, require_page=False,from_page=None):
        identity = product_identity(item)
        live = self.sync_tabs()
        page = live.get(identity['key'])
        previous = self.registry['products'].get(identity['key'])
        if page:
            if from_page is not None:
                self.focus.require(from_page);self.focus.allow(from_page,'open_product')
                self.focus.bind(page,origin=from_page,bring=True)
            else:self.focus.require(page)
            self.guard(page)
            if fresh:
                self.pause(page); self.guard(page);self.focus.require(page)
                if product_identity(page.url)['key'] != identity['key']:
                    raise RuntimeError('Product changed while waiting; no refresh was performed.')
                self.focus.begin(page);page.reload(wait_until='domcontentloaded')
                self.pause(page, 2500, 4500); self.guard(page)
                self.focus.require(page);self.focus.pending=None
            return page, 'refreshed-tab' if fresh else 'existing-tab'
        if previous and not fresh:
            if require_page:
                raise RuntimeError('Product tab is closed; use cache or explicitly request fresh to reopen.')
            if previous.get('cache'):
                return previous['cache'], 'cache'
            raise RuntimeError('Closed product has no snapshot; fresh is required to reopen.')
        page = None
        link = None
        active=self.focus.load().get('activeTabId')
        candidates=[from_page] if from_page is not None else [p for p in self.pages if self.tab_id(p)==active]
        for candidate in candidates:
            if not self.site_matches(candidate, 'taobao') and not (urlparse(candidate.url).hostname or '').endswith('.tmall.com'):
                continue
            self.guard(candidate)
            self.focus.require(candidate);self.focus.allow(candidate,'open_product')
            links=candidate.locator('a[href]')
            for item in links.evaluate_all('els=>els.map((e,index)=>({index,href:e.href,visible:e.getBoundingClientRect().width>1&&e.getBoundingClientRect().height>1&&getComputedStyle(e).visibility!=="hidden"}))'):
                if not item['visible'] or not item['href'].startswith('https://'):continue
                try:
                    if product_identity(item['href'])['key'] == identity['key']:
                        page,link=candidate,links.nth(item['index']);break
                except ValueError:continue
            if link:break
        if link is None:
            raise RuntimeError('No visible in-page link to this product. Search/list controls first; direct product navigation is forbidden.')
        self.focus.require(page);self.focus.prepare_action(page);self.pause(page);self.guard(page);self.focus.require(page)
        if product_identity(link.evaluate('e=>e.href'))['key'] != identity['key'] or not link.is_visible():
            raise RuntimeError('Product link changed; no click performed.')
        before=set(self.pages)
        source_url=page.url
        from .tab_focus import page_type
        source_type=page_type(page)
        self.tab_budget.before_popup(page,link)
        self.focus.begin(page)
        link.click(timeout=8000)
        self.pause(page, 2500, 4500); self.guard(page)
        for opened in self.pages:
            if opened not in before:self.guard(opened)
        selected=None
        for _ in range(50):
            selected=self.sync_tabs().get(identity['key'])
            if selected:break
            page.wait_for_timeout(100)
        if selected is None:raise RuntimeError('Click did not reach the requested product; no direct URL fallback.')
        selected.wait_for_load_state('domcontentloaded',timeout=8000)
        self.guard(selected)
        if selected is page:
            self.focus.require(selected)
            self.focus.remember_same_tab(selected,source_url,source_type)
        else:self.focus.adopt_popup(page,selected)
        self.focus.pending=None
        return selected, 'clicked-link'

    def product(self):
        page, source = self.product_page(self.args['item'], self.args.get('fresh', False))
        if source == 'cache':
            return {'source': source, 'stale': True, 'product': page,'availableActions':[],
                    'note':'Cached product only; no cached control IDs are executable. Activate an existing live tab to discover options.'}
        from .shopping_research import read, publish
        state=publish(self,read(self,page))
        return {'source': source, 'stale': False, 'refreshed': source == 'refreshed-tab', 'product': state['product'],
                'detail':state['detail'],'state':state}

    def input(self, page, shop=False):
        selectors = ['input[name="keyword"]', 'input[name="keywords"]'] if shop else [
            '#q', '#key', 'input[name="q"]', 'input[name="keyword"]', 'input[name="keywords"]',
            'input[type="search"]', 'input[placeholder*="搜索"]', 'input[placeholder*="搜宝贝"]']
        for selector in selectors:
            for element in page.locator(selector).all():
                if element.is_visible() and element.is_editable():
                    return element
        return None

    def site_matches(self, page, site):
        host = urlparse(page.url).hostname or ''
        domains = {'taobao': 'taobao.com', 'jd': 'jd.com', 'goofish': 'goofish.com', '1688': '1688.com', 'pinduoduo': 'yangkeduo.com'}
        return host == domains.get(site) or host.endswith('.' + domains.get(site, '.invalid'))

    def search(self):
        site, keyword = self.args.get('site', 'taobao'), self.args.get('keyword', '').strip()
        if site not in HOMES or not keyword:
            raise ValueError('Search needs a supported site and a keyword.')
        target = urlparse(self.args['startUrl']) if self.args.get('startUrl') else None
        if target and (target.scheme != 'https' or target.username or target.password):
            raise ValueError('Search entry must be an HTTPS URL without embedded credentials.')
        shop = bool(target and target.path == '/search.htm')
        marker = f'huoyan-search:v1:{site}:' + (f'{target.netloc}{target.path}' if target else 'global')
        candidates = []
        for page in self.pages:
            if not self.site_matches(page, site):
                continue
            current = urlparse(page.url)
            if target and (current.netloc, current.path) != (target.netloc, target.path):
                continue
            if not target and site == 'taobao' and current.hostname not in ('www.taobao.com', 's.taobao.com'):
                continue
            try:
                product_identity(page.url)
                continue  # Product pages must never be repurposed as search tabs.
            except ValueError:
                pass
            if self.input(page, shop):
                candidates.append(page)
        page = next((p for p in candidates if p.evaluate('window.name') == marker), None)
        page = page or (candidates[-1] if candidates else None)
        reused = page is not None
        if page is None:
            home_state = self.home_state_file
            if site != 'taobao' or (target and self.args['startUrl'] != HOMES['taobao']) or any(self.site_matches(p,'taobao') or (urlparse(p.url).hostname or '').endswith('.tmall.com') for p in self.pages) or load_json(home_state,{}).get('homeOpened'):
                raise RuntimeError('No reusable search form. Use visible page controls/back; only the first Taobao homepage entry may use direct navigation.')
            atomic_json(home_state,{'homeOpened':True,'openedAt':stamp()})
            page = next((p for p in self.pages if p.url == 'about:blank'), None) or self.context.new_page()
            page.goto(HOMES['taobao'], wait_until='domcontentloaded')
            self.pause(page, 1800, 3500)
        self.guard(page)
        if reused:self.focus.require(page)
        else:self.focus.activate(page)
        self.focus.allow(page,'search')
        self.focus.prepare_action(page)
        page.evaluate('(name)=>{window.name=name}', marker)
        if urlparse(page.url).path in ('/', '/index.html', '/index.htm'):
            width, height = page.evaluate('[innerWidth,innerHeight]')
            x, y = width // 2, height // 2
            for direction in random.sample(['up', 'down', 'left', 'right'], 4) + random.choices(['up', 'down', 'left', 'right'], k=random.randint(0, 3)):
                self.guard(page);self.focus.require(page)
                x = min(width - 30, max(30, x + (random.randint(60, 240) if direction == 'right' else -random.randint(60, 240) if direction == 'left' else 0)))
                y = min(height - 30, max(30, y + (random.randint(40, 160) if direction == 'down' else -random.randint(40, 160) if direction == 'up' else 0)))
                page.mouse.move(x, y, steps=random.randint(10, 20)); self.pause(page, 350, 1200)
        self.pause(page); self.guard(page);self.focus.require(page)
        input_element = self.input(page, shop)
        if input_element is None:
            raise RuntimeError('No search box found. No direct search URL fallback or retry.')
        self.focus.require(page)
        input_element.fill(keyword)
        input_element.evaluate("el=>{if(el.form)el.form.target='_self'}")
        buttons = input_element.locator('xpath=ancestor::form[1]').locator('button[type="submit"],input[type="submit"],button:not([type])')
        button = next((b for b in buttons.all() if b.is_visible() and b.is_enabled()), None)
        if button is None:
            button = next((b for b in page.get_by_role('button', name='搜索', exact=True).all() if b.is_visible() and b.is_enabled()), None)
        self.focus.require(page);self.focus.begin(page)
        if button:
            button.evaluate("el=>el.removeAttribute('formtarget')"); button.click()
        else:
            input_element.press('Enter')
        self.pause(page, 2500, 4500); self.guard(page);self.focus.require(page);self.focus.pending=None
        page.evaluate('(name)=>{window.name=name}', marker)
        return page, reused

    def save_controls(self,data):
        atomic_json(self.controls_file,data)
        if data.get('controls') and not load_json(self.home_state_file,{}).get('homeOpened'):
            atomic_json(self.home_state_file,{'homeOpened':True,'observedExistingSite':True,'openedAt':stamp()})

    def load_controls(self):
        data=load_json(self.controls_file,{})
        if data.get('endpoint')!=self.endpoint:raise RuntimeError('Controls belong to another browser; list again.')
        return data

    def page_action(self):
        from .page_buttons import list_buttons,click_button
        action=self.args.get('action')
        if action=='list':return list_buttons(self,product_identity)
        if action=='click':return click_button(self,product_identity)
        if action=='back':
            page=next((p for p in self.pages if self.tab_id(p)==self.args.get('tabId')),None)
            if page is None:raise RuntimeError('Unknown tabId; list controls first.')
            if not self.site_matches(page,'taobao') and not (urlparse(page.url).hostname or '').endswith('.tmall.com'):
                raise RuntimeError('Tab is no longer on a supported shopping page; stopped.')
            self.guard(page);self.focus.require(page);self.pause(page);self.guard(page);self.focus.require(page)
            session=page.context.new_cdp_session(page)
            try:history=session.send('Page.getNavigationHistory')
            finally:session.detach()
            if history['currentIndex']<1:raise RuntimeError('No previous page.')
            previous=history['entries'][history['currentIndex']-1]['url']
            host=urlparse(previous).hostname or ''
            if not any(host==d or host.endswith('.'+d) for d in ('taobao.com','tmall.com')):raise RuntimeError('Previous page is outside supported shopping sites; stopped.')
            self.focus.begin(page);page.go_back(wait_until='commit',timeout=8000)
            page.wait_for_function("document.readyState==='interactive'||document.readyState==='complete'",timeout=8000)
            self.guard(page);self.focus.require(page);self.focus.pending=None;self.sync_tabs()
            return {'action':'back','tabId':self.tab_id(page)}
        raise ValueError('Action must be list, click or back.')

    def scroll(self, page):
        self.focus.require(page)
        count = self.args.get('scroll', 'auto')
        count = random.randint(2, 5) if count == 'auto' else max(0, int(count))
        if count:self.focus.prepare_action(page)
        for _ in range(count):
            self.guard(page);self.focus.require(page)
            top, height, viewport = page.evaluate('[scrollY,document.documentElement.scrollHeight,innerHeight]')
            if top >= height - viewport - 2:
                if top > 2:
                    page.evaluate('(dy)=>scrollBy(0,-dy)', int(viewport * random.uniform(.2, .5)))
                break
            page.evaluate('(dy)=>scrollBy(0,dy)', int(viewport * random.uniform(.5, 2.5)))
            self.pause(page, 350, 800)
        self.guard(page)

    def collect(self):
        if self.args.get('openSearch') or self.args.get('startUrl'):
            page, reused = self.search()
        else:
            active=self.focus.load().get('activeTabId')
            candidates = [p for p in self.pages if self.tab_id(p)==active and (self.args.get('site') in (None, 'auto') or self.site_matches(p, self.args['site']))]
            page = next((p for p in reversed(candidates) if p.url.startswith('https://')), None)
            if page is None:
                raise RuntimeError('NEEDS_TAB_SWITCH: activate an existing list page before collecting.')
            reused = True
        self.focus.require(page)
        from .tab_focus import page_type
        if page_type(page) not in ('search','shop','home'):raise RuntimeError('WRONG_PAGE_TYPE: switch to a list page before collecting products.')
        items, seen = [], set()
        for index in range(max(1, int(self.args.get('pages', 1)))):
            self.guard(page); self.scroll(page)
            raw = page.evaluate('''() => [...document.querySelectorAll('a[href]')].map(a=>{
              const rect=a.getBoundingClientRect(); if(rect.width<1||rect.height<1)return null;
              const card=a.closest('[data-product-card],[class*="doubleCardWrapper"],[class*="cardItem"],[class*="item--"],li')||a;
              const text=(card.innerText||'').trim();
              const image=card.querySelector('img');
              return {url:a.href,title:(a.title||image?.alt||text).replace(/\\s+/g,' ').slice(0,200),
                price:(text.match(/(?:¥|￥)\\s*(\\d+(?:\\.\\d+)?)/)||[])[1]||null,image_url:image?.currentSrc||image?.src||null};
            }).filter(Boolean)''')
            for item in raw:
                try:
                    identity = product_identity(item['url'])
                except ValueError:
                    continue
                if identity['key'] in seen or not item['title']:
                    continue
                seen.add(identity['key'])
                items.append({**item, 'item_id': identity['productId'], 'site': identity['site'], 'keyword': self.args.get('keyword', ''), 'extract_time': stamp()})
                if len(items) >= int(self.args.get('max', 50)):
                    break
            if index + 1 >= int(self.args.get('pages', 1)) or len(items) >= int(self.args.get('max', 50)):
                break
            next_button = next((b for b in page.get_by_text('下一页', exact=True).all() if b.is_visible() and b.is_enabled()), None)
            if next_button is None:
                break
            self.pause(page); self.guard(page);self.focus.require(page);self.focus.begin(page); next_button.click(); self.pause(page); self.guard(page);self.focus.require(page);self.focus.pending=None
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', self.args.get('keyword', 'items'))[:80]
        prefix = f"{self.args.get('site','auto')}_{name}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        raw_file, report = self.out / 'raw' / (prefix + '.jsonl'), self.out / 'reports' / (prefix + '.md')
        raw_file.parent.mkdir(parents=True, exist_ok=True); report.parent.mkdir(parents=True, exist_ok=True)
        raw_file.write_text(''.join(json.dumps(item, ensure_ascii=False) + '\n' for item in items), encoding='utf-8')
        report.write_text('# 商品搜索结果\n\n' + '\n'.join(f"- [{item['title'].replace(']', '')}]({item['url']})：{item['price'] or '价格未识别'}" for item in items), encoding='utf-8')
        return {'site': self.args.get('site'), 'page': page.url, 'itemCount': len(items), 'items': items, 'reused': reused,
                'outputs': {'jsonl': str(raw_file), 'markdown': str(report)}, 'warning': None if items else 'No product cards recognized; no automatic retry.'}

    def sku_images(self):
        from PIL import Image, ImageDraw, ImageFont, ImageOps
        identity = product_identity(self.args['item'])
        if identity['site'] != 'taobao':
            raise ValueError('SKU selection currently supports Taobao/Tmall only.')
        page, _ = self.product_page(self.args['item'], self.args.get('fresh', False), require_page=True)
        self.guard(page)
        groups, sku = inspect(page, 'groups'), self.args.get('sku', [])
        if len(groups) != len(sku) or any(value not in group['options'] for value, group in zip(sku, groups)):
            raise ValueError('Supply exact option text for each selectable SKU dimension; no selection was made.')
        self.focus.require(page)
        if not inspect(page, 'single-skus').get('ok'):
            raise RuntimeError('A fixed SKU is unavailable.')
        self.focus.prepare_action(page)
        initial_scroll = page.evaluate('scrollY')
        for index, value in enumerate(sku):
            self.guard(page);self.focus.require(page)
            if not inspect(page, 'click-sku', groupIndex=index, value=value).get('clicked'):
                raise RuntimeError('SKU selection failed; no further clicks were made.')
            self.pause(page, 500, 1200)
        def verify():
            self.guard(page)
            self.focus.require(page)
            if product_identity(page.url)['key'] != identity['key'] or not inspect(page, 'all-selected'):
                raise RuntimeError('Product or SKU changed; no collage returned.')
            if not all(inspect(page, 'selected-sku', groupIndex=i, value=value) for i, value in enumerate(sku)):
                raise RuntimeError('Selected SKU was not confirmed.')
        verify()
        images, sources, hashes, urls = [], [], set(), set()
        limit = max(1, min(12, int(self.args.get('maxImages', 8))))
        requested_sources=self.args.get('imageSources',['gallery','description'])
        if not isinstance(requested_sources,list) or not requested_sources or set(requested_sources)-{'gallery','description','review'}:
            raise ValueError('imageSources must contain gallery, description or review.')
        def capture(locator,source='gallery'):
            verify()
            if source not in requested_sources:return
            if len(images) >= limit or not locator.is_visible():
                return
            locator.scroll_into_view_if_needed()
            locator.evaluate('img=>Promise.race([img.decode().catch(()=>{}),new Promise(r=>setTimeout(r,5000))])')
            info = locator.evaluate('img=>({src:img.currentSrc||img.src,width:img.naturalWidth,height:img.naturalHeight})')
            if info['width'] < 120 or info['height'] < 120 or info['src'] in urls:
                return
            verify()
            png = locator.screenshot(type='png', timeout=5000)
            digest = hashlib.sha256(png).hexdigest()
            if digest in hashes:
                return
            hashes.add(digest); urls.add(info['src']); images.append(Image.open(io.BytesIO(png)).convert('RGB'))
            sources.append({'index': len(images), 'url': info['src'], 'originalWidth': info['width'], 'originalHeight': info['height'],
                            'capturedWidth':images[-1].width,'capturedHeight':images[-1].height,
                            'source':source,'clarity':'thumbnail-or-small-capture' if min(info['width'],info['height'],images[-1].width,images[-1].height)<600 else 'rendered-image',
                            'skuAssociation':'unverified','observedAt':stamp()})
        try:
            main = page.locator('[data-product-main-image],#J_ImgBooth,.tb-booth img,[class*="mainPic"] img,img[class*="mainPic--"],[class*="MainPic"] img')
            for locator in main.all():
                capture(locator)
            for thumb in page.locator('[data-product-thumbnail],#J_UlThumb li,[class*="thumbnail"] button,[class*="Thumbnail"] button,[class*="thumbnail"] img,[class*="Thumbnail"] img').all()[:16] if 'gallery' in requested_sources else []:
                if len(images) >= limit:
                    break
                if thumb.is_visible():
                    verify(); thumb.click(timeout=5000); self.pause(page, 500, 1200)
                    for locator in main.all():
                        capture(locator)
            for locator in page.locator('[data-product-image],#description img,#J_DivItemDesc img,.desc-root img,.descV8-container img').all()[:40]:
                capture(locator,'description')
            for locator in page.locator('[data-review-image],[class*="Comment--"] [class*="album--"] img').all()[:20]:
                capture(locator,'review')
        finally:
            if self.focus.info()['bindingValid']:page.evaluate('(top)=>scrollTo(0,top)', initial_scroll)
        verify()
        if not images:
            raise RuntimeError('No loaded product images found; no collage fabricated.')
        product = self.snapshot(page)
        columns = min(2, len(images)); width, height = columns * 600, 90 + ((len(images) + columns - 1) // columns) * 660
        canvas = Image.new('RGB', (width, height), 'white'); draw = ImageDraw.Draw(canvas)
        font_path = Path('C:/Windows/Fonts/msyh.ttc')
        font = ImageFont.truetype(str(font_path), 22) if font_path.exists() else ImageFont.load_default()
        draw.text((20, 16), (product['title'] + ' | ' + ' / '.join(sku))[:80], fill='black', font=font)
        draw.text((20, 50), '商品图片可能为不同规格共用，请结合规格信息判断。', fill='black', font=font)
        for index, image in enumerate(images):
            image = ImageOps.contain(image, (560, 600))
            left, top = (index % columns) * 600, 90 + (index // columns) * 660
            canvas.paste(image, (left + (600 - image.width) // 2, top + (600 - image.height) // 2))
            draw.text((left + 20, top + 622), f'#{index + 1}', fill='black', font=font)
        file = self.out / 'images' / 'collages' / f"{identity['productId']}-{uuid.uuid4().hex}.png"
        file.parent.mkdir(parents=True, exist_ok=True); canvas.save(file)
        result = {'productId': identity['productId'], 'tabId': product['tabId'], 'url': page.url, 'sku': sku,
                  'imageCount': len(images), 'sources': sources, 'file': str(file), 'width': width, 'height': height,
                  'observedAt': stamp(), 'warning': 'Rendered product images may be shared across variants.'}
        atomic_json(file.with_suffix('.json'), result)
        from .shopping_research import read, publish
        state=publish(self,read(self,page))
        return {**result, 'product': product, 'detail':state['detail'],'state':state,
                'imageBase64': base64.b64encode(file.read_bytes()).decode('ascii')}


def run(command, args):
    from .state_store import state_directory
    out = state_directory(args)
    with OutputLock(out):
        from .favorites import OFFLINE as FAVORITE_OFFLINE, offline as favorite_offline
        if command == 'shopping' and args.get('operation') in FAVORITE_OFFLINE:
            return favorite_offline(Controller(args))
        if command == 'shopping' and args.get('operation') == 'open_local_favorite' and not args.get('fresh', False):
            from .favorites import local_record
            # A failed browser connection must still return a usable saved favorite.
            saved_favorite = local_record(Controller(args))
        else:
            saved_favorite = None
        if command == 'shopping' and args.get('operation') == 'preview_merchant_wording':
            from .merchant_wording import preview
            return preview(args)
        if command == 'shopping' and args.get('operation') == 'workflow_status':
            from .workflows import status
            return status(Controller(args))
        if command == 'shopping' and args.get('operation') in ('summarize_invoice_terms', 'finish_merchant_inquiry'):
            from .merchant_chat import run as chat_run
            return chat_run(Controller(args))
        if command == 'shopping' and args.get('operation') in ('compare_candidates', 'research_progress'):
            from .shopping_research import offline
            return offline(Controller(args))
        if command == 'product' and not args.get('fresh'):
            identity = product_identity(args['item'])
            cache = load_json(out / 'product-tabs.json', {'products': {}})['products'].get(identity['key'], {}).get('cache')
        else:
            cache = None
        try:
            controller = Controller(args).__enter__()
        except Exception:
            if saved_favorite:
                return {'scope':'local','confirmed':True,'source':'local-cache','favorite':saved_favorite,'cached':True,
                        'stale':True,'browserUnavailable':True,'pageOpened':False}
            if cache:
                return {'source': 'cache', 'stale': True, 'browserUnavailable': True, 'product': cache,
                        'availableActions':[],'note':'Browser unavailable; cached data has no executable controls.'}
            raise
        try:
            if command == 'status':
                return {'browser': 'chrome', 'controller': 'python-playwright', 'directVerified': True, 'pages': len(controller.pages)}
            if command == 'product':
                return controller.product()
            if command == 'sku-images':
                return controller.sku_images()
            if command == 'page-action':
                return controller.page_action()
            if command == 'shopping':
                from .shopping_research import run as shopping_run
                return shopping_run(controller)
            if command in ('collect', 'search'):
                if command == 'search':
                    args['openSearch'] = True
                return controller.collect()
            raise ValueError('Unknown command.')
        finally:
            controller.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['status', 'search', 'collect', 'product', 'sku-images', 'dispatch'])
    parser.add_argument('--site', default='taobao'); parser.add_argument('--keyword', default='')
    parser.add_argument('--item'); parser.add_argument('--sku', nargs='*', default=[])
    parser.add_argument('--fresh', action='store_true'); parser.add_argument('--max-images', type=int, default=8)
    parser.add_argument('--max', type=int, default=5); parser.add_argument('--pages', type=int, default=1)
    parser.add_argument('--scroll', default='auto'); parser.add_argument('--out', default='data')
    parser.add_argument('--cdp', default=DEFAULT_CDP); parser.add_argument('--start-url')
    parser.add_argument('--open-search', action='store_true')
    parser.add_argument('--delay-min', type=int, default=12000); parser.add_argument('--delay-max', type=int, default=25000)
    parsed = parser.parse_args()
    args = vars(parsed).copy(); command = args.pop('command')
    args['maxImages'] = args.pop('max_images'); args['delayMin'] = args.pop('delay_min'); args['delayMax'] = args.pop('delay_max')
    args['startUrl'] = args.pop('start_url')
    args['openSearch'] = args.pop('open_search')
    try:
        if command == 'dispatch':
            request = json.load(sys.stdin); command, args = request['command'], request.get('args', {})
        result = run(command, args)
        if parsed.command != 'dispatch':
            result.pop('imageBase64', None)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False))
        sys.exit(1)


if __name__ == '__main__':
    main()
