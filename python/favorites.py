"""Separate local bookmarks and scoped Taobao favorites, using observed controls only."""
import copy
import hashlib
import json
import time
import uuid
from random import uniform

from .huoyan_browser import atomic_json, load_json, dom_script, product_identity, stamp

OFFLINE = {'list_local_favorites', 'remove_local_favorite'}
READONLY = OFFLINE | {'favorite_options', 'taobao_favorites_state', 'save_local_favorite', 'open_local_favorite'}
OPERATIONS = READONLY | {'open_local_favorite', 'set_taobao_favorite', 'open_taobao_favorites', 'find_taobao_favorite', 'open_taobao_favorite'}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def library(c):
    return load_json(c.out / 'local-favorites.json', {'version': 1, 'favorites': {}})


def protected_tabs(c):
    db=load_json(c.out/'favorite-actions.json',{})
    if db.get('endpoint')!=c.endpoint:return set()
    return {a['intent']['tabId'] for a in db.get('attempts',{}).values()
            if a.get('dispatchAttempted') and not a.get('confirmed')}


def local_record(c):
    row = library(c)['favorites'].get(c.args.get('favoriteId'))
    if not row:
        raise ValueError('Unknown local favoriteId; list_local_favorites first.')
    if product_identity(row['url'])['key'] != row['favoriteId']:
        raise RuntimeError('FAVORITE_CORRUPT: saved identity and URL disagree.')
    return row


def offline(c):
    db = library(c)
    if c.args['operation'] == 'remove_local_favorite':
        key = c.args.get('favoriteId')
        removed = db['favorites'].pop(key, None)
        if removed:
            atomic_json(c.out / 'local-favorites.json', db)
        return {'scope': 'local', 'removed': bool(removed), 'favoriteId': key, 'taobaoAccountChanged': False}
    query = c.args.get('query', '').strip().casefold()
    values = [copy.deepcopy(v) for v in db['favorites'].values() if not query or query in json.dumps(
        [v.get('title'), v.get('productId'), v.get('note'), v.get('tags'), list(v.get('skuSnapshots', {}).values())], ensure_ascii=False).casefold()]
    values.sort(key=lambda r: r['updatedAt'], reverse=True)
    limit = c.args.get('limit', 50)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise ValueError('limit must be 1..200.')
    return {'scope': 'local', 'favorites': values[:limit], 'totalMatches': len(values), 'cached': True,
            'taobaoAccountChanged': False, 'contentIsUntrusted':True, 'note': 'Historical saved snapshots; price, stock and selected SKU are not current.'}


def save_local(c, page):
    from .shopping_research import read
    data = read(c, page)
    if data['pageType'] != 'product':
        raise RuntimeError('WRONG_PAGE_TYPE: save local favorites from a bound product page.')
    identity = product_identity(page.url)
    product = data['product']
    db = library(c)
    prior = db['favorites'].get(identity['key'], {})
    row = {**prior, 'favoriteId': identity['key'], 'productId': identity['productId'], 'url': identity['url'],
           'title': product['title'], 'createdAt': prior.get('createdAt', stamp()), 'updatedAt': stamp(),
           'sourceTabId': c.tab_id(page), 'scope': 'local', 'platformFavoriteState': 'unverified'}
    row.setdefault('note', '')
    row.setdefault('tags', [])
    if 'note' in c.args:
        row['note'] = c.args['note']
    if 'tags' in c.args:
        row['tags'] = list(dict.fromkeys(c.args['tags']))
    if not isinstance(row['note'], str) or len(row['note']) > 2000 or not isinstance(row['tags'], list) or len(row['tags']) > 20 or any(not isinstance(t, str) or len(t) > 60 for t in row['tags']):
        raise ValueError('Local note/tags exceed limits.')
    selected = product.get('selectedSku', [])
    complete = all(any(o['selected'] for o in g['options']) for g in data['detail']['skuGroups'])
    key = digest(selected)[:20]
    # Keep a bounded, explicitly historical summary; no credentials/control IDs.
    snapshot = {k: product.get(k) for k in ('title', 'selectedSku', 'price', 'displayPrice', 'observedAt')}
    snapshot.update(skuSelectionComplete=complete, pricing=product.get('commerce', {}).get('pricing'),
                    priceVerification='historical visible evidence, not current payable total')
    row.setdefault('skuSnapshots', {})[key] = snapshot
    if len(row['skuSnapshots']) > 50:
        row['skuSnapshots'] = dict(list(row['skuSnapshots'].items())[-50:])
    db['favorites'][identity['key']] = row
    atomic_json(c.out / 'local-favorites.json', db)
    return {'scope': 'local', 'saved': True, 'favorite': row, 'taobaoAccountChanged': False}


