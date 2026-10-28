"""Shop interfaces against isolated local DOM fixtures, never real shopping traffic."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from playwright.sync_api import sync_playwright
from python.huoyan_browser import Controller,load_json
from python.shopping_research import run

CHROME='C:/Program Files/Google/Chrome/Application/chrome.exe'
PRODUCT='''<!doctype html><meta charset="utf-8"><title>Product fixture</title>
<a class="shop-name" href="https://shop123.taobao.com/">测试同名店</a>
<div class="skuItem"><span class="label">重量</span><li class="selected">1kg</li><li>2kg</li></div><div data-product-price>￥36</div>'''
SHOP='''<!doctype html><meta charset="utf-8"><title>Shop fixture</title><style>[hidden]{display:none!important}</style>
<h1 data-shop-name>测试同名店</h1>
<form data-global-search onsubmit="event.preventDefault();globalCalls++"><input name="q" value="全站词"><button>搜全站</button></form>
<form data-shop-search onsubmit="event.preventDefault();shopCalls++;history.pushState({},'', '/search.htm?keyword='+encodeURIComponent(this.q.value));document.querySelector('[data-shop-query]').setAttribute('data-shop-query',this.q.value);document.querySelector('[data-shop-query]').innerText=this.q.value;render(this.q.value==='无结果')"><input name="q" value=""><button>搜本店</button></form>
<span data-shop-query=""></span>
<nav class="shop-nav"><a data-shop-section href="#all" onclick="this.setAttribute('aria-current','page')">全部商品</a><a data-shop-section href="#new" onclick="this.setAttribute('aria-current','page')">上新</a></nav>
<div class="shop-category"><button data-shop-category aria-expanded="false" onclick="this.setAttribute('aria-expanded',true);document.querySelector('#sub').hidden=false">耗材分类</button><div id="sub" hidden><a data-shop-category href="#pla" onclick="this.setAttribute('aria-current','page')">PLA</a></div></div>
<button role="tab" aria-selected="true" onclick="sort(this)">综合</button><button role="tab" onclick="sort(this)">销量</button>
<button aria-label="下一页" onclick="document.querySelector('[aria-current=page]#p').innerText='2'">下一页</button><span id="p" aria-current="page">1</span>
<div data-shop-products id="cards"></div><div data-recommendation><a data-product-card href="https://item.taobao.com/item.htm?id=999">外店推荐 ￥9</a></div>
<button onclick="danger++">关注店铺</button><button onclick="danger++">领取优惠券</button><a href="https://evil.test/">进入店铺</a>
<script>window.shopCalls=window.globalCalls=window.danger=0;function render(empty){document.querySelector('#cards').innerHTML=empty?'没有找到相关商品':[123,456].map(id=>'<a data-product-card target="_blank" href="https://item.taobao.com/item.htm?id='+id+'">PLA '+id+' ￥36</a>').join('')}render(false);function sort(e){document.querySelectorAll('[role=tab]').forEach(x=>x.setAttribute('aria-selected',x===e))}
const q=new URL(location.href).searchParams.get('keyword');if(q!==null){document.querySelector('[data-shop-search] input').value=q;document.querySelector('[data-shop-query]').setAttribute('data-shop-query',q);document.querySelector('[data-shop-query]').innerText=q;render(q==='无结果')}
</script>'''
GLOBAL='''<!doctype html><meta charset="utf-8"><title>Search fixture</title>
<button data-search-target="products" role="tab" aria-selected="true" onclick="mode(this)">宝贝</button><button data-search-target="shops" role="tab" onclick="mode(this)">店铺</button>
<form onsubmit="event.preventDefault();history.pushState({},'', '/search?q='+encodeURIComponent(this.q.value));document.querySelector('#cards').hidden=false"><input name="q"><button>搜索</button></form>
<div id="cards" hidden><article data-shop-card><a href="https://shop123.taobao.com/">测试同名店</a></article><article data-shop-card><a href="https://shop456.taobao.com/">测试同名店</a></article></div>
<script>function mode(e){document.querySelectorAll('[data-search-target]').forEach(x=>x.setAttribute('aria-selected',x===e))}</script>'''


class ShopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='huoyan-shop-');cls.pw=sync_playwright().start()
        cls.context=cls.pw.chromium.launch_persistent_context(str(Path(cls.temp.name)/'profile'),executable_path=CHROME,headless=True,args=['--no-proxy-server'])
        cls.context.route('**/*',lambda r:r.fulfill(content_type='text/html; charset=utf-8',body=PRODUCT if 'item.taobao.com' in r.request.url else GLOBAL if 's.taobao.com' in r.request.url else SHOP))
    @classmethod
    def tearDownClass(cls):cls.context.close();cls.pw.stop();cls.temp.cleanup()
    def setUp(self):
        self.page=self.context.new_page();self.page.goto('https://shop123.taobao.com/')
        self.base={'out':str(Path(self.temp.name)/self._testMethodName),'delayMin':0,'delayMax':0,'verificationTimeoutMs':180,'settleMs':0,'stableMs':0}
        self.c=Controller(self.base.copy(),self.context.browser).__enter__();self.c.pause=lambda *a,**k:0
        self.tab=self.c.tab_id(self.page);self.c.focus.activate(self.page);self.original=set(self.context.pages)
    def tearDown(self):
        for p in self.context.pages:
            self.assertEqual(p.evaluate('window.danger||0'),0)
        self.c.close()
        for p in list(self.context.pages):
            if p is self.page or p not in self.original:p.close()
    def call(self,op,**kw):
        self.c.args={**self.base,'tabId':self.tab,'operation':op,**kw};return run(self.c)
    def ctrl(self,state,action,label=None):return next(r['controlId'] for r in state['controls'] if r['action']==action and (label is None or r['label']==label))
    def enter_product(self,same_tab=False):
        if same_tab:self.page.locator('[data-shop-products] a').first.evaluate("e=>e.removeAttribute('target')")
        s=self.call('shop_state');r=self.call('open_shop_product',controlId=self.ctrl(s,'open_product'))
        self.tab=r['state']['tabId'];return r

    def test_discovery_dual_search_q_pair_privacy(self):
        s=self.call('shop_state');self.assertEqual(s['shop']['identity']['shopId'],'123');self.assertIsNone(s['shop']['identity']['sellerId'])
        self.assertNotIn('elementPath',json.dumps(s));self.assertNotIn('fieldPath',json.dumps(s));self.assertNotIn('关注店铺',[r['label'] for r in s['controls']])
        r=self.call('search_shop_products',keyword='PLA');self.assertTrue(r['confirmed']);self.assertEqual(self.page.evaluate('[shopCalls,globalCalls]'),[1,0])
        self.assertEqual(r['state']['shop']['queryEvidence']['value'],'PLA')
        self.assertTrue(self.call('search_shop_products',keyword='PLA')['alreadySatisfied'])

    def test_noop_search_not_success_just_input(self):
        self.page.locator('[data-shop-search]').evaluate('e=>e.onsubmit=ev=>{ev.preventDefault();shopCalls++}')
        r=self.call('search_shop_products',keyword='PLA');self.assertFalse(r['confirmed']);self.assertEqual(self.page.evaluate('shopCalls'),1)
    def test_no_results_is_valid_and_no_global_fallback(self):
        r=self.call('search_shop_products',keyword='无结果');self.assertTrue(r['confirmed']);self.assertTrue(r['state']['noResults']);self.assertEqual(self.page.evaluate('globalCalls'),0)
    def test_pair_ambiguity_rejects_before_edit(self):
        self.page.locator('[data-shop-search]').evaluate("e=>e.insertAdjacentHTML('afterbegin','<input name=keywords>')")
        with self.assertRaisesRegex(RuntimeError,'pairing'):self.call('search_shop_products',keyword='PLA')
        self.assertEqual(self.page.locator('[data-shop-search] input').last.input_value(),'')
    def test_scope_escape_is_false(self):
        self.page.locator('[data-shop-search]').evaluate("e=>e.onsubmit=ev=>{ev.preventDefault();location.href='https://s.taobao.com/search?q=PLA'}")
        r=self.call('search_shop_products',keyword='PLA');self.assertFalse(r['confirmed']);self.assertEqual(r['code'],'SCOPE_MISMATCH')
    def test_product_return_popup_and_save_evidence(self):
        self.call('search_shop_products',keyword='PLA');r=self.enter_product();self.assertTrue(r['confirmed']);self.assertIn('detail',r['state']);self.assertEqual(r['shopEvidence']['cardRegion'],'shop-products')
        saved=self.call('save_candidate')['candidate'];self.assertEqual(saved['shopDiscovery']['source']['query'],'PLA')
        back=self.call('return_to_shop_results');self.assertTrue(back['confirmed']);self.tab=back['state']['tabId'];self.assertTrue(back['contextRestored'])
        self.assertEqual(back['state']['shop']['query'],'PLA')
    def test_same_tab_return_history(self):
        self.call('search_shop_products',keyword='PLA');self.enter_product(True)
        back=self.call('return_to_shop_results');self.assertTrue(back['confirmed']);self.assertEqual(back['state']['shop']['query'],'PLA')
    def test_existing_product_reuse_multiple_visits(self):
        r=self.enter_product();product_tab=self.tab;count=len(self.context.pages)
        b=self.call('return_to_shop_results');self.tab=b['state']['tabId'];self.call('search_shop_products',keyword='黑色')
        r=self.enter_product();self.assertEqual(self.tab,product_tab);self.assertEqual(len(self.context.pages),count)
        db=load_json(self.c.out/'shop-visits.json',{});self.assertEqual(len(db['visits']),2)
        self.assertEqual(self.call('return_to_shop_results')['state']['shop']['query'],'黑色')
    def test_changed_or_closed_source_not_reconstructed(self):
        self.enter_product();self.page.evaluate("()=>{const e=document.querySelector('[data-shop-query]');e.setAttribute('data-shop-query','changed');e.innerText='changed'}")
        r=self.call('return_to_shop_results');self.assertFalse(r['confirmed']);self.assertFalse(r['contextRestored'])
    def test_closed_source_stops(self):
        self.enter_product();self.page.close()
        with self.assertRaisesRegex(RuntimeError,'closed'):self.call('return_to_shop_results')
    def test_recommendation_refused_and_stale_ref(self):
        s=self.call('shop_state');rec=next(r for r in s['controls'] if r.get('productId')=='999')
        with self.assertRaisesRegex(RuntimeError,'recommendation'):self.call('open_shop_product',controlId=rec['controlId'])
        s=self.call('shop_state');ref=self.ctrl(s,'shop_section');self.call('shop_state')
        with self.assertRaisesRegex(RuntimeError,'expired'):self.call('open_shop_section',controlId=ref)
    def test_sections_category_sort_pagination(self):
        s=self.call('shop_state');r=self.call('open_shop_section',controlId=self.ctrl(s,'shop_section','全部商品'));self.assertTrue(r['confirmed'])
        s=r['state'];r=self.call('open_shop_category',controlId=self.ctrl(s,'shop_category','耗材分类'));self.assertTrue(r['confirmed'])
        self.assertTrue(any(x['label']=='PLA' for x in r['state']['controls']))
        r=self.call('open_shop_category',controlId=self.ctrl(r['state'],'shop_category','PLA'));self.assertTrue(r['confirmed'])
        self.assertTrue(self.call('set_sort',field='sales')['confirmed']);s=self.call('shop_state')
        self.assertTrue(self.call('click_shopping_control',controlId=self.ctrl(s,'next_page'))['confirmed'])
    def test_global_shop_discovery_same_name_different_id(self):
        self.page.goto('https://s.taobao.com/search');self.c.focus.activate(self.page)
        r=self.call('search_products',keyword='测试同名店',target='shops');self.assertTrue(r['confirmed'])
        shops=self.call('list_shops');self.assertEqual(len(shops['shops']),2);self.assertNotEqual(shops['shops'][0]['identity']['key'],shops['shops'][1]['identity']['key'])
        r=self.call('open_shop',controlId=shops['shops'][1]['controlId']);self.assertTrue(r['confirmed']);self.assertEqual(r['state']['shop']['identity']['shopId'],'456')
    def test_tmall_shop_and_unsupported_frame(self):
        self.page.goto('https://examplebrand.tmall.com/');self.c.focus.activate(self.page)
        self.assertEqual(self.call('shop_state')['pageType'],'shop')
        self.page.evaluate("document.querySelectorAll('form').forEach(e=>e.remove());const f=document.createElement('iframe');f.src='https://frame.test/';document.body.append(f)")
        s=self.call('shop_state');self.assertTrue(s['shop']['coverage']['unsupportedFrames'])
        with self.assertRaisesRegex(RuntimeError,'search controlId'):self.call('search_shop_products',keyword='PLA')
    def test_shop_reuse_identity_not_search_url(self):
        self.page.goto('https://shop123.taobao.com/search.htm?keyword=PLA&spm=tracking');self.page.evaluate('window.keepState=42')
        source=self.context.new_page();source.goto('https://item.taobao.com/item.htm?id=123');self.tab=self.c.tab_id(source);self.c.focus.activate(source)
        r=self.call('open_product_shop');self.assertTrue(r['confirmed']);self.assertEqual(r['source'],'existing-shop-tab');self.assertEqual(self.page.evaluate('window.keepState'),42)
        self.assertEqual(r['state']['shop']['query'],'PLA')

    def test_multiple_shop_forms_require_current_explicit_control(self):
        self.page.locator('[data-shop-search]').evaluate("e=>{const other=e.cloneNode(true);other.querySelector('input').value='other';e.after(other)}")
        with self.assertRaisesRegex(RuntimeError,'search controlId'):self.call('search_shop_products',keyword='PLA')
        s=self.call('shop_state');rows=[r for r in s['controls'] if r['action']=='search' and r.get('searchScope')=='shop']
        self.assertEqual(len(rows),2);r=self.call('search_shop_products',keyword='PLA',controlId=rows[1]['controlId'])
        self.assertTrue(r['confirmed']);self.assertEqual(self.page.locator('[data-shop-search] input').first.input_value(),'')
    def test_alias_shop_id_reuses_without_reload(self):
        self.page.evaluate('window.keepState=42')
        source=self.context.new_page();source.goto('https://item.taobao.com/item.htm?id=123')
        source.locator('a').evaluate("e=>e.href='https://store.taobao.com/shop/view_shop.htm?shop_id=123&spm=promotion'")
        self.tab=self.c.tab_id(source);self.c.focus.activate(source)
        r=self.call('open_product_shop');self.assertTrue(r['confirmed']);self.assertEqual(r['source'],'existing-shop-tab');self.assertEqual(self.page.evaluate('window.keepState'),42)
    def test_newest_only_when_real_control_exists(self):
        with self.assertRaisesRegex(RuntimeError,'UNSUPPORTED'):self.call('set_sort',field='newest')
        self.page.evaluate("()=>{const b=document.createElement('button');b.role='tab';b.innerText='新品';b.onclick=()=>sort(b);document.body.append(b)}")
        r=self.call('set_sort',field='newest');self.assertTrue(r['confirmed']);self.assertEqual(r['state']['sort']['field'],'newest')
    def test_global_visit_replaces_latest_shop_origin_keeps_history(self):
        self.enter_product();product_tab=self.tab
        global_page=self.context.new_page();global_page.goto('https://s.taobao.com/search')
        global_page.evaluate("()=>{const a=document.createElement('a');a.href='https://item.taobao.com/item.htm?id=123';a.innerText='PLA ￥36';document.body.append(a)}")
        self.tab=self.c.tab_id(global_page);self.c.focus.activate(global_page)
        s=self.call('shopping_state');r=self.call('click_shopping_control',controlId=self.ctrl(s,'open_product'));self.assertEqual(r['state']['tabId'],product_tab)
        self.tab=product_tab;db=load_json(self.c.out/'shop-visits.json',{});self.assertEqual(len(db['visits']),1);self.assertNotIn(product_tab,db['latest'])
        self.assertEqual(self.call('return_to_results')['state']['tabId'],self.c.tab_id(global_page))
    def test_sort_scope_escape_stops_and_registry_updates(self):
        self.call('shop_state')
        self.page.get_by_role('tab',name='销量',exact=True).evaluate("e=>e.onclick=()=>location.href='https://shop456.taobao.com/'")
        r=self.call('set_sort',field='sales');self.assertFalse(r['confirmed']);self.assertEqual(r['code'],'SCOPE_MISMATCH');self.assertEqual(r['clicks'],1)
        db=load_json(self.c.out/'shop-tabs.json',{});self.assertEqual(db['tabs'][self.tab]['identity']['shopId'],'456')

    def test_target_menu_discovery_and_seller_evidence(self):
        self.page.locator('h1').evaluate("e=>e.setAttribute('data-seller-id','567')")
        self.assertEqual(self.call('shop_state')['shop']['identity']['sellerId'],'567')
        self.page.goto('https://s.taobao.com/search');self.c.focus.activate(self.page)
        self.page.locator('[data-search-target=shops]').evaluate('e=>e.hidden=true')
        self.page.locator('[data-search-target=products]').evaluate("e=>{e.setAttribute('aria-haspopup','menu');e.onclick=()=>{document.querySelector('[data-search-target=shops]').hidden=false}}")
        s=self.call('shopping_state');self.assertFalse(any(r.get('target')=='shops' for r in s['controls']))
        r=self.call('click_shopping_control',controlId=self.ctrl(s,'search_target_menu'));self.assertTrue(r['confirmed'])
        self.assertTrue(self.call('search_products',keyword='测试店',target='shops')['confirmed'])

    def test_native_submit_and_shop_home_navigation(self):
        self.page.locator('[data-shop-search] button').evaluate("e=>{const i=document.createElement('input');i.type='submit';i.value='搜索';e.replaceWith(i)}")
        r=self.call('search_shop_products',keyword='PLA');self.assertTrue(r['confirmed'])
        self.page.locator('.shop-nav').evaluate("e=>{const a=document.createElement('a');a.href='https://shop123.taobao.com/';a.innerText='店铺首页';e.append(a)}")
        s=self.call('shop_state');home=next(r for r in s['controls'] if r['label']=='店铺首页');self.assertEqual(home['action'],'shop_section')
        r=self.call('open_shop_section',controlId=home['controlId']);self.assertTrue(r['confirmed']);self.assertEqual(r['state']['shop']['stage'],'home')

if __name__=='__main__':unittest.main(verbosity=2)
