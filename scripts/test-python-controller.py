"""Isolated Chrome integration checks; all shopping traffic is fulfilled locally."""
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from playwright.sync_api import sync_playwright
from PIL import Image
from python.huoyan_browser import Controller, product_identity

CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
HTML = '''<!doctype html><title>PLA挂钩</title><body>
<form target="_blank" onsubmit="event.preventDefault();window.searches++;history.pushState({},'', '/search?q='+encodeURIComponent(this.q.value));"><input name="q"><button type="submit">搜索</button></form>
<a data-product-card href="https://item.taobao.com/item.htm?id=123&spm=tracking">PLA挂钩 ¥12.50 1000+人付款</a>
<div data-product-description>PLA 1.75mm 0.5kg/1kg</div><div data-product-price>PRICE_VALUE</div>
<div class="skuItem"><span class="label">重量</span><li onclick="pick(this)">0.5kg</li><li onclick="pick(this)">1kg</li><li class="disabled">缺货</li></div>
<img data-product-main-image width="200" height="200"><button data-product-thumbnail onclick="main.src=pics[2]">图2</button><button data-product-thumbnail onclick="main.src=pics[3]">图3</button><img data-product-image width="200" height="200"><button onclick="window.cart++">加入购物车</button>
<script>window.searches=0;window.cart=0;window.pics=['red','green','blue','yellow'].map(color=>{const c=document.createElement('canvas');c.width=c.height=200;const x=c.getContext('2d');x.fillStyle=color;x.fillRect(0,0,200,200);return c.toDataURL()});window.main=document.querySelector('[data-product-main-image]');main.src=pics[0];document.querySelector('[data-product-image]').src=pics[2];window.pick=el=>{document.querySelectorAll('.skuItem li').forEach(x=>x.classList.remove('selected'));el.classList.add('selected');main.src=pics[el.innerText==='1kg'?1:0]};</script>'''


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class PythonControllerTests(unittest.TestCase):
    def test_full_flow_and_bridge(self):
        with tempfile.TemporaryDirectory(prefix='huoyan-py-') as folder, sync_playwright() as playwright:
            port = free_port()
            context = playwright.chromium.launch_persistent_context(str(Path(folder) / 'profile'), executable_path=CHROME,
                headless=True, ignore_default_args=['--enable-automation'], args=['--no-proxy-server', f'--remote-debugging-port={port}'])
            try:
                price = ['12.50']
                context.route('**/*', lambda route: route.fulfill(content_type='text/html; charset=utf-8', body=HTML.replace('PRICE_VALUE', price[0])))
                out = str(Path(folder) / 'data')
                endpoint = f'http://127.0.0.1:{port}'
                bridge = subprocess.run(['node', '-e', "require('./src/core/pythonController').runPython('status',JSON.parse(process.argv[1])).then(r=>console.log(JSON.stringify(r))).catch(e=>{console.error(e.message);process.exitCode=1})", json.dumps({'out': out, 'cdp': endpoint})],
                    cwd=ROOT, capture_output=True, text=True, timeout=30)
                self.assertEqual(bridge.returncode, 0, bridge.stderr)
                self.assertTrue(json.loads(bridge.stdout)['directVerified'])
                self.assertEqual(len(context.pages), 1)
                args = {'out': out, 'cdp': endpoint, 'site': 'taobao', 'keyword': '钩子', 'openSearch': True,
                        'max': 5, 'pages': 1, 'scroll': 0, 'delayMin': 0, 'delayMax': 0}
                with Controller(args, context.browser) as controller:
                    controller.home_state_file = Path(folder)/'navigation-state.json'
                    controller.pause = lambda *a, **kw: 0
                    first = controller.collect()
                    self.assertEqual(first['itemCount'], 1)
                    self.assertEqual(len(context.pages), 1)
                    original = context.pages[0]
                    from python.page_buttons import list_buttons,click_button
                    listed=list_buttons(controller,product_identity)['controls']
                    self.assertTrue(any(c['action']=='search' for c in listed))
                    self.assertTrue(any(c['action']=='open_product' for c in listed))
                    self.assertFalse(any('购物车' in c['label'] for c in listed))
                    missing_before=len(context.pages)
                    with self.assertRaisesRegex(RuntimeError,'direct product navigation'):
                        controller.product_page('999',True)
                    self.assertEqual(len(context.pages),missing_before)
                    record=next(c for c in listed if c['action']=='search')
                    controller.args.update({'controlId':record['controlId'],'keyword':'按钮搜索'})
                    clicked=click_button(controller,product_identity)
                    self.assertTrue(clicked['clicked'])
                    with self.assertRaisesRegex(RuntimeError,'page changed'):
                        click_button(controller,product_identity)
                    original.evaluate("()=>{const b=document.createElement('button');b.textContent='下一页';b.onclick=()=>history.pushState({},'', '/search?page=2');document.body.append(b)}")
                    original.evaluate("()=>{const s=document.createElement('div');s.setAttribute('role','tab');s.textContent='销量';s.onclick=()=>s.setAttribute('aria-selected','true');document.body.append(s)}")
                    listed=list_buttons(controller,product_identity)['controls']
                    controller.args['controlId']=next(c['controlId'] for c in listed if c['action']=='sort')
                    self.assertEqual(click_button(controller,product_identity)['action'],'sort')
                    self.assertEqual(original.get_by_role('tab').get_attribute('aria-selected'),'true')
                    controller.args['controlId']=next(c['controlId'] for c in listed if c['action']=='next_page')
                    self.assertEqual(click_button(controller,product_identity)['action'],'next_page')
                    controller.args.update({'action':'back','tabId':controller.tab_id(original)})
                    self.assertEqual(controller.page_action()['action'],'back')
                    self.assertNotIn('page=2',original.url)
                    controller.args['keyword'] = 'PLA钩子'
                    controller.collect()
                    self.assertEqual(original.evaluate('window.searches'), 3)
                    self.assertEqual(len(context.pages), 1)
                    product_page = context.new_page()
                    product_page.goto('https://item.taobao.com/item.htm?id=123')
                    controller.focus.activate(product_page)
                    controller.args.update({'item': 'https://item.taobao.com/item.htm?id=123&spm=other', 'sku': ['1kg']})
                    product = controller.product()
                    self.assertEqual(product['source'], 'existing-tab')
                    self.assertIn('1.75mm', product['product']['description'])
                    self.assertTrue(product['product']['skuCandidates'])
                    controller.args['tabId']=controller.tab_id(product_page)
                    listed=list_buttons(controller,product_identity)['controls']
                    option=next(c for c in listed if c['action']=='select_sku' and c['label']=='1kg')
                    controller.args['controlId']=option['controlId']
                    chosen=click_button(controller,product_identity)
                    self.assertTrue(chosen['selected'])
                    self.assertIn('1kg',chosen['product']['selectedSku'])
                    before = len(context.pages)
                    collage = controller.sku_images()
                    self.assertEqual(collage['imageCount'], 3)
                    with Image.open(collage['file']) as image:
                        self.assertEqual(image.size, (1200, 1410))
                    self.assertEqual(product_page.locator('.selected').inner_text(), '1kg')
                    self.assertEqual(product_page.evaluate('window.cart'), 0)
                    self.assertEqual(len(context.pages), before)
                    self.assertEqual(collage['tabId'], product['product']['tabId'])
                    price[0] = '99.00'; controller.args['fresh'] = True
                    updated = controller.product()
                    self.assertEqual(updated['source'], 'refreshed-tab')
                    self.assertIn('99.00', updated['product']['prices'])
                    self.assertEqual(len(context.pages), before)
                    product_page.close(); controller.args['fresh'] = False
                    cached = controller.product()
                    self.assertEqual(cached['source'], 'cache')
                    self.assertEqual(len(context.pages), before - 1)
                    self.assertEqual(product_identity('123')['key'], product_identity('https://detail.tmall.com/item.htm?id=123&spm=x')['key'])
                    controller.args['fresh']=True
                    controller.focus.activate(original)
                    # Reopen only by a real visible product link; site may open a tab.
                    original.locator('a').evaluate("e=>e.target='_blank'")
                    p,source=controller.product_page('123',True)
                    self.assertEqual(source,'clicked-link')
                    self.assertEqual(len(context.pages),before)  # popup created by the real link
                    self.assertEqual(product_identity(p.url)['productId'],'123')
                    p.close()
                    original.evaluate("()=>{const el=document.createElement('div');el.id='captcha';el.textContent='安全验证';document.body.append(el)}")
                    searches = original.evaluate('window.searches')
                    with self.assertRaisesRegex(RuntimeError, 'Verification'):
                        controller.search()
                    self.assertEqual(original.evaluate('window.searches'), searches)
                self.assertFalse(original.is_closed())
                print('PASS Python Chrome search-box reuse, blank reuse, product cache/refresh, SKU collage, blocking stop, MCP bridge and browser preservation')
            finally:
                context.close()

    def test_reject_non_direct_chrome(self):
        with tempfile.TemporaryDirectory(prefix='huoyan-py-proxy-') as folder, sync_playwright() as playwright:
            port = free_port()
            context = playwright.chromium.launch_persistent_context(str(Path(folder) / 'profile'), executable_path=CHROME,
                headless=True, ignore_default_args=['--enable-automation'], args=[f'--remote-debugging-port={port}'])
            try:
                result = subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / 'huoyan.py'), 'status', '--cdp', f'http://127.0.0.1:{port}', '--out', str(Path(folder) / 'data')],
                    capture_output=True, text=True, timeout=30)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('direct mode', result.stdout)
                self.assertFalse(context.pages[0].is_closed())
            finally:
                context.close()


if __name__ == '__main__':
    unittest.main()