def probe(c, page):
    c.guard(page)
    c.focus.require(page)
    return page.evaluate(dom_script('favoritesDom.js'))


def publish(c, page, raw=None):
    raw = raw or probe(c, page)
    file = c.out / 'favorite-controls.json'
    db = load_json(file, {})
    if db.get('endpoint') != c.endpoint:
        db = {'endpoint': c.endpoint, 'tabs': {}}
    generation = uuid.uuid4().hex
    records, controls = {}, []
    for r in raw['controls']:
        ref = digest([generation, r['signature']])[:24]
        records[ref] = r
        controls.append({k: v for k, v in r.items() if k not in ('elementPath', 'signature', 'href', 'fieldPath')} | {'controlId': ref})
    db['tabs'][c.tab_id(page)] = {'url': page.url, 'records': records}
    atomic_json(file, db)
    cards = [{k: v for k, v in row.items() if k != 'signature'} | {'controlIds': [r['controlId'] for r in controls if r.get('productId') == row['productId'] and r['action'] == 'open_taobao_favorite']} for row in raw['cards']]
    return {'scope': 'taobao', 'tabId': c.tab_id(page), 'isFavoritesPage': raw['isFavoritesPage'],
            'productId': raw['productId'], 'controls': controls, 'products': cards, 'empty': raw['empty'],
            'observedAt': stamp(), 'coverage': raw['coverage'], 'iframeCount': len(page.frames) - 1,'contentIsUntrusted':True,
            'note': 'Current page evidence only. Taobao favorites are product-level; saved local SKU is independent.'}


def record(c, page, action, ref=None):
    raw = probe(c, page)
    if ref:
        db = load_json(c.out / 'favorite-controls.json', {})
        saved = db.get('tabs', {}).get(c.tab_id(page), {}) if db.get('endpoint') == c.endpoint else {}
        old = saved.get('records', {}).get(ref)
        if saved.get('url') != page.url or not old or old['action'] != action:
            raise RuntimeError('STALE_FAVORITE_CONTROL: read favorite_options again.')
        rows = [r for r in raw['controls'] if r['signature'] == old['signature']]
    else:
        rows = [r for r in raw['controls'] if r['action'] == action and not r['disabled']]
    if len(rows) != 1 or rows[0]['disabled']:
        raise RuntimeError('FAVORITE_CONTROL_UNAVAILABLE: choose one currently observed, enabled controlId.')
    return rows[0], raw


def click(c, page, row, before, paced=False):
    """One bounded native click; exact target identity checked before/after pacing."""
    c.focus.prepare_action(page)
    if not paced:c.pause(page)
    current = probe(c, page)
    if current['url'] != before['url'] or current['productId'] != before['productId'] or not any(r['signature'] == row['signature'] for r in current['controls']):
        raise RuntimeError('STALE_FAVORITE_CONTROL: context changed during wait; no click.')
    loc = page.locator(row['elementPath'])
    loc.scroll_into_view_if_needed(timeout=5000)
    loc.click(trial=True, timeout=5000)
    current = probe(c, page)
    if current['url'] != before['url'] or not any(r['signature'] == row['signature'] for r in current['controls']):
        raise RuntimeError('STALE_FAVORITE_CONTROL: control changed during native preflight.')
    c.tab_budget.before_popup(page, loc)
    return loc


