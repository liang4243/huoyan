"""Tab-budget integration against ordinary headed Chrome and local fixtures only."""
from pathlib import Path
import json
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from playwright.sync_api import sync_playwright
from python.huoyan_browser import Controller,load_json
from python.shopping_research import run

HTML='''<!doctype html><meta charset="utf-8"><title>Local tab budget</title>
<p data-product-price>￥12.50</p><p data-product-description>本地商品</p>
<a data-product-card target="_blank" href="https://item.taobao.com/item.htm?id=999">商品999 ￥12.50</a>'''


class BudgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='huoyan-budget-');cls.pw=sync_playwright().start()
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        cls.endpoint=f'http://127.0.0.1:{port}'
        cls.process=subprocess.Popen(['C:/Program Files/Google/Chrome/Application/chrome.exe',
            '--no-proxy-server','--no-first-run','--no-default-browser-check',
            f'--user-data-dir={Path(cls.temp.name)/"profile"}',f'--remote-debugging-port={port}',
            '--remote-debugging-address=127.0.0.1','about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(40):
            try:
                with opener.open(f'{cls.endpoint}/json/version',timeout=.5):break
            except Exception:time.sleep(.2)
        cls.browser=cls.pw.chromium.connect_over_cdp(cls.endpoint,no_defaults=True)
        cls.context=cls.browser.contexts[0];cls.requests=0
        def respond(route):
            cls.requests+=1;route.fulfill(content_type='text/html; charset=utf-8',body=HTML)
        cls.context.route('**/*',respond)

    @classmethod
    def tearDownClass(cls):
        try:cls.browser.new_browser_cdp_session().send('Browser.close')
        finally:cls.browser.close();cls.pw.stop();cls.process.wait(timeout=10);cls.temp.cleanup()

    def setUp(self):
        self.original=self.context.pages[0]
        self.c=Controller({'out':str(Path(self.temp.name)/self._testMethodName),'cdp':self.endpoint,
            'delayMin':0,'delayMax':0,'verificationTimeoutMs':300,'settleMs':0,'stableMs':0},self.browser).__enter__()
        self.c.pause=lambda *a,**k:0

    def tearDown(self):
        self.c.close()
        for p in list(self.context.pages):
            if p is not self.original:p.close()

    def product(self,n,managed=True):
        p=self.context.new_page();p.goto(f'https://item.taobao.com/item.htm?id={n}')
        self.c.tab_budget.touch(p,managed=managed)
        return p

    def bind(self,p):
        p.bring_to_front();self.c.focus.activate(p,background=True);self.c.args['tabId']=self.c.tab_id(p)

    def call(self,operation,**kw):
        self.c.args={**self.c.args,'operation':operation,**kw};return run(self.c)

    def test_lru_cache_protection_and_persistence(self):
        manual=self.product(100,False);old=self.product(101);recent=self.product(102);active=self.product(103)
        self.c.tab_budget.touch(old);self.c.tab_budget.touch(recent);self.bind(active)
        count=type(self).requests
        r=self.call('set_tab_limit',maxTabs=4)['tabBudget']
        self.assertFalse(r['blocked']);self.assertTrue(old.is_closed());self.assertFalse(manual.is_closed())
        self.assertFalse(recent.is_closed());self.assertFalse(active.is_closed());self.assertEqual(r['openTabs'],4)
        cache=load_json(self.c.registry_file,{})['products']['taobao:101']['cache']
        self.assertEqual(cache['prices'],['￥12.50']);self.assertTrue(r['closedTabs'][0]['cached'])
        cached,source=self.c.product_page('101');self.assertEqual(source,'cache');self.assertEqual(cached['productId'],'101')
        self.assertEqual(type(self).requests,count)
        reconnected=Controller({'out':str(self.c.out),'cdp':self.endpoint},self.browser)
        self.assertEqual(reconnected.tab_budget.status()['maxTabs'],4)

    def test_unknown_and_current_tabs_block_before_new_tab_click(self):
        self.product(201,False);active=self.product(202,False);self.bind(active)
        r=self.call('set_tab_limit',maxTabs=2)['tabBudget']
        self.assertTrue(r['blocked']);self.assertEqual(r['closedTabs'],[])
        # Use a real list page and link, never product-page navigation bypass.
        active.goto('https://s.taobao.com/search?q=local');self.bind(active)
        count=len(self.context.pages);requests=type(self).requests
        with self.assertRaisesRegex(RuntimeError,'TAB_LIMIT_REACHED'):
            self.c.product_page('999',True,require_page=True,from_page=active)
        self.assertEqual(len(self.context.pages),count);self.assertEqual(type(self).requests,requests)

    def test_real_popup_is_managed_and_slot_is_reserved_before_click(self):
        old=self.product(301)
        listing=self.context.new_page();listing.goto('https://s.taobao.com/search?q=local');self.bind(listing)
        self.call('set_tab_limit',maxTabs=3)
        state=self.call('shopping_state');row=next(r for r in state['controls'] if r['action']=='open_product')
        r=self.call('click_shopping_control',controlId=row['controlId'])
        self.assertTrue(r['confirmed']);self.assertTrue(old.is_closed());self.assertEqual(len(self.context.pages),3)
        tab=r['state']['tabId'];record=self.c.tab_budget.load()['tabs'][tab]
        self.assertTrue(record['managed']);self.assertEqual(record['productKey'],'taobao:999')
        self.assertIn('taobao:301',[x['productKey'] for x in r['tabBudget']['closedTabs']])
        self.assertFalse(listing.is_closed());self.assertFalse(r['tabBudget']['blocked'])

    def test_navigation_to_other_product_revokes_cleanup_ownership(self):
        changed=self.product(401);changed.goto('https://item.taobao.com/item.htm?id=499')
        active=self.product(402);self.bind(active)
        r=self.call('set_tab_limit',maxTabs=2)['tabBudget']
        self.assertTrue(r['blocked']);self.assertFalse(changed.is_closed())
        self.c.tab_budget.touch(changed)
        self.assertFalse(self.c.tab_budget.load()['tabs'][self.c.tab_id(changed)]['managed'])

    def test_busy_page_and_cache_failure_never_closed(self):
        old=self.product(501);old.evaluate("()=>{const e=document.createElement('textarea');document.body.append(e);e.value='unsaved'}")
        active=self.product(502);self.bind(active)
        r=self.call('set_tab_limit',maxTabs=2)['tabBudget']
        self.assertTrue(r['blocked']);self.assertFalse(old.is_closed());self.assertTrue(r['skippedTabs'])
        old.locator('textarea').evaluate('e=>e.remove()')
        original_guard=self.c.guard
        def fail(p):
            if p is old:raise RuntimeError('verification-detected')
            return original_guard(p)
        self.c.guard=fail
        r=self.call('trim_product_tabs')['tabBudget']
        self.assertTrue(r['blocked']);self.assertFalse(old.is_closed());self.assertEqual(r['closedTabs'],[])
        self.c.guard=original_guard
        from python.huoyan_browser import atomic_json
        def failed_cache(file,data):
            if file==self.c.registry_file:raise OSError('fixture cache write failure')
            return atomic_json(file,data)
        with patch('python.tab_budget.atomic_json',side_effect=failed_cache):
            r=self.call('trim_product_tabs')['tabBudget']
        self.assertTrue(r['blocked']);self.assertFalse(old.is_closed());self.assertEqual(r['closedTabs'],[])

    def test_readonly_state_never_trims_and_invalid_limit_does_not_change_policy(self):
        self.product(601);active=self.product(602);self.bind(active)
        data=self.c.tab_budget.load();data['maxTabs']=2
        from python.huoyan_browser import atomic_json
        atomic_json(self.c.tab_budget.file,data)
        count=len(self.context.pages)
        r=self.call('shopping_state');self.assertTrue(r['tabBudget']['overLimit']);self.assertEqual(len(self.context.pages),count)
        for limit in (True,1,51,2.5):
            with self.assertRaises(ValueError):self.call('set_tab_limit',maxTabs=limit)
        self.assertEqual(self.c.tab_budget.status()['maxTabs'],2)

    def test_endpoint_scope_never_reuses_ownership(self):
        old=self.product(701);active=self.product(702);self.bind(active)
        other=Controller({'out':str(self.c.out),'cdp':'http://127.0.0.1:1'},self.browser)
        other.tab_budget.configure(2)
        self.assertFalse(old.is_closed());self.assertFalse(other.tab_budget.load()['tabs'])


    def test_paused_workflow_source_is_protected(self):
        import time
        from python.huoyan_browser import atomic_json
        old=self.product(901);active=self.product(902);self.bind(active)
        atomic_json(self.c.out/'workflows.json',{'endpoint':self.c.endpoint,'runs':{'pending':{
            'sourceTabId':self.c.tab_id(old),'status':'paused','protectUntil':time.time()+60}}})
        report=self.call('set_tab_limit',maxTabs=2)['tabBudget']
        self.assertTrue(report['blocked']);self.assertFalse(old.is_closed())

    def test_uncertain_favorite_product_protected_until_reconciled(self):
        from python.huoyan_browser import atomic_json
        old=self.product(911);active=self.product(912);self.bind(active)
        journal={'endpoint':self.c.endpoint,'attempts':{'uncertain':{'intent':{'tabId':self.c.tab_id(old)},'dispatchAttempted':True,'confirmed':False}}}
        atomic_json(self.c.out/'favorite-actions.json',journal)
        report=self.call('set_tab_limit',maxTabs=2)['tabBudget']
        self.assertTrue(report['blocked']);self.assertFalse(old.is_closed())
        journal['attempts']['uncertain']['confirmed']=True
        atomic_json(self.c.out/'favorite-actions.json',journal)
        report=self.call('trim_product_tabs')['tabBudget']
        self.assertFalse(report['blocked']);self.assertTrue(old.is_closed())


if __name__=='__main__':unittest.main(verbosity=2)
