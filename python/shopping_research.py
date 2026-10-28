"""Evidence-based rendered-page shopping, with an explicit fixed-home recovery entry."""
import hashlib
import json
import math
import re
import time
import uuid
from random import uniform
from urllib.parse import urlparse, parse_qs

from .huoyan_browser import atomic_json, load_json, dom_script, product_identity, inspect, stamp


def supported(url):
    parsed = urlparse(url)
    return parsed.scheme == 'https' and not parsed.username and not parsed.password and any(
        parsed.hostname == d or (parsed.hostname or '').endswith('.' + d) for d in ('taobao.com', 'tmall.com'))


def page_for(c,require_focus=True):
    tab = c.args.get('tabId')
    pages = [p for p in c.pages if supported(p.url)]
    if tab:
        page = next((p for p in pages if c.tab_id(p) == tab), None)
        if page is None:
            raise RuntimeError('Unknown supported tabId. Read shopping_state first.')
    else:
        if len(pages) != 1:
            raise ValueError('Specify tabId when there is not exactly one shopping page.')
        page = pages[0]
    c.guard(page)
    if require_focus:c.focus.require(page)
    return page


def read(c, page):
    if not supported(page.url):
        raise RuntimeError('Page left supported shopping sites; stopped.')
    c.guard(page)
    c.focus.require(page)
    data = page.evaluate(dom_script('researchPageDom.js'))
    data['tabId'] = c.tab_id(page)
    from .shop_research import enrich
    enrich(c,page,data)
    data['favoritesDom'] = page.evaluate(dom_script('favoritesDom.js'))
    if data['favoritesDom']['isFavoritesPage']:
        data['pageType'] = 'favorites'
    if data['pageType']!='product':
        commerce=page.evaluate(dom_script('commerceEvidenceDom.js'),{'mode':'cards'})
        by_id={p['productId']:p for p in commerce}
        for product in data['products']:
            observed=by_id.get(product['productId'])
            if observed:
                product.update({k:v for k,v in observed.items() if k!='productId'})
                product['commerce']['observedAt']=stamp()
                if product['commerce']['shop']['name']:product['shop']=product['commerce']['shop']['name']
    if data['pageType'] == 'product':
        data['product'] = c.snapshot(page)
        data['skuOptions'] = inspect(page, 'option-controls')
        data['detail'] = page.evaluate(dom_script('detailPageDom.js'))
        data['detail']['commerce']=data['product']['commerce']
        # The legacy broad comment selector also includes buyer headers/avatars.
        # Product research exports only explicitly parsed review content.
        d=data['detail']
        data['sections']=([{'label':'参数','text':t} for t in d['parameterText']]+
            [{'label':'图文详情','text':t} for t in d['descriptions']]+
            [{'label':'评价','text':r['text']} for r in d['reviews']])
    c.focus.require(page)
    c.tab_budget.touch(page)
    return data


def revision(data):
    # State tokens change on SPA list/sort/filter/selection updates, not just URL changes.
    fields = [(f['index'], f['kind'], f['label'], f['value']) for f in data['fields']]
    stable_sort=[e for e in data['sort']['evidence'] if e.get('selectionEvidence')!='inline-bold-and-background']
    value = [data['url'], data['query'], stable_sort, sorted(set(x['label'] for x in data['filters'])), data['pagination'], data.get('appliedPriceRange'),
             [(p['productId'], p['displayPrice']) for p in data['products']],
             [(x['signature'], x['disabled']) for x in data['controls'] if x['action']=='section' and x['selected']],
             data.get('skuOptions'), fields, data['currentImages'],[(x['index'],x['label'],x['src']) for x in data['images']]]
    shop=data.get('shopDom',{})
    value.append([shop.get('identity'),shop.get('queryEvidence'),shop.get('selectedSections'),shop.get('selectedCategories'),shop.get('searchTarget'),
        [(r['signature'],r['selected'],r['disabled'],r.get('expanded')) for r in shop.get('controls',[])]])
    value.append([r['signature'] for r in data.get('favoritesDom',{}).get('controls',[])])
    if data.get('detail'):
        detail=data['detail']
        value.append([[(r['signature'],r['selected'],r['disabled'],r.get('value')) for r in detail['controls']],
                      detail['panels'],detail['reviews'],detail.get('reviewSort'),detail['questions'],detail['parameterText'],detail['services'],detail['descriptions']])
        commerce=detail.get('commerce',{})
        value.append([commerce.get('pricing'),commerce.get('fulfillment'),commerce.get('shop',{}).get('name')])
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def publish(c, data):
    file = c.out / 'shopping-controls.json'
    database = load_json(file, {'endpoint': c.endpoint, 'tabs': {}})
    if database.get('endpoint') != c.endpoint:
        database = {'endpoint': c.endpoint, 'tabs': {}}
    generation = uuid.uuid4().hex
    records = {}
    public = {k: v for k, v in data.items() if k not in ('selector', 'imageSelector','shopDom','favoritesDom')}
    if 'skuOptions' in public:public['skuOptions']=[{k:v for k,v in x.items() if k!='elementPath'} for x in public['skuOptions']]
    for kind in ('controls', 'fields', 'images'):
        values = []
        for raw in data[kind]:
            ref = hashlib.sha256((generation + kind + str(raw['index'])).encode()).hexdigest()[:20]
            records[ref] = {'kind': kind, **raw}
            item={k: v for k, v in raw.items() if k not in ('signature', 'index', 'href', 'visible','elementPath','fieldPath')} | {'controlId': ref}
            if raw.get('action')=='open_product':item['productId']=product_identity(raw['href'])['productId']
            values.append(item)
        public[kind] = values
    if data.get('detail'):
        from .detail_research import publish_detail
        public['detail']=publish_detail(c,data,generation,records)
    database['tabs'][data['tabId']] = {'pageUrl': data['url'], 'revision': revision(data),
        'records': records, 'selector': data['selector'], 'imageSelector': data['imageSelector']}
    atomic_json(file, database)
    for product in public['products']:
        product['controlIds']=[x['controlId'] for x in public['controls'] if x.get('action')=='open_product' and x.get('productId')==product['productId']]
    from .shop_research import publish_shop
    publish_shop(data,public,generation)
    if data.get('favoritesDom'):
        from .favorites import publish as publish_favorites
        page=next(p for p in c.pages if c.tab_id(p)==data['tabId'])
        public['favorites']=publish_favorites(c,page,data['favoritesDom'])
    public.update(observedAt=stamp(), contentIsUntrusted=True,
        focus=c.focus.info(),
        note='Only visible evidence. Null means unverified. Listing invalidates earlier controls for this tab. Prices may be minimum-SKU or conditional prices.')
    return public