def set_platform(c, page):
    desired = c.args.get('selected', True)
    request = c.args.get('requestId')
    if not isinstance(desired, bool) or not isinstance(request, str) or not 1 <= len(request) <= 120:
        raise ValueError('selected boolean and stable requestId length 1..120 required.')
    identity = product_identity(page.url)
    file = c.out / 'favorite-actions.json'
    db = load_json(file, {'endpoint': c.endpoint, 'attempts': {}})
    if db.get('endpoint') != c.endpoint:
        raise RuntimeError('FAVORITE_SESSION_CHANGED: action journal belongs to another endpoint.')
    intent = {'productKey': identity['key'], 'selected': desired, 'tabId': c.tab_id(page)}
    old = db['attempts'].get(request)
    if old:
        if old['intent'] != intent:
            raise RuntimeError('FAVORITE_REQUEST_CONFLICT: requestId belongs to another intent.')
        raw = probe(c, page)
        values = [r['selected'] for r in raw['controls'] if r['action'] == 'set_taobao_favorite']
        satisfied = bool(values) and all(v is desired for v in values)
        if satisfied and not old.get('confirmed'):
            old.update(confirmed=True,status='reconciled_current_desired_state',observedAt=stamp());atomic_json(file,db)
        return {'scope': 'taobao', 'replayed': True, 'confirmed': satisfied, 'attempt': old,
                'currentState': values[0] if len(values) == 1 else None, 'retryAllowed': False, 'state': publish(c, page, raw)}
    row, raw = record(c, page, 'set_taobao_favorite', c.args.get('controlId'))
    if row['selected'] is desired:
        db['attempts'][request]={'intent':intent,'createdAt':stamp(),'dispatchAttempted':False,'confirmed':True,'status':'already_satisfied'}
        atomic_json(file,db)
        return {'scope': 'taobao', 'confirmed': True, 'alreadySatisfied': True, 'clicks': 0, 'state': publish(c, page, raw)}
    if row['selected'] is None:
        raise RuntimeError('FAVORITE_STATE_UNKNOWN: cannot toggle an unverified state.')
    unresolved = [a for a in db['attempts'].values() if a['intent']['productKey'] == identity['key'] and a.get('dispatchAttempted') and not a.get('confirmed')]
    if unresolved:
        raise RuntimeError('FAVORITE_OUTCOME_UNKNOWN: inspect original page; do not retry under another requestId.')
    loc = click(c, page, row, raw)
    attempt = {'intent': intent, 'createdAt': stamp(), 'dispatchAttempted': True, 'confirmed': False, 'status': 'dispatching'}
    db['attempts'][request] = attempt
    atomic_json(file, db)  # Persist the unknown outcome BEFORE touching account state.
    try:
        c.focus.require(page);c.guard(page)
        loc.click(timeout=5000)
        deadline = time.monotonic() + c.args.get('favoriteTimeoutMs', 4000) / 1000
        while True:
            after = probe(c, page)
            if after['productId'] != identity['productId']:
                raise RuntimeError('PRODUCT_CHANGED: favorite outcome belongs to another page.')
            values = [r['selected'] for r in after['controls'] if r['action'] == 'set_taobao_favorite']
            if values and all(v is desired for v in values):
                attempt.update(confirmed=True, status='observed_desired_state', observedAt=stamp())
                break
            if time.monotonic() >= deadline:
                break
            page.wait_for_timeout(150)
    except Exception as error:
        attempt['error'] = str(error)
        attempt['status'] = 'outcome_unknown'
    atomic_json(file, db)
    return {'scope': 'taobao', 'confirmed': attempt['confirmed'], 'attempt': attempt, 'retryAllowed': False,
            'state': publish(c, page), 'note': 'Verified UI state only; no claim of independent server persistence.'}


def enter_folder(c, page):
    from .shopping_research import clicked_target
    raw = probe(c, page)
    if raw['isFavoritesPage']:
        return page, {'confirmed': True, 'reused': True, 'state': publish(c, page, raw)}
    live = [p for p in c.pages if p is not page and favorites_url(p.url)]
    if len(live) == 1:
        c.guard(live[0]);c.focus.bind(live[0], origin=page)
        return live[0], {'confirmed': True, 'reused': True, 'state': publish(c, live[0])}
    if len(live) > 1:
        raise RuntimeError('FAVORITES_AMBIGUOUS: choose an existing favorites tab explicitly.')
    row, raw = record(c, page, 'open_taobao_favorites', c.args.get('controlId'))
    loc = click(c, page, row, raw)
    c.focus.begin(page);loc.click(timeout=5000)
    target = clicked_target(c, page, allow_popup=True)
    target.wait_for_timeout(500)
    c.guard(target);c.focus.require(target)
    after = probe(c, target)
    deadline=time.monotonic()+4
    while after['isFavoritesPage'] and not after['cards'] and not after['empty'] and time.monotonic()<deadline:
        target.wait_for_timeout(200);after=probe(c,target)
    return target, {'confirmed': after['isFavoritesPage'], 'reused': False, 'state': publish(c, target, after)}


