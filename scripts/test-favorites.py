"""Local Chrome favorites fixtures. No real account mutations or paid model calls."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from playwright.sync_api import sync_playwright
from python.huoyan_browser import Controller,atomic_json,run as dispatch
from python.shopping_research import run

FOLDER='https://i.taobao.com/my_itaobao/itao-tool/collect'
PRODUCT='https://item.taobao.com/item.htm?id=123'
PRODUCT_HTML='''<!doctype html><meta charset=utf-8><title>PLA 测试商品</title><h1>PLA 测试商品</h1>
<a href="https://i.taobao.com/my_itaobao/itao-tool/collect">收藏夹</a>
<div class=skuItem><span class=label>颜色</span><li onclick="pick(this)">白色1kg</li><li onclick="pick(this)">灰色1kg</li></div>
<div data-product-price>￥36</div><div class=RightButton--fixture data-favorite-toggle aria-pressed=false onclick="toggle(this)">收藏</div>
<button onclick="cart++">加购</button><button onclick="orders++">立即购买</button>
<script>window.favoriteClicks=window.cart=window.orders=0;window.marker=42;window.uncertain=false;
function toggle(e){favoriteClicks++;if(!uncertain){const selected=e.getAttribute('aria-pressed')!=='true';e.setAttribute('aria-pressed',selected);e.innerText=selected?'已收藏':'收藏';}}
function pick(e){document.querySelectorAll('.skuItem li').forEach(x=>x.classList.toggle('selected',x===e));}</script>'''
FOLDER_HTML='''<!doctype html><meta charset=utf-8><title>我的收藏</title>
<header><form onsubmit="event.preventDefault();globalSearches++"><input name=q><button>搜索</button></form></header>
<main data-taobao-favorites-page>
<form data-favorites-search onsubmit="event.preventDefault();searchFavorites(this)"><input name=keyword><button>搜索</button></form>
<div id=cards><li data-favorite-item><a href="https://item.taobao.com/item.htm?id=123&spm=one" target=_blank>PLA 测试商品 ￥36</a><a href="https://detail.tmall.com/item.htm?id=123&spm=two" target=_blank>同商品推广链接</a></li></div>
<aside data-recommendation><a href="https://item.taobao.com/item.htm?id=999">推荐商品</a></aside>
<button onclick="deletes++">批量删除</button></main>
<script>window.favoriteSearches=window.globalSearches=window.deletes=0;function searchFavorites(form){favoriteSearches++;const a=document.createElement('a');a.href='https://item.taobao.com/item.htm?id=456';a.innerText=form.keyword.value;document.querySelector('#cards').replaceChildren(a);}</script>'''


class FavoriteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='huoyan-favorites-')
        cls.pw=sync_playwright().start()
        cls.context=cls.pw.chromium.launch_persistent_context(str(Path(cls.temp.name)/'profile'),
            executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True,args=['--no-proxy-server'])
        cls.context.route('**/*',lambda r:r.fulfill(content_type='text/html; charset=utf-8',body=FOLDER_HTML if '/collect' in r.request.url else PRODUCT_HTML))

    @classmethod
    def tearDownClass(cls):cls.context.close();cls.pw.stop();cls.temp.cleanup()

    def setUp(self):
        self.page=self.context.new_page();self.page.goto(PRODUCT)
        self.c=Controller({'out':str(Path(self.temp.name)/self._testMethodName),'delayMin':0,'delayMax':0},self.context.browser).__enter__()
        self.c.pause=lambda *a,**k:0
        self.c.focus.activate(self.page)

    def tearDown(self):
        for p in list(self.context.pages):
            if p.url.startswith('https://item.taobao.com'):
                self.assertEqual(p.evaluate('cart+orders'),0)
        self.c.close()
        for p in list(self.context.pages)[1:]:p.close()

    def call(self,operation,**kw):
        self.c.args={'operation':operation,'tabId':self.c.tab_id(self.page),'delayMin':0,'delayMax':0,'favoriteTimeoutMs':200,**kw}
        return run(self.c)

    def folder(self):
        self.page.goto(FOLDER);self.c.focus.activate(self.page)

    def test_local_save_without_sku_and_product_dedup(self):
        a=self.call('save_local_favorite',note='打印材料',tags=['PLA','PLA'])
        self.assertEqual(a['favorite']['tags'],['PLA']);self.assertFalse(a['taobaoAccountChanged'])
        self.assertFalse(next(iter(a['favorite']['skuSnapshots'].values()))['skuSelectionComplete'])
        self.page.goto(PRODUCT+'&spm=another');self.c.focus.activate(self.page)
        self.page.locator('.skuItem li').last.click()
        b=self.call('save_local_favorite')
        self.assertEqual(a['favorite']['favoriteId'],b['favorite']['favoriteId'])
        self.assertEqual(len(b['favorite']['skuSnapshots']),2)
        self.assertEqual(b['favorite']['note'],'打印材料')
        self.assertEqual(self.call('list_local_favorites',query='打印材料')['totalMatches'],1)
        self.assertEqual(self.call('list_local_favorites',query='灰色1kg')['totalMatches'],1)
        self.assertEqual(self.page.evaluate('favoriteClicks'),0)

    def test_offline_list_remove_no_browser_and_account_unchanged(self):
        self.call('save_local_favorite',tags=['耗材'])
        with patch('python.huoyan_browser.Controller.__enter__',side_effect=AssertionError('browser called')):
            r=dispatch('shopping',{'operation':'list_local_favorites','stateDir':str(self.c.out),'query':'耗材'})
            self.assertEqual(r['totalMatches'],1)
            r=dispatch('shopping',{'operation':'remove_local_favorite','stateDir':str(self.c.out),'favoriteId':'taobao:123'})
            self.assertTrue(r['removed']);self.assertFalse(r['taobaoAccountChanged'])
        self.assertEqual(self.page.evaluate('favoriteClicks'),0)

    def test_open_local_reuses_tab_without_refresh_or_sku_change(self):
        a=self.call('save_local_favorite')
        self.page.locator('.skuItem li').last.click()
        r=self.call('open_local_favorite',favoriteId=a['favorite']['favoriteId'])
        self.assertEqual(r['source'],'existing-tab');self.assertFalse(r['skuRestored'])
        self.assertEqual(self.page.evaluate('marker'),42)
        self.assertEqual(self.page.locator('.selected').inner_text(),'灰色1kg')

    def test_closed_local_uses_cache_and_never_navigates_saved_url(self):
        a=self.call('save_local_favorite');self.page.close()
        with patch('python.huoyan_browser.Controller.__enter__',side_effect=RuntimeError('offline')):
            r=dispatch('shopping',{'operation':'open_local_favorite','stateDir':str(self.c.out),'favoriteId':a['favorite']['favoriteId']})
        self.assertEqual(r['source'],'local-cache');self.assertFalse(r['pageOpened']);self.assertTrue(r['stale'])

    def test_native_options_add_replay_no_toggle_and_request_conflict(self):
        state=self.call('favorite_options');ref=next(r['controlId'] for r in state['controls'] if r['action']=='set_taobao_favorite')
        r=self.call('set_taobao_favorite',controlId=ref,requestId='first',selected=True)
        self.assertTrue(r['confirmed']);self.assertEqual(self.page.evaluate('favoriteClicks'),1)
        self.assertTrue(self.call('set_taobao_favorite',controlId=ref,requestId='first',selected=True)['replayed'])
        self.assertTrue(self.call('set_taobao_favorite',requestId='already',selected=True)['alreadySatisfied'])
        self.assertEqual(self.page.evaluate('favoriteClicks'),1)
        with self.assertRaisesRegex(RuntimeError,'REQUEST_CONFLICT'):self.call('set_taobao_favorite',requestId='already',selected=False)

    def test_native_remove_is_explicit_desired_state(self):
        self.call('set_taobao_favorite',requestId='add',selected=True)
        r=self.call('set_taobao_favorite',requestId='remove',selected=False)
        self.assertTrue(r['confirmed']);self.assertEqual(self.page.evaluate('favoriteClicks'),2)
        self.call('set_taobao_favorite',requestId='remove',selected=False)
        self.assertEqual(self.page.evaluate('favoriteClicks'),2)

    def test_uncertain_click_never_retries_and_reconciles_same_request(self):
        self.page.evaluate('uncertain=true')
        r=self.call('set_taobao_favorite',requestId='unknown',selected=True)
        self.assertFalse(r['confirmed']);self.assertFalse(r['retryAllowed'])
        self.call('set_taobao_favorite',requestId='unknown',selected=True)
        with self.assertRaisesRegex(RuntimeError,'OUTCOME_UNKNOWN'):self.call('set_taobao_favorite',requestId='new',selected=True)
        self.assertEqual(self.page.evaluate('favoriteClicks'),1)
        self.page.locator('[data-favorite-toggle]').evaluate("e=>{e.setAttribute('aria-pressed','true');e.innerText='已收藏'}")
        self.assertTrue(self.call('set_taobao_favorite',requestId='unknown',selected=True)['confirmed'])

    def test_stale_control_and_changed_context_stop_before_click(self):
        s=self.call('favorite_options');ref=next(r['controlId'] for r in s['controls'] if r['action']=='set_taobao_favorite')
        self.call('favorite_options')
        with self.assertRaisesRegex(RuntimeError,'STALE_FAVORITE_CONTROL'):self.call('set_taobao_favorite',requestId='stale',controlId=ref)
        self.c.pause=lambda *a,**k:self.page.locator('[data-favorite-toggle]').evaluate("e=>e.innerText='购买'")
        with self.assertRaisesRegex(RuntimeError,'STALE_FAVORITE_CONTROL'):self.call('set_taobao_favorite',requestId='changed')
        self.assertEqual(self.page.evaluate('favoriteClicks'),0)

    def test_folder_entry_and_dedup_excludes_recommendations_and_global_search(self):
        r=self.call('open_taobao_favorites')
        self.assertTrue(r['confirmed']);self.assertEqual(self.page.url,FOLDER)
        self.assertEqual([p['productId'] for p in r['state']['products']],['123'])
        self.assertFalse(any(x['action'] in ('delete','cart','buy') for x in r['state']['controls']))
        r=self.call('find_taobao_favorite',keyword='新收藏商品',maxScrolls=0)
        self.assertTrue(r['found']);self.assertTrue(r['searchedFavorites'])
        self.assertEqual(self.page.evaluate('favoriteSearches'),1);self.assertEqual(self.page.evaluate('globalSearches'),0)

    def test_open_favorite_reuses_product_and_return_to_source(self):
        source=self.page
        folder=self.context.new_page();folder.goto(FOLDER)
        self.page=folder;self.c.focus.activate(folder)
        r=self.call('open_taobao_favorite',productId='123')
        self.assertEqual(r['source'],'existing-tab');self.assertEqual(r['state']['tabId'],self.c.tab_id(source))
        self.assertEqual(source.evaluate('marker'),42)
        self.page=source
        back=self.call('return_to_results');self.assertEqual(back['state']['tabId'],self.c.tab_id(folder))

    def test_open_favorite_real_link_popup_and_local_fresh(self):
        a=self.call('save_local_favorite');self.page.close()
        self.page=self.context.new_page();self.page.goto(FOLDER);self.c.focus.activate(self.page)
        r=self.call('open_local_favorite',favoriteId=a['favorite']['favoriteId'],fresh=True,maxScrolls=0)
        self.assertTrue(r['confirmed']);self.assertEqual(r['source'],'clicked-favorite-card')
        self.assertEqual(r['state']['product']['productId'],'123')

    def test_favorite_not_loaded_and_empty_coverage_no_direct_open(self):
        self.folder();before=len(self.context.pages)
        with self.assertRaisesRegex(RuntimeError,'FAVORITE_NOT_LOADED'):self.call('open_taobao_favorite',productId='555')
        self.page.locator('#cards').evaluate("e=>e.innerHTML='<div data-favorites-empty>收藏夹空空的</div>'")
        r=self.call('find_taobao_favorite',productId='555',maxScrolls=2)
        self.assertFalse(r['found']);self.assertEqual(r['stopReason'],'EXPLICIT_EMPTY');self.assertEqual(len(self.context.pages),before)

    def test_bounded_native_scroll_loads_actual_favorite_card(self):
        self.folder()
        self.page.evaluate('''()=>{const box=document.querySelector('#cards');box.style.minHeight='4000px';window.addEventListener('scroll',()=>{if(scrollY>10&&!document.querySelector('#lazy-card')){const a=document.createElement('a');a.id='lazy-card';a.href='https://item.taobao.com/item.htm?id=555';a.innerText='向下加载的收藏';box.append(a);}});}''')
        initial=self.call('find_taobao_favorite',productId='555',maxScrolls=0)
        self.assertFalse(initial['found']);self.assertEqual(initial['scrolls'],0)
        loaded=self.call('find_taobao_favorite',productId='555',maxScrolls=2)
        self.assertTrue(loaded['found']);self.assertLessEqual(loaded['scrolls'],2)
        self.assertEqual(loaded['products'][0]['productId'],'555')


if __name__=='__main__':unittest.main(verbosity=2)