def state(c):
    if not c.args.get('tabId'):
        pages = []
        for page in c.pages:
            if not supported(page.url):
                continue
            try:
                from .tab_focus import page_type
                c.guard(page)
                try:window=c.focus.window(page)
                except Exception:window={'state':'unverified','foreground':'unverified','occlusion':'unverified'}
                pages.append({'tabId': c.tab_id(page), 'pageType': page_type(page), 'title': page.title(), 'status': 'ready', 'visible':page.evaluate('document.visibilityState')=='visible','window':window})
            except RuntimeError as error:
                pages.append({'tabId': c.tab_id(page), 'status': 'blocked', 'reason': str(error)})
        return {'pages': pages, 'focus':c.focus.info(), 'nextAction': 'Use resume_shopping to restore/select a shopping tab or open the fixed Taobao homepage when none remain; no manual window/homepage request is needed. Login/verification still requires user handling.'}
    return publish(c, read(c, page_for(c)))


def saved_record(c, page, ref):
    data = load_json(c.out / 'shopping-controls.json', {})
    if data.get('endpoint') != c.endpoint:
        raise RuntimeError('Controls belong to another browser; read shopping_state again.')
    saved = data.get('tabs', {}).get(c.tab_id(page))
    if not saved or ref not in saved['records']:
        raise RuntimeError('Unknown or expired controlId; read shopping_state again.')
    current = read(c, page)
    if saved['revision'] != revision(current):
        raise RuntimeError('Page state changed; no action performed. Read shopping_state again.')
    record = saved['records'][ref]
    if record['kind'].startswith('detail'):
        from .detail_research import validate_record
        validate_record(current,record)
    if record['kind'] == 'controls' and not any(x['index'] == record['index'] and x['signature'] == record['signature'] for x in current['controls']):
        raise RuntimeError('Control changed or disappeared; read shopping_state again.')
    return record, current


def native_locator(page, data, record):
    if record.get('elementPath'):
        return page.locator(record['elementPath'])
    if record['kind'] == 'controls':
        return page.locator(data['selector']).nth(record['index'])
    if record['kind'] == 'fields':
        return page.locator('input').nth(record['index'])
    return page.locator(data['imageSelector']).nth(record['index'])


def record_for(data, action, label=None):
    rows = [x for x in data['controls'] if x['action'] == action and not x['disabled'] and (label is None or x['label'] == label)]
    if len(rows) != 1:
        raise RuntimeError(f'Expected one {action} control; found {len(rows)}. Read controls and choose an explicit controlId.')
    return {'kind': 'controls', **rows[0]}


def changed(before, after):
    return revision(before) != revision(after)


def list_context(data):
    return {k:data.get(k) for k in ('url','query','searchScope','filters','currentPage','totalPages','appliedPriceRange')} | {
        'sort':{k:data['sort'].get(k) for k in ('field','direction')},'shopKey':(data.get('shopDom',{}).get('identity') or {}).get('key')}


def media_state(product):
    return [(i['src'],i['width'],i['height'],i['ready']) for i in product.get('commerce',{}).get('media',{}).get('images',[])]


def list_load_evidence(before,after):
    old={p['productId']:p for p in before['products']};new={p['productId']:p for p in after['products']}
    removed=sorted(old.keys()-new.keys());added=sorted(new.keys()-old.keys())
    image_changes=sorted(k for k in old.keys()&new.keys() if media_state(old[k])!=media_state(new[k]))
    ready_changes=sorted(k for k in image_changes if any(i[3] and i not in media_state(old[k]) for i in media_state(new[k])))
    return {'contextChanged':list_context(before)!=list_context(after),'newProductIds':added,'removedProductIds':removed,'imageChangedProductIds':image_changes,'readyImageChangedProductIds':ready_changes}


def wait_result(c, page, before, predicate=None):
    deadline = time.monotonic() + c.args.get('verificationTimeoutMs', 6000) / 1000
    after = read(c, page)
    stable_since=time.monotonic();last_revision=revision(after)
    started=stable_since
    while time.monotonic() < deadline:
        now=time.monotonic();new_revision=revision(after)
        if new_revision!=last_revision:stable_since=now;last_revision=new_revision
        if (predicate(after) if predicate else changed(before, after)) and now-started>=c.args.get('settleMs',1200)/1000 and now-stable_since>=c.args.get('stableMs',400)/1000:
            return after
        page.wait_for_timeout(200)
        after = read(c, page)
    return after


def outcome(c, page, action, before, after, confirmed, reason=None, **extra):
    c.focus.require(page)
    c.focus.pending=None
    from .shop_research import check_shop_transition,context
    intentional_departure=action in ('open_product','open_shop','return_to_shop_results','home') or action=='search_products' and extra.get('requestedScope')=='global'
    mismatch=check_shop_transition(before,after) if not intentional_departure else None
    if mismatch:confirmed=False;reason=mismatch;extra['code']='SCOPE_MISMATCH'
    result = {'action': action, 'confirmed': bool(confirmed), 'before': summary(before),
        'after': summary(after), 'failureReason': None if confirmed else reason or 'No sufficient visible evidence; no automatic retry.',
        **extra, 'state': publish(c, after)}
    atomic_json(c.out / 'research-progress.json', {'version': 1, 'updatedAt': stamp(), 'lastAction': action,
        'tabId': c.tab_id(page), 'confirmed': bool(confirmed), 'state': summary(after),
        'shopContext':context(after) if after['pageType']=='shop' else None})
    return result


def summary(data):
    return {k: data.get(k) for k in ('tabId', 'pageType', 'query', 'searchScope', 'sort', 'filters', 'pagination', 'currentPage','totalPages', 'appliedPriceRange', 'noResults')} | {
        'productIds': [p['productId'] for p in data['products']],
        'selectedSku': data.get('product', {}).get('selectedSku', []),
        'shopIdentity':data.get('shopDom',{}).get('identity')}


