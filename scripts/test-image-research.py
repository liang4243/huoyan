"""Local browser tests for overview -> exact single image, with no live traffic."""
import sys,json,io,base64,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PIL import Image
from playwright.sync_api import sync_playwright,Locator
from python.huoyan_browser import Controller
from python.shopping_research import run

def image_bytes(color,size):
    output=io.BytesIO();Image.new('RGB',size,color).save(output,'PNG');return output.getvalue()
ASSETS={'red.png':image_bytes('red',(800,800)),'blue.png':image_bytes('blue',(600,600)),
        'detail.png':image_bytes('green',(790,1053))}
HTML='''<!doctype html><meta charset=utf-8><title>Image overview fixture</title><style>li{display:inline-block}[hidden]{display:none!important}</style>
<div class=skuItem><span class=label>颜色</span><li class=selected onclick="pick(this)"><img width=40 height=40 src="https://img.example/red.png">红色</li><li class=disabled onclick="danger++"><img width=40 height=40 src="https://img.example/blue.png">蓝色</li></div>
<div data-product-price>￥36</div><input name=quantity value=1>
<img data-product-main-image width=200 height=200 src="https://img.example/red.png">
<div class=thumbnail><img width=40 height=40 src="https://img.example/red.png"><img width=40 height=40 src="https://img.example/blue.png"></div>
<div class=desc-root><div style="height:1000px"></div><img width=200 height=267 src="https://img.example/detail.png"><img width=200 height=200 src="https://img.example/broken.png"></div>
<button onclick="danger++">加入购物车</button><a href="https://shop123.taobao.com/" onclick="danger++">客服</a>
<script>window.danger=0;function pick(e){danger++;document.querySelectorAll('li').forEach(n=>n.classList.remove('selected'));e.classList.add('selected')}</script>'''

class ImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='huoyan-image-');cls.pw=sync_playwright().start()
        cls.context=cls.pw.chromium.launch_persistent_context(str(Path(cls.temp.name)/'profile'),executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True,args=['--no-proxy-server'])
    @classmethod
    def tearDownClass(cls):cls.context.close();cls.pw.stop();cls.temp.cleanup()
    def setUp(self):
        self.requests=[]
        def route(r):
            self.requests.append(r.request.url);asset=r.request.url.rsplit('/',1)[-1]
            if 'img.example' in r.request.url:r.fulfill(content_type='image/png',body=ASSETS.get(asset,b'broken'))
            else:r.fulfill(content_type='text/html; charset=utf-8',body=HTML)
        self.page=self.context.new_page();self.page.route('**/*',route);self.page.goto('https://item.taobao.com/item.htm?id=123');self.page.wait_for_load_state('networkidle')
        self.args={'out':str(Path(self.temp.name)/self._testMethodName),'delayMin':0,'delayMax':0};self.c=Controller(self.args.copy(),self.context.browser).__enter__();self.tab=self.c.tab_id(self.page);self.c.focus.activate(self.page)
    def tearDown(self):self.assertEqual(self.page.evaluate('danger'),0);self.c.close();self.page.close()
    def call(self,operation,**kw):self.c.args={**self.args,'tabId':self.tab,'operation':operation,**kw};return run(self.c)
    def test_overview_interleaves_sources_without_requests_or_sku_clicks(self):
        before=list(self.requests);r=self.call('product_image_overview',maxImages=4)
        self.assertEqual([x['source'] for x in r['images']],['sku','gallery','description','sku']);self.assertEqual(r['nextOffset'],4)
        self.assertEqual(r['sourceCounts'],{'sku':2,'gallery':2,'description':2});self.assertEqual(r['selectedSku'],['红色']);self.assertEqual(self.page.locator('[name=quantity]').input_value(),'1')
        self.assertEqual(self.requests,before);self.assertEqual(len(self.context.pages),2)
        self.assertTrue(r['images'][3]['disabled']);self.assertIn('not a full SKU',r['images'][3]['skuAssociation'])
    def test_single_image_returns_exact_original_resource_not_thumbnail(self):
        r=self.call('product_image_overview',maxImages=3);one=self.call('read_product_image',overviewId=r['overviewId'],index=1)
        im=Image.open(io.BytesIO(base64.b64decode(one['imageBase64'])));self.assertEqual(im.size,(800,800));self.assertEqual(im.getpixel((0,0)),(255,0,0));self.assertEqual(one['image']['captureMethod'],'loaded-resource')
    def test_pagination_keeps_old_sheet_and_rejects_unshown_index(self):
        first=self.call('product_image_overview',maxImages=3);second=self.call('product_image_overview',offset=3,maxImages=2)
        self.assertEqual([x['index'] for x in second['images']],[4,5]);self.assertEqual(self.call('read_product_image',overviewId=first['overviewId'],index=1)['image']['index'],1)
        with self.assertRaisesRegex(ValueError,'actually returned'):self.call('read_product_image',overviewId=second['overviewId'],index=1)
    def test_changed_sku_and_changed_source_rejected(self):
        r=self.call('product_image_overview',maxImages=3)
        self.page.locator('li').evaluate_all("es=>{es[0].classList.remove('selected');es[1].classList.add('selected')}")
        with self.assertRaisesRegex(RuntimeError,'PRODUCT_CHANGED'):self.call('read_product_image',overviewId=r['overviewId'],index=1)
        self.page.locator('li').evaluate_all("es=>{es[1].classList.remove('selected');es[0].classList.add('selected')}")
        self.page.locator('.skuItem img').first.evaluate("e=>e.src='https://img.example/blue.png'");self.page.wait_for_timeout(100)
        with self.assertRaisesRegex(RuntimeError,'STALE_IMAGE'):self.call('read_product_image',overviewId=r['overviewId'],index=1)
    def test_failed_image_has_placeholder_and_cannot_be_returned(self):
        r=self.call('product_image_overview',offset=3,maxImages=3);bad=next(x for x in r['images'] if not x['ready']);self.assertIn('error',bad)
        with self.assertRaisesRegex(RuntimeError,'STALE_IMAGE|IMAGE_UNAVAILABLE'):self.call('read_product_image',overviewId=r['overviewId'],index=bad['index'])
    def test_hidden_images_and_title_are_not_invented_sources(self):
        self.page.locator('.skuItem img').first.evaluate('e=>e.hidden=true')
        r=self.call('product_image_overview',imageSources=['sku']);self.assertEqual(r['totalLoadedImages'],1);self.assertEqual(r['images'][0]['skuOptions'],['蓝色'])
    def test_svg_fallback_restores_nested_and_document_scroll(self):
        svg="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='200'%3E%3Crect width='200' height='200' fill='purple'/%3E%3C/svg%3E"
        self.page.locator('.desc-root').evaluate("(e,src)=>{e.innerHTML='<div style=\"height:600px\"></div><img width=200 height=200 src=\"'+src+'\">';e.style.cssText='height:250px;overflow:auto';e.scrollTop=80}",svg)
        self.page.wait_for_function("document.querySelector('.desc-root img').naturalWidth>0");self.page.evaluate('scrollTo(0,50)')
        before=self.page.evaluate("({doc:scrollY,inner:document.querySelector('.desc-root').scrollTop})")
        r=self.call('product_image_overview',imageSources=['description'],allowScreenshot=True);self.assertEqual(r['images'][0]['captureMethod'],'rendered-screenshot')
        self.assertEqual(self.page.evaluate("({doc:scrollY,inner:document.querySelector('.desc-root').scrollTop})"),before)
    def test_invalid_inputs_and_unknown_overview_are_rejected(self):
        for values in [{'maxImages':49},{'offset':-1},{'imageSources':['avatar']},{'allowScreenshot':'yes'}]:
            with self.assertRaises(ValueError):self.call('product_image_overview',**values)
        with self.assertRaisesRegex(RuntimeError,'STALE_IMAGE'):self.call('read_product_image',overviewId='missing',index=1)
    def test_screenshot_fallback_does_not_return_covering_overlay(self):
        svg="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='200'%3E%3C/svg%3E"
        self.page.locator('.desc-root').evaluate("(e,src)=>e.innerHTML='<img width=200 height=200 src=\"'+src+'\">'",svg)
        self.page.wait_for_function("document.querySelector('.desc-root img').naturalWidth>0")
        self.page.evaluate("()=>document.body.insertAdjacentHTML('beforeend','<div style=\"position:fixed;inset:0;z-index:999999;background:white\"></div>')")
        with self.assertRaisesRegex(RuntimeError,'IMAGE_UNAVAILABLE'):self.call('product_image_overview',imageSources=['description'],allowScreenshot=True)
    def test_default_never_scrolls_screenshots_or_rewrites_dom_on_resource_failure(self):
        svg="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='200'%3E%3C/svg%3E"
        self.page.locator('.desc-root').evaluate("(e,src)=>e.insertAdjacentHTML('beforeend','<img width=200 height=200 src=\"'+src+'\">')",svg)
        self.page.wait_for_function("document.querySelector('.desc-root img:last-child').naturalWidth>0");self.page.evaluate('scrollTo(0,90)')
        before=self.page.evaluate('({html:document.documentElement.outerHTML,scroll:scrollY,url:location.href})');requests=list(self.requests);pages=len(self.context.pages)
        with patch.object(Locator,'screenshot',side_effect=AssertionError('Default must not screenshot')),patch.object(Locator,'scroll_into_view_if_needed',side_effect=AssertionError('Default must not scroll')):
            r=self.call('product_image_overview',imageSources=['description'])
        self.assertFalse(r['allowScreenshot']);self.assertEqual(r['screenshotCount'],0);self.assertEqual(r['imageCount'],1);self.assertEqual(r['unavailableCount'],2)
        self.assertTrue(any('IMAGE_RESOURCE_UNAVAILABLE' in x.get('error','') for x in r['images']))
        self.assertEqual(self.page.evaluate('({html:document.documentElement.outerHTML,scroll:scrollY,url:location.href})'),before);self.assertEqual(self.requests,requests);self.assertEqual(len(self.context.pages),pages)

if __name__=='__main__':unittest.main(verbosity=2)