def favorites_url(url):
    from urllib.parse import urlparse
    u = urlparse(url)
    return u.scheme == 'https' and not u.username and not u.password and not u.port and (
        u.hostname == 'i.taobao.com' and u.path.rstrip('/') == '/my_itaobao/itao-tool/collect' or
        u.hostname == 'shoucang.taobao.com' and u.path in ('/item_collect.htm', '/item_collect_new.htm', '/favorite.htm'))


def open_platform_product(c, page, product_id):
    from .shopping_research import clicked_target, read, publish as research_publish
    raw = probe(c, page)
    if not raw['isFavoritesPage']:
        raise RuntimeError('WRONG_PAGE_TYPE: use the observed favorites list.')
    rows = [r for r in raw['controls'] if r['action'] == 'open_taobao_favorite' and r['productId'] == product_id]
    if not rows:
        raise RuntimeError('FAVORITE_NOT_LOADED: find the actual card first; no URL opened.')
    current = c.sync_tabs().get('taobao:' + product_id)
    if current is not None:
        c.guard(current);c.focus.bind(current, origin=page)
        return {'scope': 'taobao', 'confirmed': True, 'source': 'existing-tab', 'state': research_publish(c, read(c, current))}
    row = rows[0]
    loc = click(c, page, row, raw)
    source_url = page.url
    c.focus.begin(page);loc.click(timeout=5000)
    target = clicked_target(c, page, allow_popup=True)
    c.guard(target)
    if product_identity(target.url)['productId'] != product_id:
        raise RuntimeError('FAVORITE_DESTINATION_MISMATCH: click did not reach the requested product.')
    if target is page:
        c.focus.remember_same_tab(page, source_url, 'favorites')
    return {'scope': 'taobao', 'confirmed': True, 'source': 'clicked-favorite-card', 'state': research_publish(c, read(c, target))}


def find(c, page):
    raw = probe(c, page)
    if not raw['isFavoritesPage']:
        raise RuntimeError('WRONG_PAGE_TYPE: open_taobao_favorites first.')
    product_id, keyword = c.args.get('productId'), c.args.get('keyword', '').strip()
    if not product_id and not keyword:
        raise ValueError('Provide productId or keyword.')
    steps = c.args.get('maxScrolls', 3)
    if isinstance(steps, bool) or not isinstance(steps, int) or not 0 <= steps <= 5:
        raise ValueError('maxScrolls must be 0..5.')
    hits = lambda d: [r for r in d['cards'] if (not product_id or r['productId'] == product_id) and (not keyword or keyword.casefold() in r['title'].casefold())]
    searched=False
    searches=[r for r in raw['controls'] if r['action']=='favorites_search' and not r['disabled']]
    if keyword and not hits(raw) and len(searches)==1:
        from .shopping_research import clicked_target
        search=searches[0]
        c.focus.prepare_action(page);c.pause(page)
        current=probe(c,page)
        if current['url']!=raw['url'] or not any(r['signature']==search['signature'] for r in current['controls']):
            raise RuntimeError('FAVORITES_CONTEXT_CHANGED: stopped before search input.')
        page.locator(search['fieldPath']).fill(keyword,timeout=5000)
        loc=click(c,page,search,current,paced=True)
        c.focus.begin(page);loc.click(timeout=5000);page=clicked_target(c,page,allow_popup=False)
        page.wait_for_timeout(500);raw=probe(c,page);searched=True
        if not raw['isFavoritesPage']:
            raise RuntimeError('FAVORITES_SCOPE_CHANGED: search left the account favorites page; stopped.')
    stop, count = 'SCROLL_LIMIT', 0
    for _ in range(steps):
        if hits(raw):stop='FOUND';break
        if raw['empty']:stop='EXPLICIT_EMPTY';break
        if raw['scroll']['atBottom']:stop='AT_BOTTOM';break
        before = raw
        c.focus.prepare_action(page);c.pause(page,500,1200)
        now = probe(c, page)
        if now['url'] != before['url'] or not now['isFavoritesPage']:
            raise RuntimeError('FAVORITES_CONTEXT_CHANGED: stopped before scrolling.')
        page.mouse.move(300, 300);page.mouse.wheel(0, round(now['scroll']['viewport'] * uniform(.5, 2.5)))
        page.wait_for_timeout(450);raw=probe(c,page);count+=1
        if raw['scroll']['top'] == now['scroll']['top']:
            stop='NO_MOVEMENT';break
    if count and raw['scroll']['atBottom'] and raw['scroll']['top']>2:
        c.guard(page);c.focus.require(page)
        page.mouse.wheel(0,-round(raw['scroll']['viewport']*uniform(.2,.5)))
        page.wait_for_timeout(150);raw=probe(c,page)
    return {'scope': 'taobao', 'found': bool(hits(raw)), 'products': [{k:v for k,v in r.items() if k!='signature'} for r in hits(raw)],
            'scrolls': count, 'searchedFavorites':searched, 'stopReason': 'FOUND' if hits(raw) else stop, 'state': publish(c, page, raw),
            'coverage': 'loaded content only; not found does not prove absent from account; no unbounded paging'}