def detail_actionable(c,page,loc):
    """Bounded native preflight; scroll around sticky UI without bypassing overlays."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    try:
        loc.scroll_into_view_if_needed(timeout=5000)
        # Playwright's nearest scrolling can leave a control behind a sticky bar.
        # Center the actual element using normal scrolling; never remove overlays.
        loc.evaluate("""e=>{const r=e.getBoundingClientRect(),h=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
            if(!h||h!==e&&!e.contains(h))e.scrollIntoView({block:'center',inline:'nearest',behavior:'instant'})}""")
        c.focus.require(page);c.guard(page)
        loc.click(trial=True,timeout=5000)
    except PlaywrightTimeout as error:
        c.focus.require(page);c.guard(page)
        try:
            evidence=loc.evaluate('''e=>{const r=e.getBoundingClientRect(),x=r.left+r.width/2,y=r.top+r.height/2,h=document.elementFromPoint(x,y);
                return {inViewport:x>=0&&y>=0&&x<innerWidth&&y<innerHeight,blockedByOverlay:!!h&&h!==e&&!e.contains(h),
                hitTag:h?.tagName||null,visibility:document.visibilityState}}''')
        except Exception:evidence={'target':'unavailable'}
        raise RuntimeError('CONTROL_NOT_ACTIONABLE: native detail preflight timed out; no click delivered. '+json.dumps(evidence)) from error


def search_context(data):
    return (data['url'], data['pageType'], data.get('query'),
            data.get('shopDom', {}).get('identity'), data.get('shopDom', {}).get('searchTarget'),
            [(f['signature'], f['value']) for f in data['fields'] if f['kind'] == 'search'])


def search_progress(c, **values):
    c.search_progress = {**getattr(c, 'search_progress', {}), **values}
    if getattr(c, 'workflow_checkpoint', None):
        c.workflow_checkpoint(c.search_progress)


def deliver(c, page, before, record, paced=False):
    c.focus.require(page);c.focus.allow(page,record.get('action','gallery_image'))
    def compatible(current):
        if revision(current)==revision(before):return True
        if record.get('action') == 'search':
            matches = [r for r in current['controls'] if r['signature'] == record['signature'] and not r['disabled'] and r.get('searchScope') == record.get('searchScope')]
            return search_context(current) == search_context(before) and len(matches) == 1
        if record['kind']=='detail':
            # Scrolling a detail control into view can load images/comments and move
            # the sticky active section. These do not change the target's identity.
            old=before['product'];new=current.get('product',{})
            target=next((r for r in current.get('detail',{}).get('controls',[]) if r['signature']==record['signature']),None)
            same_panels=lambda d:[(p['kind'],p['elementPath']) for p in d.get('detail',{}).get('panels',[])]
            return bool(target and not target['disabled'] and current['url']==before['url'] and
                old['productId']==new.get('productId') and old['selectedSku']==new.get('selectedSku') and
                same_panels(before)==same_panels(current) and
                (record['action']=='section' or target['selected']==record['selected']))
        # Background list completion does not change the identity of a panel opener.
        return record.get('action') in ('price_panel','filter_panel','close_filter_panel') and all(current.get(k)==before.get(k) for k in ('url','query','pageType'))
    c.guard(page)
    if not compatible(read(c, page)):
        raise RuntimeError('Page state changed before click; read shopping_state again.')
    if record.get('disabled'):
        raise RuntimeError('Control disabled; stopped.')
    loc = native_locator(page, before, record)
    if not loc.is_visible() or not loc.is_enabled():
        raise RuntimeError('Control no longer visible/enabled; stopped.')
    if record['kind']=='detail':
        detail_actionable(c,page,loc)
    href = record.get('href')
    if href and not supported(href):
        raise RuntimeError('Control target is outside supported shopping sites; stopped.')
    if not paced:c.pause(page)
    c.guard(page);c.focus.require(page)
    if not compatible(read(c, page)):
        raise RuntimeError('Page state changed while waiting; stopped.')
    current = read(c, page)
    if record['kind']=='detail':
        from .detail_research import validate_record
        validate_record(current,record)
        target=next(r for r in current['detail']['controls'] if r['signature']==record['signature'])
        if record['action']=='section' and target['selected']:return False
    if record.get('action') in ('price_panel','filter_panel','close_filter_panel','search'):
        candidates=[x for x in current['controls'] if x['signature']==record['signature'] and not x['disabled']]
        if len(candidates)!=1:raise RuntimeError('Panel control changed or became ambiguous; stopped.')
        record={'kind':'controls',**candidates[0]}
        loc=native_locator(page,current,record)
    if record['kind'] == 'controls' and not any(x['index'] == record['index'] and x['signature'] == record['signature'] for x in current['controls']):
        raise RuntimeError('Control changed/disappeared while waiting; stopped.')
    c.tab_budget.before_popup(page,loc)
    c.focus.require(page);c.focus.begin(page)
    if record.get('action') == 'search':
        search_progress(c, clickAttempted=True, outcomeUnknown=True, stage='submitting')
    loc.click(timeout=8000)
    return True


def clicked_target(c,source,allow_popup=False):
    pending=c.focus.pending
    if not pending:return source
    source.wait_for_timeout(250)
    candidates=[p for p in c.pages if p not in pending['pages'] and supported(p.url)]
    if candidates:
        if not allow_popup or len(candidates)!=1:raise RuntimeError('Unexpected/ambiguous new tab; activate a tab explicitly.')
        target=candidates[0];target.wait_for_load_state('domcontentloaded',timeout=8000)
        c.guard(target);c.focus.adopt_popup(source,target)
        return target
    c.focus.require(source)
    return source


def set_sort(c, page):
    field, direction = c.args.get('field'), c.args.get('direction')
    if field not in ('comprehensive', 'sales', 'price','newest') or direction not in (None, 'asc', 'desc'):
        raise ValueError('Invalid sort field/direction.')
    if field != 'price' and direction:
        raise ValueError('Direction is only supported for price.')
    def reveal_price():
        # This site's menu is removed from DOM on mouse leave. Hover its observed tab to
        # expose the existing selected direction; this does not submit a new sort.
        if field == 'price':
            tabs = page.locator('[role="tab"][class*="customTabItemWithArr"]')
            target = next((t for t in tabs.all() if t.is_visible() and t.inner_text().strip() == '价格'), None)
            if target:
                c.guard(page);c.focus.require(page);target.hover();page.wait_for_timeout(250);c.guard(page);c.focus.require(page)
    reveal_price()
    before = read(c, page)
    matches = lambda x: x['sort']['field'] == field and (not direction or x['sort']['direction'] == direction)
    if matches(before):
        return outcome(c, page, 'set_sort', before, before, True, alreadySatisfied=True, clicks=0)
    current = before
    clicks = 0
    # One menu/tab click, then at most one explicit direction click. Never toggle blindly.
    direct = next((x for x in current['controls'] if x['action'] == 'sort_direction' and
                   (direction == 'asc' and re.search('低到高|升序', x['label']) or direction == 'desc' and re.search('高到低|降序', x['label']))), None)
    if direct:
        record = {'kind': 'controls', **direct}
    else:
        if field=='newest':
            rows=[r for r in current['controls'] if r['action']=='sort' and r['label'] in ('新品','上新') and not r['disabled']]
            if len(rows)!=1:raise RuntimeError('UNSUPPORTED: no unique visible newest sort.')
            record={'kind':'controls',**rows[0]}
        else:record = record_for(current, 'sort', {'comprehensive': '综合', 'sales': '销量', 'price': '价格'}[field])
    deliver(c, page, current, record); clicks += 1
    reveal_price()
    after = wait_result(c, page, current, matches)
    from .shop_research import check_shop_transition
    if check_shop_transition(before,after):return outcome(c,page,'set_sort',before,after,False,clicks=clicks)
    if not matches(after) and direction:
        rows = [x for x in after['controls'] if x['action'] == 'sort_direction' and not x['disabled'] and
                re.search('低到高|升序' if direction == 'asc' else '高到低|降序', x['label'])]
        if len(rows) == 1:
            deliver(c, page, after, {'kind': 'controls', **rows[0]}); clicks += 1
            reveal_price()
            after = wait_result(c, page, after, matches)
    return outcome(c, page, 'set_sort', before, after, matches(after),
        'Requested sort field/direction could not be confirmed. No blind toggle or repeat submission.', clicks=clicks)


def click(c, page):
    record, before = saved_record(c, page, c.args.get('controlId'))
    if record['kind'].startswith('detail'):
        from .detail_research import click_control
        return click_control(c,page,record,before)
    if record['kind'] == 'fields':
        raise ValueError('Use set_filters or search_products for input fields.')
    action = record.get('action', 'gallery_image')
    if action=='open_shop':
        from .shop_research import open_shop
        return open_shop(c,page,c.args.get('controlId'))
    if action in ('shop_section','shop_category'):
        from .shop_research import run as shop_run
        return shop_run(c,page,'open_shop_section' if action=='shop_section' else 'open_shop_category')
    c.focus.allow(page,action)
    if action == 'open_product':
        if before['pageType']=='shop':
            card=next((p for p in before['products'] if p['productId']==product_identity(record['href'])['productId']),None)
            if card and card.get('region')=='recommendation':raise RuntimeError('UNSUPPORTED: recommendation is not a verified shop result.')
        already_open=product_identity(record['href'])['key'] in c.sync_tabs()
        p, source = c.product_page(record['href'], not already_open, require_page=True,from_page=page)
        after = read(c, p)
        from .shop_research import remember_visit
        remember_visit(c,before,after)
        return outcome(c, p, action, before, after, product_identity(p.url)['key'] == product_identity(record['href'])['key'], source=source)
    pages_before = set(c.pages)
    deliver(c, page, before, record)
    page=clicked_target(c,page,action in ('open_shop','home','search_suggestion'))
    predicate=None
    if action=='filter_panel':predicate=lambda x:x.get('filterPanelVisible',False)
    if action=='close_filter_panel':predicate=lambda x:not x.get('filterPanelVisible',False)
    after = wait_result(c, page, before,predicate)
    new_pages = [p for p in c.pages if p not in pages_before]
    for p in new_pages:
        c.guard(p)
    if action in ('open_shop', 'home', 'search_suggestion'):
        relevant = [p for p in new_pages if supported(p.url)]
        if relevant:
            if relevant[-1] is not page:raise RuntimeError('Unexpected extra tab; activate explicitly.')
    if action in ('sort', 'sort_direction', 'filter_option', 'section'):
        new = next((x for x in after['controls'] if x['signature'] == record['signature']), None)
        confirmed = bool(new and new['selected'])
    elif action == 'gallery_image':
        confirmed = after['currentImages'] != before['currentImages'] or any(x['index'] == record['index'] and x['selected'] for x in after['images'])
    elif action in ('next_page', 'previous_page'):
        confirmed = (after['pagination'] != before['pagination'] or [x['productId'] for x in after['products']] != [x['productId'] for x in before['products']])
    elif action=='filter_panel':confirmed=after.get('filterPanelVisible',False)
    elif action=='close_filter_panel':confirmed=not after.get('filterPanelVisible',False)
    elif action=='search_target':confirmed=after.get('shopDom',{}).get('searchTarget')==record['target']
    elif action=='search_target_menu':confirmed=any(r['action']=='search_target' and r['signature'] not in {x['signature'] for x in before['controls']} for r in after['controls'])
    else:
        confirmed = changed(before, after)
    return outcome(c, page, action, before, after, confirmed, clicked=True, siteOpenedTabs=len(new_pages))


def filters(c, page):
    before = read(c, page)
    requested = c.args.get('options', [])
    minimum, maximum = c.args.get('priceMin'), c.args.get('priceMax')
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError('priceMin must not exceed priceMax.')
    if any(v is not None and (not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or v < 0) for v in (minimum, maximum)):
        raise ValueError('Prices must be nonnegative numbers.')
    if not requested and minimum is None and maximum is None:
        raise ValueError('Specify option controlIds with selected booleans, or a price range.')
    records = []
    for option in requested:
        record, _ = saved_record(c, page, option['controlId'])
        if record.get('action') != 'filter_option' or not isinstance(option.get('selected'), bool):
            raise ValueError('Filter option needs a current filter_option controlId and selected boolean.')
        records.append((record, option['selected']))
    # Validate all price fields before any clicks, to avoid preventable partial operations.
    price_fields = []
    for kind, value in (('price_min', minimum), ('price_max', maximum)):
        if value is None: continue
        rows = [f for f in before['fields'] if f['kind'] == kind]
        if len(rows) != 1:
            raise RuntimeError(f'Cannot uniquely identify visible {kind}; no filters changed.')
        price_fields.append((rows[0], str(value)))
    current = before
    for record, desired in records:
        row = next((r for r in current['controls'] if r['signature'] == record['signature']), None)
        if row is None:
            return outcome(c, page, 'set_filters', before, current, False, 'Filter disappeared after earlier change; inspect partial state.')
        if row['selected'] != desired:
            deliver(c, page, current, {'kind': 'controls', **row})
            current = wait_result(c, page, current)
            from .shop_research import check_shop_transition
            if check_shop_transition(before,current):return outcome(c,page,'set_filters',before,current,False,partialChanges=['filter-option-click'])
    if price_fields:
        c.focus.require(page); c.pause(page); c.guard(page);c.focus.require(page)
        if revision(read(c, page)) != revision(current):
            raise RuntimeError('Page changed before filling prices; inspect current state.')
        for field, value in price_fields:
            c.focus.require(page)
            loc = page.locator('input').nth(field['index'])
            actual = next((f for f in read(c, page)['fields'] if f['index'] == field['index']), None)
            if not actual or actual['signature'] != field['signature']:
                raise RuntimeError('Price input changed; inspect partial state.')
            loc.fill(value); loc.blur()
        current = read(c, page)
    apply = [x for x in current['controls'] if x['action'] == 'apply_filters' and not x['disabled']]
    if len(apply) > 1:
        return outcome(c, page, 'set_filters', before, current, False, 'Multiple apply buttons; choose the intended visible control explicitly.')
    if apply:
        deliver(c, page, current, {'kind': 'controls', **apply[0]})
        after = wait_result(c, page, current)
    else:
        after = read(c, page)
    from .shop_research import check_shop_transition
    if check_shop_transition(before,after):return outcome(c,page,'set_filters',before,after,False,partialChanges=['filter-edits'])
    evidence = []
    for record, desired in records:
        row = next((r for r in after['controls'] if r['signature'] == record['signature']), None)
        evidence.append({'label': record['label'], 'requested': desired, 'observed': row['selected'] if row else None})
    choices_ok = all(e['observed'] == e['requested'] for e in evidence)
    # Input values prove editing, not server-side filter application. Require visible list/filter change too.
    applied_change = after['filters'] != before['filters'] or [(p['productId'],p['displayPrice']) for p in after['products']] != [(p['productId'],p['displayPrice']) for p in before['products']]
    observed_range=after.get('appliedPriceRange') or {}
    def same_price(value, observed):
        try:return value is None or observed is not None and float(observed)==value
        except (ValueError,TypeError):return False
    price_confirmed=bool(observed_range) and same_price(minimum,observed_range.get('min')) and same_price(maximum,observed_range.get('max'))
    range_evidence=observed_range or None
    if price_fields and not price_confirmed and apply and not any(f['kind'] in ('price_min','price_max') for f in after['fields']):
        # Observed Taobao UI closes the range menu on Apply. Reopen through its real
        # tab and verify persisted values. This establishes UI application, not server correctness.
        tabs=[x for x in after['controls'] if x['action']=='price_panel' and x['selected']]
        if len(tabs)==1:
            deliver(c,page,after,{'kind':'controls',**tabs[0]})
            after=wait_result(c,page,after,lambda x:any(f['kind']=='price_min' for f in x['fields']))
            persisted={f['kind']:f['value'] for f in after['fields'] if f['kind'] in ('price_min','price_max')}
            price_confirmed=same_price(minimum,persisted.get('price_min')) and same_price(maximum,persisted.get('price_max'))
            if price_confirmed:range_evidence={'min':persisted.get('price_min'),'max':persisted.get('price_max'),'evidence':'apply-closed-menu-and-values-persist-after-reopen','scope':'UI state; server filtering correctness unverified'}
    confirmed = choices_ok and (price_confirmed if price_fields else True)
    return outcome(c, page, 'set_filters', before, after, confirmed,
        'Inputs/choices may be edited, but applied filtering could not be confirmed.', optionEvidence=evidence,
        priceInputsEdited=bool(price_fields), priceRangeConfirmed=price_confirmed if price_fields else None, priceRangeEvidence=range_evidence, applicationEvidence=bool(applied_change))


def select_sku(c, page):
    if not isinstance(c.args.get('sku'),list):
        raise ValueError('Provide exact SKU texts, one per multi-option group.')
    before = read(c, page)
    if before['pageType'] != 'product':
        raise ValueError('SKU selection requires a current product page.')
    if not before['product']['skuCandidates']:
        raise RuntimeError('No SKU groups recognized; cannot verify a selected offer.')
    groups = inspect(page, 'groups')
    values = c.args['sku']
    if len(values) != len(groups) or any(v not in g['options'] for g, v in zip(groups, values)):
        raise ValueError('SKU texts must exactly match each current group in displayed order.')
    for index, value in enumerate(values):
        current = inspect(page, 'groups')
        if index >= len(current) or value not in current[index]['options']:
            return outcome(c, page, 'select_sku', before, read(c, page), False, 'SKU options changed during selection; inspect partial selection.')
        c.guard(page);c.focus.require(page); c.pause(page); c.guard(page);c.focus.require(page)
        options=[o for o in inspect(page,'option-controls') if o['groupIndex']==index and o['text']==value]
        if len(options)!=1 or options[0]['disabled']:
            return outcome(c, page, 'select_sku', before, read(c, page), False, 'SKU option unavailable.')
        if not options[0]['selected']:
            loc=page.locator(options[0]['elementPath'])
            if ' '.join(loc.inner_text().split())!=value or not loc.is_visible():
                return outcome(c,page,'select_sku',before,read(c,page),False,'SKU element changed.')
            loc.click(timeout=8000)
        page.wait_for_timeout(250)
    c.focus.require(page)
    single = inspect(page, 'single-skus')
    after = read(c, page)
    confirmed = single.get('ok') and inspect(page, 'all-selected') and all(inspect(page, 'selected-sku', groupIndex=i, value=v) for i, v in enumerate(values))
    return outcome(c, page, 'select_sku', before, after, confirmed)


def candidate(c, page):
    data = read(c, page)
    if data['pageType'] != 'product':
        raise ValueError('Save a candidate from its visible product page.')
    if not data['product']['skuCandidates'] or not inspect(page, 'all-selected'):
        raise RuntimeError('Select and verify every SKU group before saving a candidate.')
    product = data['product']
    offer = {k: product.get(k) for k in ('productId', 'title', 'url', 'selectedSku', 'prices', 'offers', 'stock', 'observedAt')}
    offer['url']=product_identity(product['url'])['url']
    offer['skuSelections']=[{'group':g['label'],'selected':[o['text'] for o in g['options'] if o['selected']]} for g in product['skuCandidates']]
    from .shop_research import latest_visit
    visit=latest_visit(c,data['tabId'])
    if visit and visit['productId']==product['productId']:offer['shopDiscovery']=visit
    if data.get('detail'):
        d=data['detail']
        offer['researchEvidence']={'parameters':d['parameters'],'parameterText':d['parameterText'],
            'reviews':d['reviews'][:20],'reviewCoverage':'loaded sample only','questions':d['questions'][:20],
            'services':d['services'],'delivery':d['delivery'],
            'images':[{k:r.get(k) for k in ('src','width','height','region','skuAssociation')} for r in d['images'][:20]],
            'commerce':d.get('commerce'),'observedAt':stamp(),'selectedSku':product['selectedSku'],'claims':'Merchant descriptions and buyer feedback are not independently verified.'}
    offer.update(candidateId=hashlib.sha256(json.dumps([product['productId'], product['selectedSku']], ensure_ascii=False).encode()).hexdigest()[:20],
        notes=c.args.get('notes', '')[:2000], finalPrice=None, shipping=None,
        warning='Visible selected-SKU offer only. Coupon eligibility, shipping and checkout price unverified.')
    file = c.out / 'research-candidates.json'
    saved = load_json(file, {'version': 1, 'candidates': {}})
    previous=saved['candidates'].get(offer['candidateId'],{})
    if previous.get('invoiceEvidence'):offer['invoiceEvidence']=previous['invoiceEvidence']
    saved['candidates'][offer['candidateId']] = offer
    atomic_json(file, saved)
    return {'saved': True, 'candidate': offer}


def offline(c):
    action = c.args['operation']
    if action == 'research_progress':
        return {'progress': load_json(c.out / 'research-progress.json', None),
            'note': 'Checkpoint only; read live shopping_state to resume. No URLs are opened.'}
    values = list(load_json(c.out / 'research-candidates.json', {'candidates': {}})['candidates'].values())
    ids = c.args.get('candidateIds')
    if ids is not None:
        found = {v['candidateId'] for v in values}
        if set(ids) - found: raise ValueError('Unknown candidateId.')
        values = [v for v in values if v['candidateId'] in ids]
    return {'candidates': values, 'automaticRanking': None, 'comparisonStatus': 'needs-ai-review',
        'criteria': c.args.get('criteria', ''),
        'note': 'Compare exact SKU, quantity and units first. Never rank conditional/minimum/list prices as final prices. Saved offers may be stale.'}


def resume_shopping(c):
    """User-authorized window recovery; only an empty session may open the fixed home."""
    pages = [p for p in c.pages if supported(p.url)]
    requested = c.args.get('tabId')
    if requested:
        page = next((p for p in pages if c.tab_id(p) == requested), None)
        if page is None:
            raise RuntimeError('NEEDS_TAB_SWITCH: requested shopping tab is no longer present.')
    else:
        bound = c.focus.load().get('activeTabId')
        page = next((p for p in pages if c.tab_id(p) == bound), None)
        if page is None and pages:
            visible = [p for p in pages if p.evaluate('document.visibilityState') == 'visible']
            if len(visible) == 1: page = visible[0]
            elif len(pages) == 1: page = pages[0]
            else:
                return {'action':'resume_shopping','confirmed':False,'reason':'Choose an existing tabId from inventory.',
                        'tabs':[{'tabId':c.tab_id(p),'url':p.url} for p in pages]}
    recovery = 'reused-existing-tab'
    if page is None:
        attempt_file = c.out / 'home-recovery-state.json'
        attempt = load_json(attempt_file, {})
        if attempt.get('status') == 'attempted' and any(c.tab_id(p) == attempt.get('tabId') for p in c.pages):
            raise RuntimeError('UNSUPPORTED: prior homepage navigation remains unconfirmed; inspect its original tab without retry.')
        # Reuse only a genuinely empty blank document, never an arbitrary/manual page.
        blanks = [p for p in c.pages if p.url == 'about:blank' and p.evaluate(
            "!document.body?.textContent?.trim() && !document.querySelector('input,textarea,[contenteditable],iframe')")]
        if blanks:
            page = blanks[0]
            recovery = 'reused-empty-blank'
        else:
            budget = c.tab_budget.enforce(reserve=1)
            if budget['blocked']:
                return {'action':'resume_shopping','confirmed':False,'reason':'TAB_LIMIT_REACHED: protected tabs prevent opening homepage.','tabBudget':budget}
            page = c.context.new_page()
            recovery = 'created-homepage-tab'
        c.focus.window(page, restore=True)
        page.bring_to_front()
        atomic_json(attempt_file, {'status':'attempted','tabId':c.tab_id(page),'at':stamp()})
        page.goto('https://www.taobao.com/', wait_until='domcontentloaded')
        c.guard(page)
        atomic_json(attempt_file, {'status':'opened','tabId':c.tab_id(page),'at':stamp()})
        atomic_json(c.home_state_file, {'homeOpened':True,'at':stamp()})
    # Restore before guard so a login/verification page can be handled in its original window.
    c.focus.window(page, restore=True)
    page.bring_to_front()
    c.guard(page)
    c.focus.activate(page, background=True, restore_window=True)
    return {'action':'resume_shopping','confirmed':True,'recovery':recovery,'state':publish(c,read(c,page))}


def _run(c):
    operation = c.args.get('operation')
    from .merchant_inbox import OPERATIONS as INBOX_OPERATIONS, run as inbox_run
    if operation in INBOX_OPERATIONS:
        return inbox_run(c)
    from .favorites import OPERATIONS as FAVORITES, run as favorites_run
    if operation in FAVORITES:
        return favorites_run(c)
    if operation == 'preview_merchant_wording':
        from .merchant_wording import preview
        return preview(c.args)
    from .workflows import OPERATIONS as WORKFLOWS, run as workflow_run
    if operation in WORKFLOWS:
        return workflow_run(c)
    from .merchant_chat import OPERATIONS as CHAT_OPERATIONS, run as chat_run
    if operation in CHAT_OPERATIONS:
        return chat_run(c)
    if operation in ('compare_candidates', 'research_progress'):
        return offline(c)
    if operation == 'shopping_state': return state(c)
    if operation == 'resume_shopping': return resume_shopping(c)
    if operation in ('set_tab_limit','trim_product_tabs'):
        report=c.tab_budget.configure(c.args.get('maxTabs')) if operation=='set_tab_limit' else c.tab_budget.enforce()
        return {'action':operation,'configured':operation=='set_tab_limit','confirmed':not report['blocked'],'tabBudget':report}
    if operation=='activate_shopping_tab':
        page=page_for(c,False);c.focus.activate(page,background=c.args.get('background',True),restore_window=c.args.get('restoreWindow',False))
        return {'action':operation,'confirmed':True,'state':publish(c,read(c,page))}
    if operation=='return_to_results':
        if c.args.get('tabId') and c.args['tabId']!=c.focus.load().get('activeTabId'):raise RuntimeError('NEEDS_TAB_SWITCH: return_to_results applies to the bound tab only.')
        from .shop_research import latest_visit,return_to_shop
        current=page_for(c)
        if latest_visit(c,c.tab_id(current)):return return_to_shop(c,current)
        page=c.focus.related_results();c.focus.activate(page)
        return {'action':operation,'confirmed':True,'state':publish(c,read(c,page))}
    if operation in ('search_products','search_shop_products'):
        page = page_for(c);c.focus.allow(page,'search');c.focus.prepare_action(page);before = read(c, page)
        keyword = str(c.args.get('keyword', '')).strip()
        if not keyword: raise ValueError('Search needs keyword.')
        scope = 'shop' if operation=='search_shop_products' else c.args.get('scope', 'global')
        if scope not in ('global', 'shop'): raise ValueError('Unknown search scope.')
        target=c.args.get('target','products')
        if target not in ('products','shops') or scope=='shop' and target!='products':raise ValueError('Invalid search target/scope.')
        if scope=='shop' and before['pageType']!='shop':raise RuntimeError('WRONG_PAGE_TYPE: enter the shop before searching within it.')
        mode=before['shopDom'].get('searchTarget')
        if target=='shops' or mode=='shops' and target=='products':
            if scope!='global':raise RuntimeError('UNSUPPORTED: shop discovery requires global search.')
            if mode!=target:
                choices=[r for r in before['controls'] if r['action']=='search_target' and r.get('target')==target and not r['disabled']]
                if len(choices)!=1:raise RuntimeError('UNSUPPORTED: no unambiguous visible search-target control.')
                deliver(c,page,before,{'kind':'controls',**choices[0]});page=clicked_target(c,page,False)
                before=wait_result(c,page,before,lambda d:d['shopDom']['searchTarget']==target)
                if before['shopDom']['searchTarget']!=target:return outcome(c,page,operation,before,before,False,'Search target was not confirmed.',partialChanges=['search-target-click'])
                # Switching modes invalidates the caller control; discover the unique current search pair.
                c.args.pop('controlId',None)
        def scope_matches(r):
            return r.get('searchScope')==scope or (not r.get('searchScope') and before['pageType']!='shop' and scope=='global' and r['label']!='搜本店')
        rows = [r for r in before['controls'] if r['action'] == 'search' and not r['disabled'] and scope_matches(r)]
        if c.args.get('controlId'):
            chosen, _ = saved_record(c, page, c.args['controlId']); rows = [chosen] if chosen.get('action') == 'search' and scope_matches(chosen) else []
        if len(rows) != 1: raise RuntimeError('Choose one visible search controlId; no ambiguous search submitted.')
        loc=native_locator(page,before,{'kind':'controls',**rows[0]})
        local=loc.locator('xpath=ancestor::form[1]').locator('input[name="q"],input[name="keyword"],input[name="keywords"],input[type="search"]')
        fields=[f for f in local.all() if f.is_visible() and f.is_editable()]
        if rows[0].get('fieldPath'):field=page.locator(rows[0]['fieldPath'])
        elif scope=='shop':raise RuntimeError('UNSUPPORTED: shop input/button pairing is ambiguous; no input edited.')
        else:field=fields[0] if len(fields)==1 else None
        if field is None: raise RuntimeError('No visible editable search field.')
        if scope=='shop' and rows[0].get('query')==keyword and before['shopDom'].get('queryEvidence',{} ) and before['shopDom']['queryEvidence']['value']==keyword and (before['products'] or before['noResults']):
            return outcome(c,page,operation,before,before,True,alreadySatisfied=True,clicks=0,requestedScope=scope)
        c.pause(page);c.guard(page);c.focus.require(page)
        ready = read(c, page)
        if search_context(ready) != search_context(before): raise RuntimeError('Search context changed before input; no submission.')
        refreshed = [r for r in ready['controls'] if r['signature'] == rows[0]['signature'] and not r['disabled']]
        if len(refreshed) != 1:raise RuntimeError('Search pair changed before input; no submission.')
        loc = native_locator(page, ready, {'kind':'controls', **refreshed[0]})
        field = page.locator(refreshed[0]['fieldPath']) if refreshed[0].get('fieldPath') else loc.locator('xpath=ancestor::form[1]').locator('input[name="q"],input[name="keyword"],input[name="keywords"],input[type="search"]')
        if field.count() != 1 or not field.is_visible() or not field.is_editable():raise RuntimeError('Search input is no longer unambiguous/editable.')
        search_progress(c, stage='filling', inputMayHaveChanged=True)
        field.fill(keyword)
        search_progress(c, stage='input_filled', inputChanged=True)
        current = read(c, page)
        row = next((r for r in current['controls'] if r['signature'] == rows[0]['signature']), None)
        if not row: raise RuntimeError('Search control changed after input; no submission.')
        pages_before = set(c.pages)
        deliver(c, page, current, {'kind':'controls', **row}, paced=True)
        page.wait_for_timeout(1200)
        new = [p for p in c.pages if p not in pages_before]
        for p in new:c.guard(p)
        page=clicked_target(c,page,True)
        def matches(x):
            if scope=='shop':
                from .shop_research import same_shop
                pair_matches=any(p['scope']=='shop' and p['fieldPath'] and p['query']==keyword for p in x['shopDom']['searchPairs'])
                return same_shop(before['shopDom']['identity'],x['shopDom']['identity']) and pair_matches and (x['shopDom'].get('queryEvidence') or {}).get('value')==keyword and bool(x['products'] or x['noResults'])
            committed = parse_qs(urlparse(x['url']).query).get('q', [None])[0]
            return committed==keyword and x['query']==keyword and bool(x['products'] or x['noResults'] or target=='shops' and x['shopDom']['shops']) and (target!='shops' or x['shopDom']['searchTarget']=='shops')
        after = wait_result(c, page, current, matches)
        confirmed = matches(after) and (changed(current, after) or before['query'] == keyword)
        search_progress(c, stage='completed' if confirmed else 'unconfirmed', outcomeUnknown=not confirmed, resultsBelongToRequestedQuery=bool(confirmed))
        return outcome(c, page, operation, before, after, confirmed,siteOpenedTabs=len(new), requestedScope=scope,target=target,clicks=1,partialChanges=['keyword-input','search-click'])
    page = page_for(c)
    read_only={'list_products','read_selected_offer','save_candidate','detail_state','shop_state','list_shops',
        'read_product_parameters','read_reviews','read_product_questions','read_product_evidence','read_shop_reputation','read_delivery_services',
        'product_image_overview','read_product_image'}
    interaction=operation not in read_only or operation in ('read_shop_reputation','read_delivery_services') and bool(c.args.get('controlId'))
    if interaction:c.focus.prepare_action(page)
    from .image_research import OPERATIONS as IMAGE_OPERATIONS,run as image_run
    if operation in IMAGE_OPERATIONS:return image_run(c,page,operation)
    from .shop_research import OPERATIONS as SHOP_OPERATIONS,run as shop_run
    if operation in SHOP_OPERATIONS:return shop_run(c,page,operation)
    from .detail_research import OPERATIONS, run as detail_run
    if operation in OPERATIONS:return detail_run(c,page,operation)
    required={'set_sort':'sort','set_filters':'filter_option','go_to_page':'page_jump',
              'select_sku':'select_sku','read_selected_offer':'section','save_candidate':'select_sku','load_more':'next_page'}
    if operation in required:c.focus.allow(page,required[operation])
    if operation == 'set_sort': return set_sort(c, page)
    if operation == 'set_filters': return filters(c, page)
    if operation == 'go_to_page':
        before=read(c,page);number=c.args.get('pageNumber')
        if not isinstance(number,int) or isinstance(number,bool) or number<1:raise ValueError('pageNumber must be a positive integer.')
        if before['totalPages'] and number>before['totalPages']:raise ValueError('Requested page exceeds visible page count.')
        if before['currentPage']==number:return outcome(c,page,operation,before,before,True,alreadySatisfied=True)
        direct=[x for x in before['controls'] if x['action']=='page_number' and x['pageNumber']==number]
        if len(direct)==1:
            deliver(c,page,before,{'kind':'controls',**direct[0]})
        else:
            fields=[f for f in before['fields'] if f['kind']=='page_number']
            if len(fields)!=1:raise RuntimeError('No unique visible page-number input.')
            button=record_for(before,'page_jump')
            c.pause(page);c.guard(page);c.focus.require(page)
            if revision(read(c,page))!=revision(before):raise RuntimeError('Page changed before jump.')
            page.locator('input').nth(fields[0]['index']).fill(str(number))
            current=read(c,page);record=next((x for x in current['controls'] if x['signature']==button['signature']),None)
            if record is None:raise RuntimeError('Jump control changed after input; no submission.')
            deliver(c,page,current,{'kind':'controls',**record})
        after=wait_result(c,page,before,lambda x:x['currentPage']==number)
        return outcome(c,page,operation,before,after,after['currentPage']==number)
    if operation == 'select_sku': return select_sku(c, page)
    if operation == 'save_candidate': return candidate(c, page)
    if operation == 'click_shopping_control': return click(c, page)
    if operation == 'list_products':
        data = read(c, page)
        if data['pageType'] not in ('search','shop'):raise ValueError('Read product cards from a search or shop list.')
        public=publish(c,data)
        return {'tabId': data['tabId'], 'products': public['products'], 'noResults': data['noResults'], 'sort': data['sort'], 'filters': data['filters'], 'observedAt': stamp(),'state':public}
    if operation == 'read_selected_offer':
        data = read(c, page)
        if data['pageType'] != 'product': raise ValueError('Requires a product page.')
        return {'product': data['product'], 'allSkuSelected': bool(data['product']['skuCandidates']) and inspect(page, 'all-selected'), 'sections': data['sections'],
            'commerce':data['detail'].get('commerce'),
            'finalPrice': None, 'shipping': None, 'note': 'Read current page without reload. Final payment price and coupon eligibility unverified.'}
    if operation == 'load_more':
        before = read(c, page)
        if before['pageType'] not in ('search', 'shop'): raise ValueError('Requires a result list.')
        c.pause(page);c.guard(page);c.focus.require(page)
        ready=read(c,page);preflight=list_load_evidence(before,ready)
        if preflight['contextChanged'] or preflight['removedProductIds']:
            return outcome(c,page,operation,before,ready,False,'List context or existing products changed while waiting; no scroll performed.',code='LIST_CHANGED',scrolled=False,loadEvidence=preflight)
        before=ready
        metrics = page.evaluate('({top:scrollY,height:document.documentElement.scrollHeight,viewport:innerHeight})')
        if metrics['top'] >= metrics['height'] - metrics['viewport'] - 2:
            if metrics['top']>2:page.mouse.wheel(0,-round(metrics['viewport']*uniform(.2,.5)))
            return outcome(c, page, operation, before, read(c,page), True, alreadyAtBottom=True,loadEvidence={'scope':'current document boundary only; not full server result coverage'})
        pixels=round(metrics['viewport'] * uniform(.5,2.5))
        page.mouse.wheel(0, pixels)
        def observed(d):
            e=list_load_evidence(before,d)
            return e['contextChanged'] or bool(e['newProductIds'] or e['removedProductIds'] or e['readyImageChangedProductIds'])
        after = wait_result(c, page, before,observed)
        end = page.evaluate('scrollY>=document.documentElement.scrollHeight-innerHeight-2')
        evidence=list_load_evidence(before,after)
        replaced=evidence['contextChanged'] or bool(evidence['removedProductIds'])
        new_ids=[] if replaced else evidence['newProductIds']
        return outcome(c, page, operation, before, after, not replaced and (bool(new_ids or evidence['readyImageChangedProductIds']) or end),
            'List replaced/context changed; additions are not verified lazy loading.' if replaced else 'Scrolled, but no additional products, image updates or document boundary evidence.',
            code='LIST_REPLACED' if replaced else None,atBottom=end,scrolled=True,scrollPixels=pixels,newProductIds=new_ids,loadEvidence=evidence,
            scope='One bounded scroll; image DOM changes do not prove network downloads or complete result coverage.')
    raise ValueError('Unknown shopping operation.')


def run(c):
    c.tab_budget.closed_this_call=[]
    c.tab_budget.last_report=None
    result=_run(c)
    operation=c.args.get('operation')
    if operation in ('compare_candidates','research_progress','preview_merchant_wording'):return result
    readonly={'shopping_state','list_products','read_selected_offer','save_candidate','detail_state','shop_state','list_shops',
        'read_product_parameters','read_reviews','read_product_questions','read_product_evidence',
        'read_shop_reputation','read_delivery_services','product_image_overview','read_product_image'}
    from .merchant_chat import READONLY as CHAT_READONLY
    readonly.update(CHAT_READONLY)
    from .merchant_inbox import READONLY as INBOX_READONLY
    readonly.update(INBOX_READONLY)
    from .favorites import READONLY as FAVORITE_READONLY
    readonly.update(FAVORITE_READONLY)
    if operation in ('set_tab_limit','trim_product_tabs'):
        report=result['tabBudget']
    elif operation in readonly:
        report=c.tab_budget.status()
    else:
        report=c.tab_budget.enforce()
    if operation not in readonly:
        # Include closures made while reserving/adopting a site-opened popup.
        report['closedTabs']=list({r['tabId']:r for r in c.tab_budget.closed_this_call}.values())
        data=c.tab_budget.load();data['lastCleanup']=report;atomic_json(c.tab_budget.file,data)
    result['tabBudget']=report
    if isinstance(result.get('state'),dict):result['state']['tabBudget']=report
    return result
