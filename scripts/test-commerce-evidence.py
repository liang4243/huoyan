"""Structured commerce evidence and bounded list loading; local fixtures only."""
import sys,json,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from playwright.sync_api import sync_playwright
from python.huoyan_browser import Controller,dom_script,load_json
from python.shopping_research import run

IMAGE="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='200'%3E%3C/svg%3E"
CARD='''<article data-product-card><a href="https://item.taobao.com/item.htm?id=123"><h3 data-product-title>商品标题 下单9999人</h3></a>
<span class="realSales--fixture">20万+人付款</span><div class="tradeInfoWrapper--fixture">2小时下单600+人</div><span>5万+人看过</span>
<div class="shopName--fixture"><span>品牌旗舰</span><span>回头客10万</span><span class="shopNameText--fixture">测试官方旗舰店</span></div>
<span>明日达</span><span>24小时内发</span><span>退货宝</span><span>国补后</span><span>国家补贴15%</span><span>未知新标签</span>
<div data-shipping-origin>广东东莞</div><div data-ranking>数码热销榜第2名</div><span data-selling-point>铝合金</span>
<img width=200 height=200 src="IMAGE"><span hidden>回头客999万</span></article>'''.replace('IMAGE',IMAGE)
SEARCH='''<!doctype html><meta charset="utf-8"><title>Commerce card fixture</title><style>[hidden]{display:none!important}</style>
<form onsubmit="event.preventDefault()"><input name=q value=PLA><button>搜索</button></form>
<button role=tab aria-selected=true>综合</button><div id=cards>'''+CARD+'''</div><div style="height:4500px"></div>'''
DETAIL='''<!doctype html><meta charset="utf-8"><title>Commerce detail fixture</title><style>[hidden]{display:none!important}.skuItem li{display:inline-block;padding:8px}</style>
<header><img src="https://private.example/avatar" alt=PRIVATE_ACCOUNT><span data-private>PRIVATE_ACCOUNT</span></header>
<div data-detail-shop><a data-shop-name href="https://shop123.taobao.com/">测试官方旗舰店</a><span>品牌旗舰 回头客10万</span><div data-shop-rating>描述相符4.9 服务体验4.8 物流体验4.7</div></div>
<div data-product-metrics>近30天20万+人付款 2小时下单600+人 已售1.2万件</div>
<div data-product-price><s>¥299</s><span id=price>¥199</span><span>优惠后</span></div><div data-product-offer>满200减20 12期免息 国家补贴15%</div>
<div data-fulfillment>明日达 24小时内发 满99元包邮 运费:8元</div>
<div data-delivery-summary>浙江杭州 至 广东某市 私密街道88号 13812345678</div><div data-delivery-destination>PRIVATE_DESTINATION</div>
<span data-service-text>7天无理由退货 30天价保 正品保障 全国联保</span>
<div data-product-review-summary>用户评价(1.2万+) 好评率99.2%<article data-review><span>PRIVATE_BUYER</span><p data-review-text>PRIVATE_REVIEW_WORDS</p></article></div>
<div class=skuItem><span class=label>规格</span><li class=selected onclick="pick(this,'199')">1kg</li><li onclick="pick(this,'299')">2kg</li></div>
<img data-product-main-image width=200 height=200 src="IMAGE">
<button onclick=danger++>加入购物车</button><button onclick=danger++>领取优惠券</button>
<script>window.danger=0;function pick(e,v){document.querySelectorAll('.skuItem li').forEach(x=>x.classList.remove('selected'));e.classList.add('selected');document.querySelector('#price').innerText='¥'+v}</script>'''.replace('IMAGE',IMAGE)


class CommerceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='huoyan-commerce-');cls.pw=sync_playwright().start()
        cls.context=cls.pw.chromium.launch_persistent_context(str(Path(cls.temp.name)/'profile'),executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True,args=['--no-proxy-server'])
        cls.context.route('**/*',lambda r:r.fulfill(content_type='text/html; charset=utf-8',body=DETAIL if 'item.taobao.com' in r.request.url else SEARCH))
    @classmethod
    def tearDownClass(cls):cls.context.close();cls.pw.stop();cls.temp.cleanup()
    def setUp(self):
        self.page=self.context.new_page();self.page.goto('https://s.taobao.com/search?q=PLA')
        self.base={'out':str(Path(self.temp.name)/self._testMethodName),'delayMin':0,'delayMax':0,'settleMs':150,'stableMs':50,'verificationTimeoutMs':1000}
        self.c=Controller(self.base.copy(),self.context.browser).__enter__();self.c.pause=lambda *a,**kw:0;self.tab=self.c.tab_id(self.page);self.c.focus.activate(self.page)
    def tearDown(self):self.assertEqual(self.page.evaluate('window.danger||0'),0);self.c.close();self.page.close()
    def call(self,op,**kw):self.c.args={**self.base,'tabId':self.tab,'operation':op,**kw};return run(self.c)
    def detail(self):self.page.goto('https://item.taobao.com/item.htm?id=123');self.c.focus.activate(self.page);return self.call('detail_state')

    def test_card_clean_shop_independent_metrics_and_labels(self):
        p=self.call('list_products')['products'][0];d=p['commerce'];self.assertEqual(p['shop'],'测试官方旗舰店')
        metrics={m['kind']:m for m in d['metrics']};self.assertEqual(metrics['payments']['numericValue'],200000);self.assertEqual(metrics['payments']['comparison'],'at-least')
        self.assertEqual(metrics['orders']['numericValue'],600);self.assertEqual(metrics['orders']['periodHours'],2);self.assertEqual(metrics['views']['numericValue'],50000)
        self.assertEqual(d['shop']['repeatCustomers'][0]['numericValue'],100000);self.assertEqual(d['shop']['repeatCustomers'][0]['scope'],'shop')
        self.assertEqual(d['fulfillment']['arrivalPromises'][0]['raw'],'明日达');self.assertEqual(d['fulfillment']['dispatchPromises'][0]['raw'],'24小时内发')
        self.assertIn('未知新标签',[e['raw'] for e in d['labels']]);self.assertEqual(d['sellingPoints'],['铝合金']);self.assertIn('广东东莞',d['fulfillment']['origins'])
        self.assertTrue(p['controlIds']);self.assertTrue(p['inViewport'])
    def test_title_and_hidden_badges_do_not_invent_metrics(self):
        self.page.locator('.realSales--fixture,.tradeInfoWrapper--fixture,.shopName--fixture').evaluate_all('es=>es.forEach(e=>e.remove())')
        self.page.locator('article > span').evaluate_all('es=>es.forEach(e=>e.remove())')
        d=self.call('list_products')['products'][0]['commerce'];self.assertEqual(d['metrics'],[]);self.assertEqual(d['shop']['repeatCustomers'],[])
        self.assertEqual(d['coverage']['imageOnlyText'],'not OCRed')
    def test_detail_summary_privacy_and_price_roles(self):
        s=self.detail();d=s['detail']['commerce'];self.assertEqual(d,s['product']['commerce'])
        metrics={m['kind']:m for m in d['metrics']};self.assertEqual(metrics['orders']['periodHours'],2);self.assertEqual(metrics['payments']['period'],'近30天');self.assertEqual(metrics['sales']['unit'],'items')
        self.assertEqual(metrics['reviews']['numericValue'],12000);self.assertEqual(metrics['positive-rate']['numericValue'],99.2)
        self.assertEqual(len(d['shop']['ratings']),3);self.assertEqual(d['fulfillment']['origins'],['浙江杭州'])
        self.assertTrue(any(f['raw']=='满99元包邮' and f['conditional'] and f['amount'] is None for f in d['fulfillment']['shippingFees']))
        self.assertTrue(any(f['amount']==8 for f in d['fulfillment']['shippingFees']))
        self.assertTrue(any(p['amount']==299 and p['role']=='struck-through' for p in d['pricing']['priceClaims']))
        self.assertTrue(any(p['amount']==199 and p['role']=='displayed-unverified' for p in d['pricing']['priceClaims']))
        raw=json.dumps(d,ensure_ascii=False)
        for forbidden in ['PRIVATE_ACCOUNT','PRIVATE_BUYER','PRIVATE_REVIEW_WORDS','PRIVATE_DESTINATION','私密街道','13812345678','private.example']:self.assertNotIn(forbidden,raw)
        self.assertIsNone(d['pricing']['finalPrice']);self.assertFalse(d['pricing']['eligibilityVerified'])
    def test_actions_and_candidate_refresh_current_sku_evidence(self):
        self.detail();r=self.call('select_sku',sku=['2kg']);self.assertTrue(r['confirmed']);self.assertEqual(r['state']['detail']['commerce']['selectedSku'],['2kg'])
        offer=self.call('read_selected_offer');self.assertEqual(offer['commerce']['selectedSku'],['2kg'])
        saved=self.call('save_candidate')['candidate']['researchEvidence']['commerce'];self.assertEqual(saved['selectedSku'],['2kg'])
        self.assertTrue(any(p['amount']==299 and p['role']=='displayed-unverified' for p in saved['pricing']['priceClaims']))
        delivery=self.call('read_delivery_services');self.assertEqual(delivery['fulfillment']['destination'],'redacted')
        cache=load_json(self.c.out/'product-tabs.json',{});product=next(iter(cache['products'].values()));self.assertIn('commerce',product['cache'])
    def test_zero_is_distinct_from_not_observed(self):
        self.page.locator('.realSales--fixture').inner_text();self.page.locator('.realSales--fixture').evaluate("e=>e.innerText='0人付款'")
        d=self.call('list_products')['products'][0]['commerce'];self.assertEqual(next(m for m in d['metrics'] if m['kind']=='payments')['numericValue'],0)
        self.page.locator('.realSales--fixture').evaluate('e=>e.remove()');d=self.call('list_products')['products'][0]['commerce'];self.assertFalse(any(m['kind']=='payments' for m in d['metrics']))
    def test_wait_replacement_stops_before_scroll(self):
        def replace(*a,**kw):self.page.locator('article a').evaluate("e=>e.href='https://item.taobao.com/item.htm?id=456'")
        self.c.pause=replace;old=self.page.evaluate('scrollY');r=self.call('load_more');self.assertFalse(r['confirmed']);self.assertFalse(r['scrolled']);self.assertEqual(r['code'],'LIST_CHANGED');self.assertEqual(self.page.evaluate('scrollY'),old)
    def test_scroll_image_update_is_loading_without_new_products(self):
        self.page.evaluate("()=>{addEventListener('scroll',()=>{document.querySelector('article img').src="+json.dumps(IMAGE.replace("width='200'","width='202'").replace("height='200'","height='202'"))+"},{once:true})}")
        r=self.call('load_more');self.assertTrue(r['confirmed']);self.assertEqual(r['newProductIds'],[]);self.assertEqual(r['loadEvidence']['imageChangedProductIds'],['123'])
    def test_scroll_replacement_not_counted_as_append(self):
        self.page.evaluate("()=>addEventListener('scroll',()=>document.querySelector('article a').href='https://item.taobao.com/item.htm?id=456',{once:true})")
        r=self.call('load_more');self.assertFalse(r['confirmed']);self.assertEqual(r['code'],'LIST_REPLACED');self.assertEqual(r['newProductIds'],[]);self.assertEqual(r['loadEvidence']['removedProductIds'],['123'])
    def test_scroll_real_append_confirmed(self):
        self.page.evaluate("()=>addEventListener('scroll',()=>{const a=document.createElement('a');a.href='https://item.taobao.com/item.htm?id=456';a.innerText='新商品 ￥20';document.querySelector('#cards').append(a)},{once:true})")
        r=self.call('load_more');self.assertTrue(r['confirmed']);self.assertEqual(r['newProductIds'],['456'])
    def test_failed_image_is_not_successful_loading(self):
        self.page.evaluate("()=>addEventListener('scroll',()=>document.querySelector('article img').src='data:image/png,broken',{once:true})")
        r=self.call('load_more');self.assertFalse(r['confirmed']);self.assertEqual(r['loadEvidence']['imageChangedProductIds'],['123']);self.assertEqual(r['loadEvidence']['readyImageChangedProductIds'],[])
    def test_wait_query_change_stops_before_scroll(self):
        self.c.pause=lambda *a,**k:self.page.locator('[name=q]').fill('NEW')
        r=self.call('load_more');self.assertFalse(r['confirmed']);self.assertEqual(r['code'],'LIST_CHANGED');self.assertFalse(r['scrolled'])

    def test_real_template_shop_grade_score_and_product_repeat_scope(self):
        self.detail()
        self.page.locator('[data-detail-shop],[data-product-metrics],[data-product-review-summary]').evaluate_all('es=>es.forEach(e=>e.remove())')
        self.page.evaluate('''html=>document.body.insertAdjacentHTML('afterbegin',html)''','''<div class="shopHeader--fixture"><span class="shopName--fixture">魔创科技</span><div class="StoreComprehensiveRating--fixture">4.6</div><span>好评率99%</span><span>平均20小时发货</span><span>平均2天退款</span><img class="creditLevelIconImg--fixture" width=78 height=24 src="'''+IMAGE+'''"></div><div class="ItemTitle--fixture"><div class="subTitleInnerWrap--fixture">已售 1万+ 回头客379人 超400人加购</div></div><div class="Comments--fixture"><div class="titleWrapper--fixture">用户评价·1000+ 近3个月好评率高达100.0%</div></div><div id="description"><p>图文详情参数说明</p><img width=200 height=200 src="'''+IMAGE+'''"></div>''')
        r=self.call('read_product_evidence',includeLevelImage=False);d=r['commerce'];self.assertEqual(d['shop']['name'],'魔创科技')
        self.assertEqual(d['shop']['ratings'][0]['numericValue'],4.6);self.assertIsNone(d['shop']['level']['text']);self.assertEqual(d['shop']['level']['status'],'image-only-unverified')
        self.assertEqual(len(d['shop']['performance']),2);self.assertFalse(d['shop']['performance'][0]['isPromise'])
        self.assertEqual(next(m for m in d['metrics'] if m['kind']=='repeat-customers')['scope'],'product');self.assertEqual(d['shop']['repeatCustomers'],[])
        cart=next(m for m in d['metrics'] if m['kind']=='cart-additions');self.assertEqual(cart['numericValue'],400);self.assertEqual(cart['comparison'],'greater-than')
        rates=[m for m in d['metrics'] if m['kind']=='positive-rate'];self.assertEqual({m['scope'] for m in rates},{'shop','product'});self.assertTrue(any(m['period']=='近3个月' for m in rates))
        self.assertIn('图文详情参数说明',r['descriptions']);self.assertTrue(any(i['region']=='description' for i in r['images']))
    def test_level_image_is_actual_image_and_never_score_inference(self):
        self.detail();self.page.evaluate('''src=>document.body.insertAdjacentHTML('afterbegin','<img data-shop-level alt="三钻" width=78 height=24 src="'+src+'">')''',IMAGE)
        self.page.wait_for_function('document.querySelector("[data-shop-level]").naturalWidth>0')
        r=self.call('read_product_evidence',includeLevelImage=True);self.assertEqual(r['commerce']['shop']['level']['text'],'三钻');self.assertTrue(r['levelImageBase64']);self.assertEqual(r['levelImage']['status'],'captured-visible-level-icon')
        self.assertNotIn('levelImageBase64',self.call('read_product_evidence',includeLevelImage=False))

    def test_descv8_images_are_description_and_collage_source(self):
        self.detail();self.page.evaluate('''src=>document.body.insertAdjacentHTML('beforeend','<div class="desc-root"><div class="descV8-container"><p>descV8 图文说明</p><div class="descV8-singleImage"><img class="descV8-singleImage-image" width=200 height=200 src="'+src+'"></div></div></div>')''',IMAGE.replace("width='200'","width='240'").replace("height='200'","height='240'"))
        self.page.wait_for_function('document.querySelector(".descV8-singleImage-image").naturalWidth>0')
        r=self.call('read_product_evidence',includeLevelImage=False);self.assertIn('descV8 图文说明',r['descriptions'])
        self.assertTrue(any(i['region']=='description' and i['width']==240 for i in r['images']));self.assertTrue(any(i['region']=='description' for i in r['commerce']['media']['images']))
        self.page.evaluate('''()=>{document.body.insertAdjacentHTML('beforeend','<div style="height:1200px"></div>');const e=document.querySelector('.skuItem li');e.addEventListener('click',()=>scrollTo(0,80));scrollTo(0,0)}''')
        original_scroll=self.page.evaluate('scrollY')
        self.c.args.update(item='123',sku=['1kg'],maxImages=1,imageSources=['description'])
        collage=self.c.sku_images();self.assertEqual(collage['imageCount'],1);self.assertEqual(collage['sources'][0]['source'],'description');self.assertEqual(collage['detail']['selectedSku'],['1kg'])
        self.assertEqual(self.page.evaluate('scrollY'),original_scroll)

    def reputation_fixture(self,opens=True):
        self.detail()
        self.page.evaluate('''html=>document.body.insertAdjacentHTML('afterbegin',html)''','''<div class="shopHeader--fixture"><a href="https://shop123.taobao.com/" onclick="danger++;event.preventDefault()"><img data-open-shop-reputation width=78 height=24 src="'''+IMAGE+'''" onmouseenter="'''+("document.querySelector('[data-shop-reputation-panel]').hidden=false" if opens else '')+'''"></a><div data-shop-reputation-panel hidden><div class="shopItem--fixture"><span>综合体验</span><b>4.6</b></div><div class="evaluateItem--fixture"><span>宝贝质量</span><b>5.0</b></div><div class="evaluateItem--fixture"><span>物流速度</span><b>4.4</b></div><div class="evaluateItem--fixture"><span>服务保障</span><b>4.4</b></div><button onclick="danger++">和我联系</button><span data-private>PRIVATE_REPUTATION</span></div></div>''')
        self.page.mouse.move(900,600)
        return self.call('detail_state')

    def test_shop_reputation_native_hover_returns_text_without_link_click(self):
        s=self.reputation_fixture();self.assertFalse(s['detail']['commerce']['shop']['reputation']['panelVisible'])
        read=self.call('read_shop_reputation');self.assertEqual(read['interaction'],'none');self.assertEqual(read['shop']['reputation']['rows'],[])
        ref=next(x['controlId'] for x in read['state']['detail']['controls'] if x['tool']=='read_shop_reputation')
        r=self.call('read_shop_reputation',controlId=ref);self.assertTrue(r['confirmed']);self.assertEqual(r['clicks'],0)
        self.assertEqual({x['label']:x['displayValue'] for x in r['shop']['reputation']['rows']},{'综合体验':'4.6','宝贝质量':'5.0','物流速度':'4.4','服务保障':'4.4'})
        self.assertNotIn('levelImageBase64',r);self.assertNotIn('PRIVATE_REPUTATION',json.dumps(r['shop']))
        self.assertIsNone(r['shop']['level']['text']);self.assertEqual(self.page.url,'https://item.taobao.com/item.htm?id=123')
        ref=next(x['controlId'] for x in r['state']['detail']['controls'] if x['tool']=='read_shop_reputation')
        self.assertTrue(self.call('read_shop_reputation',controlId=ref)['alreadySatisfied'])

    def test_shop_reputation_noop_and_hidden_scores_not_success(self):
        s=self.reputation_fixture(False);ref=next(x['controlId'] for x in s['detail']['controls'] if x['tool']=='read_shop_reputation')
        r=self.call('read_shop_reputation',controlId=ref);self.assertFalse(r['confirmed']);self.assertEqual(r['shop']['reputation']['rows'],[])
        self.page.locator('[data-shop-reputation-panel]').evaluate("e=>{e.hidden=false;e.style.opacity='0'}")
        r=self.call('read_shop_reputation');self.assertFalse(r['shop']['reputation']['panelVisible']);self.assertFalse(any(x['label']=='宝贝质量' for x in r['shop']['ratings']))

    def test_shop_reputation_cannot_be_clicked_and_stale_id_rejected(self):
        s=self.reputation_fixture();ref=next(x['controlId'] for x in s['detail']['controls'] if x['tool']=='read_shop_reputation')
        with self.assertRaisesRegex(ValueError,'corresponding semantic tool'):self.call('click_shopping_control',controlId=ref)
        self.call('detail_state')
        with self.assertRaisesRegex(RuntimeError,'expired controlId'):self.call('read_shop_reputation',controlId=ref)

    def test_shop_reputation_changed_sku_during_wait_stops_before_hover(self):
        s=self.reputation_fixture();ref=next(x['controlId'] for x in s['detail']['controls'] if x['tool']=='read_shop_reputation')
        self.c.pause=lambda *a,**k:self.page.locator('.skuItem li').nth(1).click()
        with self.assertRaisesRegex(RuntimeError,'PRODUCT_CHANGED'):self.call('read_shop_reputation',controlId=ref)
        self.assertTrue(self.page.locator('[data-shop-reputation-panel]').is_hidden())

if __name__=='__main__':unittest.main(verbosity=2)