def run(c):
    from .shopping_research import page_for, read, publish as research_publish
    operation = c.args['operation']
    if operation in OFFLINE:return offline(c)
    if operation == 'open_local_favorite':
        row=local_record(c)
        live=c.sync_tabs().get(row['favoriteId'])
        if live is not None:
            c.guard(live);c.focus.activate(live, background=True, restore_window=True)
            return {'scope':'local','confirmed':True,'source':'existing-tab','favorite':row,'state':research_publish(c,read(c,live)),
                    'skuRestored':False,'note':'Current SKU is reported, never silently replaced by saved SKU.'}
        if not c.args.get('fresh',False):
            return {'scope':'local','confirmed':True,'source':'local-cache','favorite':row,'cached':True,'stale':True,
                    'pageOpened':False,'nextAction':'For live data pass fresh=true and an existing shopping tab; use real favorites card navigation.'}
        page=page_for(c)
        page,result=enter_folder(c,page)
        if not result['confirmed']:return result
        original=dict(c.args)
        try:
            c.args={**original,'productId':row['productId'],'keyword':''}
            located=find(c,page)
            if not located['found']:
                return {'scope':'local','confirmed':False,'source':'local-cache','favorite':row,'stale':True,
                        'reason':'Local favorite is not a confirmed account favorite; no loaded Taobao favorites card found.', 'lookup':located}
            opened=open_platform_product(c,page,row['productId']);opened.update(scope='local',favorite=row,skuRestored=False)
            return opened
        finally:c.args=original
    page=page_for(c)
    if operation=='save_local_favorite':return save_local(c,page)
    if operation in ('favorite_options','taobao_favorites_state'):
        raw=probe(c,page)
        if operation=='taobao_favorites_state' and not raw['isFavoritesPage']:
            raise RuntimeError('WRONG_PAGE_TYPE: open the actual favorites page first.')
        return publish(c,page,raw)
    if operation=='set_taobao_favorite':
        c.focus.allow(page,'set_taobao_favorite')
        return set_platform(c,page)
    if operation=='open_taobao_favorites':return enter_folder(c,page)[1]
    if operation=='find_taobao_favorite':return find(c,page)
    if operation=='open_taobao_favorite':
        product_id=c.args.get('productId')
        if c.args.get('controlId'):
            row,_=record(c,page,'open_taobao_favorite',c.args['controlId']);product_id=row['productId']
        if not isinstance(product_id,str) or not product_id.isdigit():raise ValueError('Provide a loaded productId or current favorites card controlId.')
        return open_platform_product(c,page,product_id)
    raise ValueError('Unknown favorites operation.')
