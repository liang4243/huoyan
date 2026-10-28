"""Real Chrome + local fixtures: no external shopping traffic or credentials."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from playwright.sync_api import sync_playwright
from python.huoyan_browser import Controller, run as dispatch
from python.shopping_research import run

CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
HTML = '''<!doctype html><meta charset="utf-8"><title>PLA fixture</title>
<style>[hidden]{display:none!important} .skuItem li{display:inline-block;padding:10px}</style>
<form onsubmit="event.preventDefault();searches++;history.pushState({},'', '/search?q='+encodeURIComponent(this.q.value));render()"><input name="q" value="PLA"><button>搜索</button></form>
<div role="tablist"><button role="tab" aria-selected="true" onclick="sort('综合')">综合</button><button role="tab" aria-selected="false" onclick="sort('销量')">销量</button><button role="tab" aria-selected="false" onclick="document.querySelector('#menu').hidden=false">价格</button></div>
<div id="menu" hidden><button role="menuitem" onclick="price('asc',this)">从低到高</button><button role="menuitem" onclick="price('desc',this)">从高到低</button></div>
<button onclick="document.querySelector('#filters').hidden=false;this.setAttribute('aria-expanded','true')" aria-expanded="false">筛选</button>
<div id="filters" data-filter-panel hidden><div data-filter-group aria-label="物流"><button data-filter-option aria-pressed="false" onclick="this.setAttribute('aria-pressed',this.getAttribute('aria-pressed')!=='true');render()">包邮</button><button data-filter-option aria-pressed="false" onclick="this.setAttribute('aria-pressed',true)">可开发票</button></div>
<input aria-label="最低价" type="number"><input aria-label="最高价" type="number"><button onclick="applies++;document.querySelector('#applied').setAttribute('data-applied-price-min',document.querySelectorAll('input[type=number]')[0].value);document.querySelector('#applied').setAttribute('data-applied-price-max',document.querySelectorAll('input[type=number]')[1].value);render(true)">确定</button><button onclick="document.querySelectorAll('[data-filter-option]').forEach(e=>e.setAttribute('aria-pressed',false));render()">重置筛选</button></div>
<button aria-label="上一页，当前第1页" onclick="paginate(-1)">上一页</button><button aria-label="下一页，当前第1页" onclick="paginate(1)">下一页</button><span aria-current="page">1</span><input aria-label="请输入跳转到第几页"><button data-page-jump onclick="n=Number(this.previousElementSibling.value);paginate(0)">确定</button><div id="cards"></div><span id="applied">已应用价格</span>
<div class="skuItem"><span class="label">重量</span><li onclick="pick(this)">0.5kg</li><li onclick="pick(this)">1kg</li><li class="disabled">缺货</li></div><div data-product-price>￥36</div><div data-product-offer>会员优惠，条件待核验</div><div data-product-stock>有货</div>
<button role="tab" onclick="this.setAttribute('aria-selected','true');document.querySelector('#params').hidden=false">参数</button><button role="tab" onclick="this.setAttribute('aria-selected','true');document.querySelector('#reviews').hidden=false">评价</button>
<div id="params" data-product-parameters hidden>PLA 1.75mm</div><div id="reviews" data-product-reviews hidden>示例评价，非实际商品</div><div data-product-description>PLA 1.75mm</div>
<img data-product-main-image width="200" height="200" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='200'%3E%3C/svg%3E"><button data-product-thumbnail onclick="document.querySelector('[data-product-main-image]').src='data:image/svg+xml,%3Csvg%20xmlns=%22http://www.w3.org/2000/svg%22%20width=%22201%22%20height=%22201%22%3E%3C/svg%3E'">图2</button>
<a href="https://shop123.taobao.com/" onclick="shops++">进入店铺</a><button onclick="cart++">加入购物车</button><button onclick="payments++">付款</button><a href="https://evil.example/">进入店铺</a>
<script>
window.searches=window.applies=window.cart=window.payments=window.shops=0;window.n=1;window.order='综合';
window.render=filtered=>{document.querySelector('#cards').innerHTML=[123,filtered?789:456].map(id=>`<a data-product-card href="https://item.taobao.com/item.htm?id=${id}" target="_blank">PLA ${id} ￥${id===123?36:40} 1000+人付款</a>`).join('')};render();
window.sort=name=>{order=name;document.querySelectorAll('[role=tab]').forEach(e=>e.setAttribute('aria-selected',e.innerText===name))};
window.price=(direction,e)=>{sort('价格');document.querySelector('[role=tablist]').querySelectorAll('button')[2].setAttribute('data-direction',direction);document.querySelectorAll('[role=menuitem]').forEach(x=>x.setAttribute('aria-selected',x===e));document.querySelector('#menu').hidden=true};
window.paginate=d=>{n+=d;document.querySelector('[aria-current]').innerText=n;document.querySelectorAll('button[aria-label*="当前第"]').forEach(e=>e.setAttribute('aria-label',e.innerText+'，当前第'+n+'页'))};
window.pick=e=>{document.querySelectorAll('.skuItem li').forEach(x=>x.classList.remove('selected'));e.classList.add('selected')};
</script>'''


class ShoppingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(prefix='huoyan-research-')
        cls.pw = sync_playwright().start()
        cls.context = cls.pw.chromium.launch_persistent_context(str(Path(cls.folder.name)/'profile'), executable_path=CHROME,
            headless=True, args=['--no-proxy-server'])
        cls.context.route('**/*', lambda r: r.fulfill(content_type='text/html; charset=utf-8', body=HTML))

    @classmethod
    def tearDownClass(cls):
        cls.context.close();cls.pw.stop();cls.folder.cleanup()

    def setUp(self):
        self.page = self.context.new_page();self.page.goto('https://s.taobao.com/search?q=PLA')
        self.c = Controller({'out':str(Path(self.folder.name)/self._testMethodName),'delayMin':0,'delayMax':0,'verificationTimeoutMs':150,'settleMs':0,'stableMs':0}, self.context.browser).__enter__()
        self.c.pause=lambda *a,**kw:0
        self.c.args['tabId']=self.c.tab_id(self.page)
        self.c.focus.activate(self.page)
        self.original_tabs=set(self.context.pages)

    def tearDown(self):
        self.assertEqual(self.page.evaluate('cart+payments'),0)
        self.c.close()
        for p in list(self.context.pages):
            if p is self.page or p not in self.original_tabs:p.close()

    def call(self, operation, **kw):
        args={**self.c.args,'operation':operation,**kw}
        self.c.args=args
        return run(self.c)

    def controls(self):return self.call('shopping_state')['controls']

    def click(self, action, label=None):
        rows=[r for r in self.controls() if r['action']==action and (label is None or r['label']==label)]
        self.assertEqual(len(rows),1,rows)
        return self.call('click_shopping_control',controlId=rows[0]['controlId'])

    def test_sort_directions_and_idempotence(self):
        r=self.call('set_sort',field='sales',direction=None);self.assertTrue(r['confirmed']);self.assertEqual(r['clicks'],1)
        self.assertEqual(self.call('set_sort',field='sales')['clicks'],0)
        r=self.call('set_sort',field='price',direction='asc');self.assertTrue(r['confirmed']);self.assertEqual(r['after']['sort']['direction'],'asc')
        r=self.call('set_sort',field='price',direction='desc');self.assertTrue(r['confirmed']);self.assertEqual(r['after']['sort']['direction'],'desc')
        self.assertEqual(len(self.context.pages),len(self.original_tabs))

    def test_filter_edit_apply_clear_and_invalid_range(self):
        self.assertTrue(self.click('filter_panel')['confirmed'])
        row=next(r for r in self.controls() if r['label']=='包邮')
        with self.assertRaises(ValueError):self.call('set_filters',options=[{'controlId':row['controlId'],'selected':True}],priceMin=60,priceMax=20)
        self.assertEqual(self.page.evaluate('applies'),0)
        r=self.call('set_filters',options=[{'controlId':row['controlId'],'selected':True}],priceMin=20,priceMax=50)
        self.assertTrue(r['confirmed']);self.assertTrue(r['applicationEvidence']);self.assertIn('包邮',[x['label'] for x in r['after']['filters']])
        r=self.click('clear_filters');self.assertTrue(r['confirmed']);self.assertEqual(r['after']['filters'],[])

    def test_stale_tokens_block_spa_and_relisting(self):
        row=next(r for r in self.controls() if r['action']=='next_page')
        self.controls()
        with self.assertRaisesRegex(RuntimeError,'expired'):self.call('click_shopping_control',controlId=row['controlId'])
        row=next(r for r in self.controls() if r['action']=='next_page')
        self.page.get_by_role('tab',name='销量',exact=True).click()
        with self.assertRaisesRegex(RuntimeError,'state changed'):self.call('click_shopping_control',controlId=row['controlId'])
        self.assertEqual(self.page.locator('[aria-current]').inner_text(),'1')

    def test_real_search_and_pagination(self):
        self.assertTrue(self.call('search_products',keyword='PLA 1.75mm',scope='global')['confirmed'])
        self.assertEqual(self.page.evaluate('searches'),1)
        self.assertTrue(self.click('next_page')['confirmed'])
        self.assertTrue(self.click('previous_page')['confirmed'])
        self.assertTrue(self.call('go_to_page',pageNumber=3)['confirmed'])
        self.assertTrue(self.call('go_to_page',pageNumber=3)['alreadySatisfied'])
        self.assertEqual(len(self.call('list_products')['products']),2)
        self.assertEqual(len(self.context.pages),len(self.original_tabs))

    def test_product_exact_sku_candidate_offer_gallery_sections(self):
        product=next(r for r in self.controls() if r['action']=='open_product')
        result=self.call('click_shopping_control',controlId=product['controlId'])
        self.assertTrue(result['confirmed']);self.assertEqual(len(self.context.pages),len(self.original_tabs)+1)
        self.assertIn('detail',result['state']);self.assertEqual(result['state']['detail']['selectedSku'],[])
        self.assertTrue(result['state']['detail']['skuGroups']);self.assertTrue(result['state']['detail']['availableActions'])
        self.c.args['tabId']=result['state']['tabId'];self.product=next(p for p in self.context.pages if self.c.tab_id(p)==self.c.args['tabId'])
        with self.assertRaisesRegex(RuntimeError,'Select'):self.call('save_candidate')
        self.assertTrue(self.call('select_sku',sku=['1kg'])['confirmed'])
        offer=self.call('read_selected_offer');self.assertTrue(offer['allSkuSelected']);self.assertIsNone(offer['finalPrice'])
        saved=self.call('save_candidate',notes='1kg sample')['candidate'];self.call('save_candidate')
        rows=self.call('compare_candidates')['candidates'];self.assertEqual(len(rows),1);self.assertEqual(saved['selectedSku'],['1kg'])
        self.assertTrue(self.click('section','参数')['confirmed'])
        self.assertTrue(any('1.75mm' in x['text'] for x in self.call('read_selected_offer')['sections']))
        image=self.call('shopping_state')['images'][0]
        self.assertTrue(self.call('click_shopping_control',controlId=image['controlId'])['confirmed'])
        # Duplicate product click reuses the product tab, no new window.
        self.call('return_to_results')
        self.c.args['tabId']=self.c.tab_id(self.page)
        product=next(r for r in self.controls() if r['action']=='open_product')
        self.call('click_shopping_control',controlId=product['controlId'])
        self.assertEqual(len(self.context.pages),len(self.original_tabs)+1)
        self.assertEqual(self.product.locator('.skuItem .selected').inner_text(),'1kg')

    def test_unconfirmed_click_and_missing_evidence(self):
        self.page.get_by_role('tab',name='销量',exact=True).evaluate("e=>e.onclick=()=>{}")
        self.assertFalse(self.call('set_sort',field='sales')['confirmed'])
        self.assertEqual(self.page.evaluate('order'),'综合')
        self.page.locator('[data-filter-panel]').evaluate('e=>e.hidden=false')
        self.page.locator('[data-filter-panel] button').last.evaluate("e=>e.onclick=()=>{}")
        self.page.locator('[data-filter-panel] button').get_by_text('确定',exact=True).count()
        self.page.locator('[data-filter-panel]').get_by_text('确定',exact=True).evaluate("e=>e.onclick=()=>{applies++}")
        r=self.call('set_filters',options=[],priceMin=10,priceMax=30)
        self.assertFalse(r['confirmed']);self.assertEqual(self.page.evaluate('applies'),1)

    def test_guard_isolation_and_disallowed_controls(self):
        labels=[r['label'] for r in self.controls()]
        self.assertNotIn('加入购物车',labels);self.assertNotIn('付款',labels)
        self.assertEqual(sum(r['action']=='open_shop' for r in self.controls()),1)
        self.page.evaluate("()=>{const d=document.createElement('div');d.id='captcha';d.innerText='安全验证';document.body.append(d)}")
        with self.assertRaisesRegex(RuntimeError,'Verification'):self.call('set_sort',field='sales')
        self.c.args.pop('tabId')
        pages=self.call('shopping_state')['pages'];self.assertTrue(any(r['status']=='blocked' for r in pages))

    def test_offline_progress_and_comparison_no_browser(self):
        self.call('set_sort',field='sales')
        r=dispatch('shopping',{'out':str(self.c.out),'operation':'research_progress','cdp':'http://127.0.0.1:1'})
        self.assertEqual(r['progress']['lastAction'],'set_sort')
        self.assertEqual(dispatch('shopping',{'out':str(self.c.out),'operation':'compare_candidates'})['candidates'],[])

    def test_unrecognized_sku_cannot_be_saved(self):
        self.page.goto('https://item.taobao.com/item.htm?id=123');self.c.focus.activate(self.page)
        self.page.locator('.skuItem').evaluate('e=>e.remove()')
        with self.assertRaisesRegex(RuntimeError,'Select'):self.call('save_candidate')
        self.assertFalse(self.call('read_selected_offer')['allSkuSelected'])

    def test_sort_waits_for_async_list_completion(self):
        self.c.args.update(verificationTimeoutMs=2000,settleMs=650,stableMs=200)
        self.page.get_by_role('tab',name='销量',exact=True).evaluate("e=>e.onclick=()=>{sort('销量');setTimeout(()=>render(true),300)}")
        r=self.call('set_sort',field='sales')
        self.assertTrue(r['confirmed']);self.assertIn('789',r['after']['productIds'])

    def test_applied_range_closed_and_reopened_persists(self):
        self.click('filter_panel')
        self.page.evaluate("""()=>{const b=document.createElement('button');b.role='tab';b.innerText='区间';b.setAttribute('aria-selected','true');b.onclick=()=>document.querySelector('#filters').hidden=false;document.body.append(b)}""")
        self.page.locator('[data-filter-panel]').get_by_text('确定',exact=True).evaluate("e=>e.onclick=()=>{applies++;document.querySelector('#filters').hidden=true}")
        r=self.call('set_filters',options=[],priceMin=20,priceMax=80)
        self.assertTrue(r['confirmed']);self.assertEqual(r['priceRangeEvidence']['evidence'],'apply-closed-menu-and-values-persist-after-reopen')

    def test_real_style_price_menu_without_aria(self):
        self.page.evaluate("""()=>{const b=[...document.querySelectorAll('[role=tab]')].find(e=>e.innerText==='价格');b.className='customTabItemWithArr--fixture';b.onmouseenter=()=>document.querySelector('#menu').hidden=false;document.querySelector('#menu').innerHTML=['从低到高','从高到低'].map(t=>'<div class="priceTag--fixture">'+t+'</div>').join('');document.querySelectorAll('.priceTag--fixture').forEach(e=>e.onclick=()=>{document.querySelectorAll('[role=tab]').forEach(x=>x.setAttribute('aria-selected',false));document.querySelectorAll('.priceTag--fixture').forEach(x=>x.removeAttribute('style'));e.style.fontWeight='bold';e.style.backgroundColor='#f3f6f8';document.querySelector('#menu').hidden=true})}""")
        r=self.call('set_sort',field='price',direction='asc');self.assertTrue(r['confirmed'])
        self.assertEqual(r['after']['sort']['evidence'][0]['selectionEvidence'],'inline-bold-and-background')
        self.assertEqual(self.call('set_sort',field='price',direction='asc')['clicks'],0)
        self.assertTrue(self.call('set_sort',field='sales',direction=None)['confirmed'])

    def test_split_decimal_card_price_and_product_control_mapping(self):
        self.page.locator('[data-product-card]').first.evaluate("e=>e.innerText='PLA ￥70 .6 100人付款'")
        s=self.call('shopping_state');self.assertEqual(s['products'][0]['displayPrice'],'70.6')
        product=s['products'][0]
        self.assertTrue(product['controlIds'])
        self.assertTrue(any(x.get('productId')==product['productId'] and x['controlId'] in product['controlIds'] for x in s['controls']))

    def test_sku_text_newlines_match_observed_option(self):
        self.page.goto('https://item.taobao.com/item.htm?id=123');self.c.focus.activate(self.page)
        self.page.locator('.skuItem li').nth(1).evaluate("e=>e.innerHTML='<div>1kg</div><div>推荐</div>'")
        r=self.call('select_sku',sku=['1kg 推荐'])
        self.assertTrue(r['confirmed']);self.assertEqual(r['after']['selectedSku'],['1kg 推荐'])

    def test_shop_search_scope_comes_from_actual_form(self):
        self.page.goto('https://shop123.taobao.com/search.htm');self.c.focus.activate(self.page)
        self.page.locator('form').evaluate("e=>{e.q.name='keywords';e.onsubmit=ev=>{ev.preventDefault();searches++;history.pushState({},'', '/search.htm?keyword='+encodeURIComponent(e.keywords.value));render()}}")
        with self.assertRaisesRegex(RuntimeError,'search controlId'):self.call('search_products',keyword='PLA',scope='global')
        self.assertEqual(self.page.evaluate('searches'),0)
        r=self.call('search_products',keyword='店内PLA',scope='shop')
        self.assertTrue(r['confirmed']);self.assertEqual(r['requestedScope'],'shop')

    def test_shop_link_click_uses_observed_href(self):
        self.page.goto('https://item.taobao.com/item.htm?id=123');self.c.focus.activate(self.page)
        r=self.click('open_shop')
        self.assertTrue(r['confirmed']);self.assertEqual(r['state']['pageType'],'shop')
        self.assertEqual(self.page.evaluate('shops'),0)  # destination fixture resets this counter
        self.assertTrue(self.page.url.startswith('https://shop123.taobao.com/'))

    def test_visible_search_suggestion_does_not_auto_submit(self):
        self.page.evaluate("""()=>{const l=document.createElement('div');l.role='listbox';l.innerHTML='<div role="option">PLA建议</div>';l.firstChild.onclick=()=>document.querySelector('[name=q]').value='PLA建议';document.body.append(l)}""")
        r=self.click('search_suggestion');self.assertTrue(r['confirmed'])
        self.assertEqual(self.page.evaluate('searches'),0)

    def test_bounded_load_more_and_bottom_stop(self):
        self.c.args.update(verificationTimeoutMs=1500,settleMs=300,stableMs=100)
        self.page.evaluate("""()=>{const d=document.createElement('div');d.style.height='5000px';document.body.append(d);addEventListener('scroll',()=>{if(scrollY>0)document.querySelector('#cards').insertAdjacentHTML('beforeend','<a data-product-card href="https://item.taobao.com/item.htm?id=789" target="_blank">PLA 789 ￥40</a>')},{once:true})}""")
        r=self.call('load_more');self.assertTrue(r['confirmed']);self.assertIn('789',r['after']['productIds'])
        self.assertGreater(self.page.evaluate('scrollY'),0)
        self.page.evaluate('scrollTo(0,document.documentElement.scrollHeight)');self.page.wait_for_timeout(50)
        r=self.call('load_more');self.assertTrue(r['alreadyAtBottom'])


    def test_search_workflow_one_pause_dynamic_list_and_replay(self):
        pauses = []
        def pause(page, *args, **kwargs):
            pauses.append(1)
            page.locator('#cards a').first.evaluate("e=>e.innerText='动态补全图片及价格 ￥99'")
            return 0
        self.c.pause = pause
        r = self.call('search_and_read', requestId='search-wf', keyword='灰色 PLA', scope='global')
        self.assertTrue(r['confirmed'], r)
        self.assertEqual(len(pauses), 1)
        self.assertEqual(self.page.evaluate('searches'), 1)
        self.assertTrue(self.call('search_and_read', requestId='search-wf')['replayed'])
        self.assertEqual(self.page.evaluate('searches'), 1)
        with self.assertRaisesRegex(RuntimeError, 'WORKFLOW_REQUEST_CONFLICT'):
            self.call('search_and_read', requestId='search-wf', keyword='不同关键词')

    def test_workflow_does_not_treat_input_as_committed_results(self):
        self.page.locator('form').evaluate("e=>e.onsubmit=ev=>{ev.preventDefault();searches++}")
        r = self.call('search_and_read', requestId='no-results-wf', keyword='新关键词', verificationTimeoutMs=400)
        self.assertFalse(r['confirmed'], r)
        self.assertEqual(r['workflow']['status'], 'needs_review')
        self.assertTrue(r['workflow']['progress']['inputChanged'])
        self.assertTrue(r['workflow']['progress']['clickAttempted'])
        self.assertFalse(r['workflow']['progress']['resultsBelongToRequestedQuery'])
        r = self.call('search_and_read', requestId='no-results-wf')
        self.assertFalse(r['confirmed'])
        self.assertEqual(self.page.evaluate('searches'), 1)

    def test_search_workflow_input_changed_but_button_disappeared(self):
        self.page.locator('input[name=q]').evaluate("e=>e.oninput=()=>{e.form.querySelector('button').hidden=true}")
        r = self.call('search_and_read', requestId='partial-input', keyword='新关键词')
        self.assertFalse(r['confirmed'], r)
        self.assertTrue(r['workflow']['progress']['inputChanged'])
        self.assertFalse(r['workflow']['progress']['clickAttempted'])
        self.assertEqual(self.page.evaluate('searches'), 0)
        self.call('search_and_read', requestId='partial-input')
        self.assertEqual(self.page.evaluate('searches'), 0)

    def test_search_step_budget_resume_before_mutation(self):
        r = self.call('search_and_read', requestId='budget-search', keyword='PETG', maxSteps=1)
        self.assertEqual(r['workflow']['status'], 'paused', r)
        self.assertEqual(self.page.evaluate('searches'), 0)
        r = self.call('search_and_read', requestId='budget-search', maxSteps=12)
        self.assertTrue(r['confirmed'], r)
        self.assertEqual(self.page.evaluate('searches'), 1)


if __name__=='__main__':unittest.main(verbosity=2)
