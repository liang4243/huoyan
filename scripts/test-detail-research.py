"""Detail research integration, all HTTP requests fulfilled by local HTML fixtures."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from playwright.sync_api import sync_playwright
from python.huoyan_browser import Controller
from python.shopping_research import run

HTML='''<!doctype html><meta charset="utf-8"><title>Detail fixture</title>
<style>[hidden]{display:none!important}.skuItem li{display:inline-block;padding:8px} [data-detail-panel]{position:fixed;inset:50px;background:white;z-index:999} [data-detail-scroll]{height:180px;overflow:auto}.review{min-height:120px}.cover{position:fixed;inset:0;z-index:9999;background:white}</style>
<div class="skuItem"><span class="label">重量</span><li onclick="pick(this)">1kg</li><li class="disabled">2kg缺货</li></div><div data-product-price>￥36</div>
<button data-detail-section data-detail-region="gallery" onclick="tab(this)">参数</button><button data-detail-section data-detail-region="body" onclick="tab(this)">参数信息</button>
<button data-open-reviews onclick="document.querySelector('[data-detail-panel=reviews]').hidden=false">查看全部评价</button>
<div data-product-parameters><dl data-parameter-row><dt>材料</dt><dd>PLA</dd></dl><dl data-parameter-row><dt>线径</dt><dd>1.75mm</dd></dl></div>
<div data-product-description><p>商品通用详情</p><img data-product-image width=140 height=140 src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140'%3E%3C/svg%3E"></div>
<img data-product-main-image width=200 height=200 src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='200'%3E%3C/svg%3E"><button data-product-thumbnail onclick="document.querySelector('[data-product-main-image]').src='data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%22202%22 height=%22202%22%3E%3C/svg%3E'">图2</button>
<div data-question><div data-question-text>是否适合 A1？</div><div data-answer-text>可以使用</div><button data-more-answers onclick="this.parentElement.insertAdjacentHTML('beforeend','<p data-answer-text>建议先校准</p>')">更多回答</button></div>
<div data-delivery-summary>浙江杭州 至 广东某市 隐私街道88号</div><span data-service-text>7天无理由退货</span><button data-open-services onclick="document.querySelector('[data-detail-panel=services]').hidden=false">售后保障</button>
<input name="quantity" type="number" min="1" max="5" value="1"><button onclick="cart++">加入购物车</button><button onclick="orders++">立即购买</button>
<a href="https://shop123.taobao.com/" target="_blank">进店</a>
<div data-detail-panel="reviews" hidden><button data-close-detail onclick="this.parentElement.hidden=true">关闭</button><button data-review-filter data-review-group="type" aria-pressed="true" onclick="filter(this)">全部</button><button data-review-filter data-review-group="type" aria-pressed="false" onclick="filter(this)">有图</button>
<button data-review-menu class="sortByText--fixture" onclick="document.querySelector('#review-sort').hidden=false">默认排序</button><div id="review-sort" hidden><button data-review-filter data-review-group="sort" onclick="document.querySelector('.sortByText--fixture').innerText=this.innerText;this.parentElement.hidden=true">时间排序</button></div>
<div data-detail-scroll data-section="reviews"><article class="review" data-review><span class="userName--private">DO_NOT_EXPORT_USERNAME</span><p data-review-text>打印稳定</p><span data-review-meta>2026-10-01</span><span data-review-sku>1kg</span><p data-review-followup>追评依然正常</p></article><article class="review" data-review><p data-review-text>颜色准确</p></article><article class="review" data-review><p data-review-text>包装完整</p></article></div></div>
<div data-detail-panel="services" hidden><span data-service-text>退货说明</span><button data-close-detail onclick="this.parentElement.hidden=true">关闭</button></div>
<script>window.cart=window.orders=0;function pick(e){document.querySelectorAll('.skuItem li').forEach(x=>x.classList.remove('selected'));e.classList.add('selected')}function tab(e){document.querySelectorAll('[data-detail-section]').forEach(n=>n.setAttribute('aria-selected',n===e))}function filter(e){document.querySelectorAll('[data-review-filter]').forEach(n=>n.setAttribute('aria-pressed',n===e))}</script>'''


class DetailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='huoyan-detail-');cls.pw=sync_playwright().start()
        cls.context=cls.pw.chromium.launch_persistent_context(str(Path(cls.temp.name)/'profile'),
            executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True,args=['--no-proxy-server'])
        cls.context.route('**/*',lambda r:r.fulfill(content_type='text/html; charset=utf-8',body=HTML))

    @classmethod
    def tearDownClass(cls):cls.context.close();cls.pw.stop();cls.temp.cleanup()

    def setUp(self):
        self.page=self.context.new_page();self.page.goto('https://item.taobao.com/item.htm?id=123')
        self.c=Controller({'out':str(Path(self.temp.name)/self._testMethodName),'delayMin':0,'delayMax':0,
            'verificationTimeoutMs':400,'settleMs':0,'stableMs':0},self.context.browser).__enter__()
        self.c.pause=lambda *a,**k:0
        self.c.args['tabId']=self.c.tab_id(self.page);self.c.focus.activate(self.page)

    def tearDown(self):
        self.assertEqual(self.page.evaluate('cart+orders'),0);self.c.close();self.page.close()

    def call(self,op,**args):
        self.c.args={k:v for k,v in self.c.args.items() if k in ('out','tabId','delayMin','delayMax','verificationTimeoutMs','settleMs','stableMs')}
        self.c.args.update(operation=op,**args);return run(self.c)

    def test_initial_discovery_and_product_reuse_no_selection(self):
        r=self.call('detail_state')['detail'];self.assertEqual(r['selectedSku'],[])
        self.assertEqual(len(r['skuGroups'][0]['options']),2);self.assertTrue(r['skuGroups'][0]['options'][1]['disabled'])
        self.assertIn('open_reviews',[x['tool'] for x in r['availableActions']])
        self.assertFalse(any(x['action']=='review_filter' for x in r['controls']))
        self.c.args['item']='123';p=self.c.product();self.assertEqual(p['source'],'existing-tab');self.assertIn('detail',p)
        self.assertEqual(p['detail']['selectedSku'],[]);self.assertEqual(self.page.locator('.selected').count(),0)
        self.assertFalse(any('elementPath' in r for r in p['detail']['controls']))

    def test_scoped_sections_and_expired_control(self):
        d=self.call('detail_state')['detail'];sections=d['sections'];self.assertEqual(len(sections),2)
        self.assertNotEqual(sections[0]['sectionId'],sections[1]['sectionId'])
        r=self.call('open_detail_section',sectionId=sections[0]['sectionId']);self.assertTrue(r['confirmed'])
        with self.assertRaisesRegex(RuntimeError,'expired'):self.call('open_detail_section',sectionId=sections[1]['sectionId'])
        params=self.call('read_product_parameters');self.assertEqual(params['parameters'][0]['value'],'PLA')

    def test_reviews_filters_read_and_owned_close(self):
        r=self.call('open_reviews');self.assertTrue(r['confirmed']);d=r['state']['detail']
        self.assertTrue(d['panels'][0]['openedByTool']);self.assertEqual(len(d['reviews']),3)
        self.assertNotIn('DO_NOT_EXPORT_USERNAME',str(d))
        row=next(r for r in d['controls'] if r['label']=='有图')
        r=self.call('set_review_filter',options=[{'controlId':row['controlId'],'selected':True}]);self.assertTrue(r['confirmed'])
        r=self.call('read_reviews',limit=1);self.assertEqual(len(r['reviews']),1);self.assertEqual(r['reviews'][0]['followUp'],'追评依然正常')
        p=r['state']['detail']['panels'][0];self.assertTrue(self.call('close_detail_panel',panelId=p['panelId'])['confirmed'])
        self.page.locator('[data-detail-panel=reviews]').evaluate('e=>e.hidden=false')
        d=self.call('detail_state')['detail'];self.assertFalse(d['panels'][0]['openedByTool'])

    def test_review_click_menu_and_hidden_selection_evidence(self):
        r=self.call('open_reviews');menu=next(x for x in r['state']['detail']['controls'] if x['action']=='review_menu')
        r=self.call('open_review_menu',controlId=menu['controlId'],interaction='click');self.assertTrue(r['confirmed'])
        row=next(x for x in r['state']['detail']['controls'] if x['label']=='时间排序')
        r=self.call('set_review_filter',options=[{'controlId':row['controlId'],'selected':True}]);self.assertTrue(r['confirmed'])
        self.assertEqual(r['state']['detail']['reviewSort'][0]['label'],'时间排序')

    def test_unowned_panel_and_wrong_control_rejected(self):
        self.page.locator('[data-detail-panel=reviews]').evaluate('e=>e.hidden=false')
        d=self.call('detail_state')['detail'];self.assertFalse(d['panels'][0]['openedByTool'])
        with self.assertRaisesRegex(RuntimeError,'UNOWNED_PANEL'):self.call('close_detail_panel',panelId=d['panels'][0]['panelId'])
        d=self.call('detail_state')['detail'];row=next(r for r in d['controls'] if r['action']=='review_filter')
        with self.assertRaises(ValueError):self.call('open_detail_section',sectionId=row['controlId'])

    def test_questions_services_and_quantity(self):
        r=self.call('read_product_questions');self.assertEqual(len(r['questions'][0]['answers']),1)
        q=r['questions'][0]['questionId'];self.assertTrue(self.call('expand_question_answers',questionId=q)['confirmed'])
        r=self.call('read_delivery_services');self.assertNotIn('隐私街道',str(r['delivery']));self.assertIsNone(r['shipping'])
        service=next(r for r in r['state']['detail']['controls'] if r['action']=='open_services')
        r=self.call('read_delivery_services',controlId=service['controlId'],interaction='click');self.assertTrue(r['confirmed'])
        self.assertTrue(self.call('close_detail_panel',panelId=r['state']['detail']['panels'][0]['panelId'])['confirmed'])
        self.assertTrue(self.call('set_quantity',quantity=3)['confirmed'])
        with self.assertRaises(ValueError):self.call('set_quantity',quantity=8)

    def test_real_service_explanation_and_native_toggle_close(self):
        self.page.locator('[data-open-services]').evaluate('''e=>{const info=document.createElement('div');info.className='GuaranteeInfo--fixture';e.replaceWith(info);info.append(e);e.className='triggerWrap--fixture';e.onclick=()=>{
            const old=document.querySelector('.moreGuaranteeListWrap--fixture');if(old){old.remove();return}
            const d=document.createElement('div');d.className='moreGuaranteeListWrap--fixture';d.style='position:absolute;background:white';
            d.innerHTML='<div class="GuaranteeItem--fixture">退货运费按说明承担</div>';info.parentElement.append(d);
        }}''')
        d=self.call('detail_state')['detail'];control=next(x for x in d['controls'] if x['action']=='open_services')
        r=self.call('read_delivery_services',controlId=control['controlId']);self.assertTrue(r['confirmed'])
        self.assertIn('退货运费按说明承担',r['services'])
        panel=r['state']['detail']['panels'][0];self.assertEqual(panel['dismissal'],'trigger-toggle')
        self.assertTrue(self.call('close_detail_panel',panelId=panel['panelId'])['confirmed'])

    def test_real_style_question_drawer_and_no_user_identity_export(self):
        self.page.evaluate('''()=>{document.querySelector('[data-more-answers]').onclick=()=>{
          const d=document.createElement('div');d.className='leftDrawer--fixture askAnswerInfoDrawer--fixture';d.style='position:fixed;inset:0;background:white;z-index:999';
          d.innerHTML='<div class="closeWrap--fixture" onclick="this.parentElement.remove()">关闭</div><div class="AskAnswersWrap--fixture"><div class="qaItem--fixture"><div class="questionTitle--fixture">是否适合 A1？</div><span class="userNick--fixture">PRIVATE_QUESTION_AUTHOR</span><div class="answerContent--fixture">可以，先校准</div></div></div>';document.body.append(d);
        }}''')
        q=self.call('read_product_questions')['questions'][0]['questionId']
        r=self.call('expand_question_answers',questionId=q);self.assertTrue(r['confirmed'])
        self.assertEqual(r['state']['detail']['questions'][0]['answers'],['可以，先校准'])
        self.assertNotIn('PRIVATE_QUESTION_AUTHOR',str(r))
        self.assertTrue(self.call('close_detail_panel',panelId=r['state']['detail']['panels'][0]['panelId'])['confirmed'])

    def test_overlay_and_offscreen_are_distinct_and_blocked_click(self):
        self.page.locator('[data-open-reviews]').evaluate("e=>{e.style.position='absolute';e.style.top='2000px'}")
        d=self.call('detail_state')['detail'];r=next(r for r in d['controls'] if r['action']=='open_reviews')
        self.assertTrue(r['rendered']);self.assertFalse(r['inViewport']);self.assertTrue(r['needsScroll'])
        self.page.evaluate("()=>{let d=document.createElement('div');d.className='cover';document.body.append(d)}")
        d=self.call('detail_state')['detail'];r=next(r for r in d['controls'] if r['action']=='section')
        self.assertTrue(r['blockedByOverlay']);self.assertFalse(r['actionable'])
        with self.assertRaises(Exception):self.call('open_detail_section',sectionId=r['sectionId'])
        self.assertEqual(self.page.locator('[data-detail-section][aria-selected=true]').count(),0)

    def test_nested_loading_stops_and_no_document_scroll_under_panel(self):
        r=self.call('open_reviews');d=r['state']['detail'];nested=next(x for x in d['containers'] if x['region']=='reviews-panel')
        original=self.page.evaluate('scrollY')
        r=self.call('load_more_detail',containerId=nested['containerId'],maxSteps=5)
        self.assertIn(r['stopReason'],['NO_NEW_CONTENT','AT_BOTTOM']);self.assertEqual(self.page.evaluate('scrollY'),original)
        d=self.call('detail_state')['detail'];body=next(x for x in d['containers'] if x['region']=='body')
        # Body at bottom may safely return AT_BOTTOM; otherwise it must reject panel-obscured scrolling.
        if not body['atBottom']:
            with self.assertRaisesRegex(RuntimeError,'BLOCKED_BY_PANEL'):self.call('load_more_detail',containerId=body['containerId'])

    def test_reviews_wait_for_transient_overlay_without_duplicate_click(self):
        self.page.evaluate('''()=>{window.reviewClicks=0;const b=document.querySelector('[data-open-reviews]'),open=b.onclick;
            b.onclick=()=>{reviewClicks++;open.call(b)};
            const cover=document.createElement('div');cover.className='cover';document.body.append(cover);setTimeout(()=>cover.remove(),2100)}''')
        r=self.call('open_reviews');self.assertTrue(r['confirmed'])
        self.assertEqual(self.page.evaluate('reviewClicks'),1)

    def test_reviews_noop_is_unconfirmed_and_never_reclicked(self):
        self.page.evaluate("()=>{window.reviewClicks=0;document.querySelector('[data-open-reviews]').onclick=()=>{reviewClicks++}}")
        result=self.call('open_reviews')
        self.assertFalse(result['confirmed']);self.assertEqual(result['clicks'],1)
        self.assertEqual(result['state']['detail']['panels'],[])
        self.assertEqual(self.page.evaluate('reviewClicks'),1)

    def test_reviews_sku_change_while_waiting_stops_before_click(self):
        self.page.evaluate("()=>{window.reviewClicks=0;document.querySelector('[data-open-reviews]').addEventListener('click',()=>{reviewClicks++})}")
        self.c.pause=lambda *a,**kw:self.page.locator('.skuItem li').first.evaluate('e=>pick(e)')
        with self.assertRaisesRegex(RuntimeError,'Page state changed while waiting'):
            self.call('open_reviews')
        self.assertEqual(self.page.evaluate('reviewClicks'),0)
        self.assertTrue(self.page.locator('[data-detail-panel=reviews]').is_hidden())
        self.assertEqual(self.page.locator('.selected').inner_text(),'1kg')

    def test_reviews_sticky_bar_and_persistent_overlay_diagnostics(self):
        self.page.evaluate('''()=>{document.body.style.minHeight='4000px';const b=document.querySelector('[data-open-reviews]');b.style='position:absolute;top:2200px';
            const bar=document.createElement('div');bar.style='position:fixed;bottom:0;left:0;right:0;height:180px;z-index:100;background:white';document.body.append(bar)}''')
        self.assertTrue(self.call('open_reviews')['confirmed'])
        d=self.call('detail_state')['detail'];self.call('close_detail_panel',panelId=d['panels'][0]['panelId'])
        self.page.evaluate("()=>{const cover=document.createElement('div');cover.className='cover';document.body.append(cover)}")
        with self.assertRaisesRegex(RuntimeError,'CONTROL_NOT_ACTIONABLE.*no click delivered.*blockedByOverlay.*true'):
            self.call('open_reviews')
        self.assertTrue(self.page.locator('[data-detail-panel=reviews]').is_hidden())

    def test_changed_sku_invalidates_review_control_and_candidate_has_sources(self):
        r=self.call('open_reviews');row=next(x for x in r['state']['detail']['controls'] if x['label']=='有图')
        self.page.locator('.skuItem li').first.evaluate("e=>pick(e)")
        with self.assertRaisesRegex(RuntimeError,'state changed'):self.call('set_review_filter',options=[{'controlId':row['controlId'],'selected':True}])
        r=self.call('save_candidate')['candidate'];self.assertEqual(r['selectedSku'],['1kg']);self.assertIn('researchEvidence',r)
        self.assertNotIn('DO_NOT_EXPORT_USERNAME',str(r));self.assertIsNone(r['finalPrice'])

    def test_collage_respects_review_source_and_retains_sku(self):
        self.call('select_sku',sku=['1kg'])
        self.page.locator('[data-review]').first.evaluate('''e=>{let img=document.createElement('img');img.setAttribute('data-review-image','');img.width=160;img.height=160;img.src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3C/svg%3E";e.append(img)}''')
        self.call('open_reviews')
        self.c.args.update(item='123',sku=['1kg'],imageSources=['review'],maxImages=2)
        r=self.c.sku_images();self.assertEqual(r['imageCount'],1)
        self.assertEqual(r['sources'][0]['source'],'review');self.assertEqual(r['sources'][0]['skuAssociation'],'unverified')
        self.assertEqual(r['detail']['selectedSku'],['1kg'])

    def test_missing_capabilities_and_noop_not_success(self):
        self.page.locator('[data-open-reviews]').evaluate('e=>e.remove()')
        with self.assertRaisesRegex(RuntimeError,'UNSUPPORTED'):self.call('open_reviews')
        self.page.locator('[data-more-answers]').evaluate('e=>e.onclick=()=>{}')
        q=self.call('read_product_questions')['questions'][0]['questionId']
        self.assertFalse(self.call('expand_question_answers',questionId=q)['confirmed'])

    def test_shop_reuse_preserves_existing_page(self):
        shop=self.context.new_page();shop.goto('https://shop123.taobao.com/?spm=tracking')
        shop.evaluate('window.keepShopState=123');self.c.focus.activate(self.page)
        try:
            count=len(self.context.pages);r=self.call('open_product_shop')
            self.assertEqual(r['source'],'existing-shop-tab');self.assertEqual(len(self.context.pages),count)
            self.assertEqual(shop.evaluate('window.keepShopState'),123)
        finally:self.c.focus.activate(self.page);shop.close()


if __name__=='__main__':unittest.main(verbosity=2)
