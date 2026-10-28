"""Headed real-Chrome focus tests; shopping traffic is local fixtures only."""
from pathlib import Path
import sys
import tempfile
import unittest
import subprocess
import socket
import time
import urllib.request
import json

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'scripts'))
from playwright.sync_api import sync_playwright
from python.huoyan_browser import Controller,product_identity
from python.shopping_research import run
from python.page_buttons import list_buttons,click_button
from importlib.util import spec_from_file_location,module_from_spec
spec=spec_from_file_location('research_fixtures',ROOT/'scripts/test-shopping-research.py')
fixture=module_from_spec(spec);spec.loader.exec_module(fixture)


class FocusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='huoyan-focus-')
        cls.pw=sync_playwright().start()
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        cls.endpoint=f'http://127.0.0.1:{port}'
        cls.process=subprocess.Popen([fixture.CHROME,'--no-proxy-server','--no-first-run','--no-default-browser-check',
            '--window-size=1000,800',f'--user-data-dir={Path(cls.temp.name)/"profile"}',f'--remote-debugging-port={port}',
            '--remote-debugging-address=127.0.0.1','about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(40):
            try:
                with opener.open(f'http://127.0.0.1:{port}/json/version',timeout=.5):break
            except Exception:time.sleep(.2)
        cls.browser=cls.pw.chromium.connect_over_cdp(f'http://127.0.0.1:{port}',no_defaults=True)
        cls.context=cls.browser.contexts[0]
        cls.context.route('**/*',lambda r:r.fulfill(content_type='text/html; charset=utf-8',body=fixture.HTML))

    @classmethod
    def tearDownClass(cls):
        try:cls.browser.new_browser_cdp_session().send('Browser.close')
        except Exception:pass
        cls.browser.close();cls.pw.stop();cls.process.wait(timeout=10);cls.temp.cleanup()

    def setUp(self):
        self.context.pages[0].goto('about:blank')
        self.page=self.context.new_page();self.page.goto('https://s.taobao.com/search?q=PLA')
        self.other=self.context.new_page();self.other.goto('https://example.test/')
        self.c=Controller({'out':str(Path(self.temp.name)/self._testMethodName),'cdp':self.endpoint,'delayMin':0,'delayMax':0,
            'verificationTimeoutMs':250,'settleMs':0,'stableMs':0},self.context.browser).__enter__()
        self.c.pause=lambda *a,**k:0
        self.c.out.mkdir(parents=True,exist_ok=True)
        self.c.home_state_file=self.c.out/'navigation-state.json'
        self.c.args['tabId']=self.c.tab_id(self.page)

    def tearDown(self):
        self.c.close()
        for p in list(self.context.pages):
            if p is not self.context.pages[0]:p.close()

    def call(self,op,**kw):
        self.c.args={**self.c.args,'operation':op,**kw}
        return run(self.c)

    def activate(self):return self.call('activate_shopping_tab',background=False)

    def test_resume_restores_minimized_existing_page_without_navigation(self):
        self.page.evaluate('window.keepMe=42')
        session=self.context.new_cdp_session(self.page)
        try:
            window=session.send('Browser.getWindowForTarget')['windowId']
            session.send('Browser.setWindowBounds',{'windowId':window,'bounds':{'windowState':'minimized'}})
            result=self.call('resume_shopping')
            self.assertTrue(result['confirmed'])
            self.assertEqual(result['recovery'],'reused-existing-tab')
            self.assertEqual(self.page.evaluate('window.keepMe'),42)
            self.assertNotEqual(session.send('Browser.getWindowBounds',{'windowId':window})['bounds']['windowState'],'minimized')
            self.assertEqual(self.page.evaluate('document.visibilityState'),'visible')
        finally:session.detach()

    def test_resume_empty_session_reuses_blank_despite_prior_home_entry(self):
        self.page.close();self.c.args.pop('tabId')
        self.c.home_state_file.write_text('{"homeOpened":true}',encoding='utf-8')
        count=len(self.c.pages)
        result=self.call('resume_shopping')
        self.assertTrue(result['confirmed'])
        self.assertEqual(result['recovery'],'reused-empty-blank')
        self.assertEqual(len(self.c.pages),count)
        self.assertEqual(self.other.url,'https://example.test/')
        selected=next(p for p in self.c.pages if self.c.tab_id(p)==result['state']['tabId'])
        self.assertEqual(selected.url,'https://www.taobao.com/')
        selected.evaluate('window.keepMe=99')
        self.assertEqual(self.call('resume_shopping')['recovery'],'reused-existing-tab')
        self.assertEqual(selected.evaluate('window.keepMe'),99)

    def test_resume_respects_protected_tab_budget(self):
        self.page.close();self.c.args.pop('tabId')
        for p in self.c.pages:
            if p.url=='about:blank':p.goto('https://example.test/manual')
        self.c.tab_budget.configure(2)
        count=len(self.c.pages)
        result=self.call('resume_shopping')
        self.assertFalse(result['confirmed'])
        self.assertIn('TAB_LIMIT_REACHED',result['reason'])
        self.assertEqual(len(self.c.pages),count)
        self.assertTrue(all(p.url.startswith('https://example.test/') for p in self.c.pages))

    def test_resume_verification_does_not_navigate_away(self):
        self.page.goto('https://login.taobao.com/')
        count=len(self.c.pages)
        with self.assertRaisesRegex(RuntimeError,'Verification/login'):
            self.call('resume_shopping')
        self.assertEqual(self.page.url,'https://login.taobao.com/')
        self.assertEqual(len(self.c.pages),count)

    def test_resume_unconfirmed_home_navigation_not_retried(self):
        self.page.close();self.c.args.pop('tabId')
        blank=next(p for p in self.c.pages if p.url=='about:blank')
        (self.c.out/'home-recovery-state.json').write_text(json.dumps({'status':'attempted','tabId':self.c.tab_id(blank)}),encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError,'without retry'):
            self.call('resume_shopping')
        self.assertEqual(blank.url,'about:blank')

    def test_resume_creates_home_without_overwriting_manual_pages(self):
        self.page.close();self.c.args.pop('tabId')
        for p in self.c.pages:
            if p.url=='about:blank':p.goto('https://example.test/manual')
        count=len(self.c.pages)
        result=self.call('resume_shopping')
        self.assertTrue(result['confirmed'])
        self.assertEqual(result['recovery'],'created-homepage-tab')
        self.assertEqual(len(self.c.pages),count+1)
        self.assertEqual(self.other.url,'https://example.test/')

    def test_background_read_then_native_action_recovers_bound_tab(self):
        self.other.bring_to_front()
        r=self.call('activate_shopping_tab',background=True)
        self.assertTrue(r['state']['focus']['bindingValid'])
        self.assertEqual(r['state']['focus']['nativeVisibility'],'hidden')
        self.assertEqual(self.other.evaluate('document.visibilityState'),'visible')
        self.assertTrue(self.call('set_sort',field='sales')['confirmed'])
        self.assertEqual(self.page.evaluate('document.visibilityState'),'visible')
        self.assertEqual(self.c.focus.info()['lastWindowRecovery']['beforeVisibility'],'hidden')
        self.assertEqual(self.page.evaluate('order'),'销量')
        self.c.args['tabId']=self.c.tab_id(self.other)
        with self.assertRaisesRegex(RuntimeError,'Unknown supported|NEEDS_TAB_SWITCH'):self.call('shopping_state')

    def test_background_rejects_unexpected_document_replacement(self):
        self.call('activate_shopping_tab',background=True)
        self.page.reload()
        with self.assertRaisesRegex(RuntimeError,'FOCUS_CHANGED'):self.call('shopping_state')

    def test_minimized_background_and_explicit_window_restore(self):
        self.page.bring_to_front();self.call('activate_shopping_tab',background=True)
        session=self.context.new_cdp_session(self.page)
        try:
            window=session.send('Browser.getWindowForTarget')['windowId']
            session.send('Browser.setWindowBounds',{'windowId':window,'bounds':{'windowState':'minimized'}})
            self.page.wait_for_timeout(150)
            r=self.call('shopping_state')
            self.assertEqual(r['focus']['window']['state'],'minimized')
            self.assertTrue(r['focus']['bindingValid'])
            r=self.call('activate_shopping_tab',background=True,restoreWindow=True)
            self.assertNotEqual(r['state']['focus']['window']['state'],'minimized')
            session.send('Browser.setWindowBounds',{'windowId':window,'bounds':{'windowState':'minimized'}})
            self.page.wait_for_timeout(150)
            self.assertTrue(self.call('set_sort',field='sales')['confirmed'])
            self.assertNotEqual(self.c.focus.window(self.page)['state'],'minimized')
            self.assertEqual(self.c.focus.info()['lastWindowRecovery']['beforeWindowState'],'minimized')
        finally:
            session.send('Browser.setWindowBounds',{'windowId':window,'bounds':{'windowState':'normal'}})
            session.detach()

    def test_explicit_binding_and_background_reads(self):
        with self.assertRaisesRegex(RuntimeError,'NEEDS_TAB_SWITCH'):self.call('set_sort',field='sales')
        self.assertTrue(self.activate()['confirmed'])
        self.assertIsNone(self.page.evaluate('window.__huoyanTabWatch||null'))
        self.assertEqual(self.page.evaluate('document.visibilityState'),'visible')
        self.assertEqual(self.other.evaluate('document.visibilityState'),'hidden')
        self.assertTrue(self.call('set_sort',field='sales')['confirmed'])
        self.other.bring_to_front();self.page.wait_for_timeout(60)
        with self.assertRaisesRegex(RuntimeError,'FOCUS_CHANGED'):self.call('shopping_state')
        self.assertEqual(self.page.evaluate('order'),'销量')

    def test_switch_during_wait_blocks_click_without_stealing_focus(self):
        self.activate()
        def switch(*a,**k):self.other.bring_to_front();self.page.wait_for_timeout(60)
        self.c.pause=switch
        with self.assertRaisesRegex(RuntimeError,'FOCUS_CHANGED'):self.call('set_sort',field='sales')
        self.assertEqual(self.page.evaluate('order'),'综合')
        self.assertEqual(self.other.evaluate('document.visibilityState'),'visible')

    def test_away_and_back_still_stops(self):
        self.activate()
        def switch(*a,**k):
            self.other.bring_to_front();self.page.wait_for_timeout(60)
            self.page.bring_to_front();self.page.wait_for_timeout(60)
        self.c.pause=switch
        with self.assertRaisesRegex(RuntimeError,'FOCUS_CHANGED'):self.call('set_sort',field='sales')
        self.assertEqual(self.page.evaluate('document.visibilityState'),'visible')
        self.assertEqual(self.page.evaluate('order'),'综合')
        self.c.pause=lambda *a,**k:0;self.activate()
        self.assertTrue(self.call('set_sort',field='sales')['confirmed'])

    def test_product_type_blocks_search_and_legacy_bypass(self):
        self.page.goto('https://item.taobao.com/item.htm?id=123');self.activate()
        with self.assertRaisesRegex(RuntimeError,'WRONG_PAGE_TYPE'):self.call('search_products',keyword='new',scope='global')
        with self.assertRaisesRegex(RuntimeError,'WRONG_PAGE_TYPE'):self.call('set_sort',field='sales')
        records=list_buttons(self.c,product_identity)['controls']
        self.c.args['controlId']=next(x['controlId'] for x in records if x['action']=='search')
        with self.assertRaisesRegex(RuntimeError,'WRONG_PAGE_TYPE'):click_button(self.c,product_identity)

    def test_detail_click_stops_when_user_changes_tab(self):
        self.page.goto('https://item.taobao.com/item.htm?id=123');self.activate()
        d=self.call('detail_state')['detail'];section=next(x for x in d['sections'] if x['label']=='参数')
        def switch(*a,**k):self.other.bring_to_front();self.page.wait_for_timeout(60)
        self.c.pause=switch
        with self.assertRaisesRegex(RuntimeError,'FOCUS_CHANGED'):self.call('open_detail_section',sectionId=section['sectionId'])
        self.assertTrue(self.page.locator('#params').is_hidden())
        self.assertEqual(self.other.evaluate('document.visibilityState'),'visible')
        self.assertEqual(self.page.evaluate('searches'),0)

    def test_shop_search_stops_before_edit_on_focus_change(self):
        self.page.goto('https://shop123.taobao.com/search.htm');self.activate()
        def switch(*a,**k):self.other.bring_to_front();self.page.wait_for_timeout(60)
        self.c.pause=switch
        with self.assertRaisesRegex(RuntimeError,'FOCUS_CHANGED'):self.call('search_shop_products',keyword='店内PLA')
        self.assertEqual(self.page.locator('[name=q]').input_value(),'PLA')
        self.assertEqual(self.page.evaluate('searches'),0)

    def test_popup_adoption_return_preserves_search_and_sort(self):
        self.activate();self.call('set_sort',field='sales');self.page.evaluate('window.keepMarker=42')
        s=self.call('shopping_state');row=next(x for x in s['controls'] if x['action']=='open_product')
        result=self.call('click_shopping_control',controlId=row['controlId'])
        self.assertTrue(result['confirmed']);product_tab=result['state']['tabId']
        self.assertEqual(result['state']['focus']['activeTabId'],product_tab)
        self.assertEqual(result['state']['focus']['originTabId'],self.c.tab_id(self.page))
        self.c.args['tabId']=product_tab
        with self.assertRaisesRegex(RuntimeError,'WRONG_PAGE_TYPE'):self.call('set_sort',field='sales')
        returned=self.call('return_to_results')
        self.assertEqual(returned['state']['tabId'],self.c.tab_id(self.page))
        self.assertEqual(returned['state']['sort']['field'],'sales');self.assertEqual(self.page.evaluate('keepMarker'),42)

    def test_same_tab_product_returns_using_verified_history(self):
        self.activate();self.page.locator('[data-product-card]').first.evaluate("e=>e.removeAttribute('target')")
        s=self.call('shopping_state');row=next(x for x in s['controls'] if x['action']=='open_product')
        r=self.call('click_shopping_control',controlId=row['controlId']);self.assertTrue(r['confirmed'])
        self.assertEqual(r['state']['tabId'],self.c.tab_id(self.page))
        r=self.call('return_to_results');self.assertEqual(r['state']['pageType'],'search')

    def test_closed_result_never_reopened_and_offline_comparison(self):
        self.activate();s=self.call('shopping_state');row=next(x for x in s['controls'] if x['action']=='open_product')
        r=self.call('click_shopping_control',controlId=row['controlId']);self.c.args['tabId']=r['state']['tabId']
        self.page.close();count=len(self.context.pages)
        with self.assertRaisesRegex(RuntimeError,'closed or changed'):self.call('return_to_results')
        self.assertEqual(len(self.context.pages),count)
        self.other.bring_to_front();self.assertEqual(self.call('compare_candidates')['candidates'],[])

    def test_focus_loss_survives_controller_reconnection(self):
        self.activate()
        self.other.bring_to_front();self.page.wait_for_timeout(60)
        self.page.bring_to_front();self.page.wait_for_timeout(60)
        args={**self.c.args,'operation':'set_sort','field':'sales'}
        result=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'huoyan.py'),'dispatch'],
            input=json.dumps({'command':'shopping','args':args}),capture_output=True,text=True,encoding='utf8',timeout=25)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('FOCUS_CHANGED',json.loads(result.stdout)['error'])
        self.assertEqual(self.page.evaluate('order'),'综合')

if __name__=='__main__':unittest.main(verbosity=2)
