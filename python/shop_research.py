"""Shop discovery and verified in-page flows, sharing shopping controls and focus rules."""
import json
from urllib.parse import urlparse
from .huoyan_browser import atomic_json,load_json,dom_script,stamp,product_identity

OPERATIONS={'shop_state','list_shops','open_shop','search_shop_products','open_shop_section','open_shop_category','open_shop_product','return_to_shop_results'}


def probe(page):
    return page.evaluate(dom_script('shopPageDom.js'))


def enrich(c,page,data):
    shop=probe(page);data['shopDom']=shop
    if shop['isShopPage'] and data['pageType']!='product':data['pageType']='shop'
    elif data['pageType']=='shop':data['pageType']='search' if urlparse(page.url).hostname=='shopsearch.taobao.com' else 'other'
    # Replace heuristic shop links with observed, supported identity-bearing links.
    data['controls']=[r for r in data['controls'] if r['action']!='open_shop']
    paths=page.locator(data['selector']).evaluate_all('els=>els.map(e=>{const p=[];for(;e&&e.nodeType===1;e=e.parentElement){if(e===document.documentElement){p.unshift("html");break;}p.unshift(e.tagName.toLowerCase()+":nth-child("+([...e.parentElement.children].indexOf(e)+1)+")");}return p.join(" > ")})')
    for r in data['controls']:
        geometry=next((p for p in shop['controlVisibility'] if p['elementPath']==paths[r['index']]),None)
        if geometry:r.update({k:v for k,v in geometry.items() if k not in ('elementPath','disabled')})
        if r['action']!='search':continue
        pair=next((p for p in shop['searchPairs'] if p['buttonPath']==paths[r['index']]),None)
        if pair:
            r.update(searchScope=pair['scope'],fieldPath=pair['fieldPath'],elementPath=pair['buttonPath'],pairing=pair['pairing'],query=pair['query'])
            r['signature']=json.dumps([r['signature'],pair['scope'],pair['fieldPath']])
    for i,row in enumerate(shop['controls']):
        data['controls'].append({'index':len(paths)+i,**row})
    if data['pageType']=='shop':
        data['query']=shop['query'];data['searchScope']='shop'
    for p in data['products']:
        regions=[r['region'] for r in shop['productRegions'] if product_match(r['href'],p['productId'])]
        p['region']='shop-products' if regions and set(regions)=={'shop-products'} else 'recommendation' if 'recommendation' in regions else 'unverified'
        p['shopMembership']='page-container-evidence' if p['region']=='shop-products' and shop['identity'] else 'unverified'
    sync_registry(c,page,shop['identity'])
    return data


def product_match(url,product_id):
    try:return product_identity(url)['productId']==product_id
    except ValueError:return False


def sync_registry(c,page,identity):
    file=c.out/'shop-tabs.json';db=load_json(file,{'endpoint':c.endpoint,'tabs':{}})
    if db.get('endpoint')!=c.endpoint:db={'endpoint':c.endpoint,'tabs':{}}
    live={c.tab_id(p):p.url for p in c.pages}
    for tab,row in db['tabs'].items():row['status']='closed' if tab not in live else 'navigated' if live[tab]!=row['url'] else 'live'
    if identity:db['tabs'][c.tab_id(page)]={'identity':identity,'url':page.url,'status':'live','observedAt':stamp()}
    atomic_json(file,db)


def publish_shop(data,public,generation):
    raw=data['shopDom'];identity=raw['identity']
    if data['pageType']!='shop':return
    controls=[r for r in public['controls'] if r['action'] in ('search','shop_section','shop_category','sort','sort_direction','filter_panel','filter_option','apply_filters','clear_filters','next_page','previous_page','page_number','page_jump','open_product')]
    methods={'search':'search_shop_products','shop_section':'open_shop_section','shop_category':'open_shop_category','sort':'set_sort','sort_direction':'set_sort','filter_panel':'click_shopping_control','filter_option':'set_filters','apply_filters':'click_shopping_control','clear_filters':'click_shopping_control','next_page':'click_shopping_control','previous_page':'click_shopping_control','page_number':'go_to_page','page_jump':'go_to_page','open_product':'open_shop_product'}
    available=[]
    for action,tool in methods.items():
        rows=[r for r in controls if r['action']==action and not r['disabled'] and (action!='search' or r.get('searchScope')=='shop' and r.get('pairing')=='same-container') and
            (action!='open_product' or next((p.get('region') for p in public['products'] if p['productId']==r.get('productId')),None)!='recommendation')]
        if rows:available.append({'tool':tool,'controlIds':[r['controlId'] for r in rows]})
    if data['products']:available.extend([{'tool':'list_products'},{'tool':'load_more','limit':'one bounded scroll'}])
    public['shop']={'identity':identity,'stage':raw['stage'],'query':raw['query'],'queryEvidence':raw['queryEvidence'],
        'sections':raw['selectedSections'],'categories':raw['selectedCategories'],'sort':data['sort'],'filters':data['filters'],
        'currentPage':data['currentPage'],'totalPages':data['totalPages'],'controls':controls,'products':public['products'],
        'availableActions':available,'stateVersion':generation,'coverage':{'scope':'currently loaded top document only','iframeCount':raw['iframeCount'],'unsupportedFrames':bool(raw['iframeCount'])}}


def same_shop(a,b):
    return bool(a and b and a['key']==b['key'])


def context(data):
    s=data.get('shopDom',{})
    return {'identity':s.get('identity'),'query':s.get('query'),'queryEvidence':s.get('queryEvidence'),
        'sections':s.get('selectedSections',[]),'categories':s.get('selectedCategories',[]),
        'sort':{k:data['sort'].get(k) for k in ('field','direction')},'filters':data['filters'],
        'currentPage':data['currentPage'],'url':data['url'],'scroll':s.get('scroll')}


def context_key(value):
    return {k:v for k,v in value.items() if k not in ('scroll','identity')} | {'shopKey':(value.get('identity') or {}).get('key')}


def remember_visit(c,before,after):
    file=c.out/'shop-visits.json';db=load_json(file,{'endpoint':c.endpoint,'visits':{},'latest':{}})
    if db.get('endpoint')!=c.endpoint:db={'endpoint':c.endpoint,'visits':{},'latest':{}}
    if before['pageType']!='shop':
        if db['latest'].pop(after['tabId'],None):atomic_json(file,db)
        return
    import uuid
    key=uuid.uuid4().hex;product_id=after['product']['productId']
    visit={'visitId':key,'productId':product_id,'productTabId':after['tabId'],'sourceTabId':before['tabId'],
        'source':context(before),'observedAt':stamp(),'sameTab':before['tabId']==after['tabId']}
    db['visits'][key]=visit;db['latest'][after['tabId']]=key
    atomic_json(file,db)


def latest_visit(c,tab_id):
    db=load_json(c.out/'shop-visits.json',{})
    if db.get('endpoint')!=c.endpoint:return None
    return db.get('visits',{}).get(db.get('latest',{}).get(tab_id))


def check_shop_transition(before,after):
    if before['pageType']=='shop' and not same_shop(before.get('shopDom',{}).get('identity'),after.get('shopDom',{}).get('identity')):
        return 'SCOPE_MISMATCH: operation left the verified shop; stop and inspect current state.'
    return None


def open_shop(c,page,control_id=None):
    from .shopping_research import read,publish,saved_record,deliver,clicked_target,wait_result,outcome
    before=read(c,page);c.focus.allow(page,'open_shop')
    if control_id:
        row,_=saved_record(c,page,control_id)
        rows=[row] if row.get('action')=='open_shop' else []
    else:rows=[r for r in before['controls'] if r['action']=='open_shop' and not r['disabled']]
    if len(rows)!=1:raise RuntimeError('UNSUPPORTED: choose one actual shop entry controlId.')
    row=rows[0];expected=row['shopIdentity'];c.focus.require(page)
    # Read only identity on inventory tabs; no full background research.
    candidates=[]
    from .shopping_research import supported
    for p in c.pages:
        if supported(p.url):
            identity=probe(p)['identity']
            if same_shop(expected,identity):candidates.append(p)
    existing=next((p for p in candidates if p is page),None) or (candidates[0] if len(candidates)==1 else None)
    if len(candidates)>1 and existing is None:raise RuntimeError('UNSUPPORTED: several matching shop tabs; activate one explicitly.')
    if existing:
        c.focus.require(page);c.focus.bind(existing,origin=page,bring=True);after=read(c,existing)
        return outcome(c,existing,'open_shop',before,after,same_shop(expected,after['shopDom']['identity']),source='existing-shop-tab',clicks=0)
    deliver(c,page,before,{'kind':'controls',**row});target=clicked_target(c,page,True)
    after=wait_result(c,target,before,lambda d:same_shop(expected,d.get('shopDom',{}).get('identity')))
    return outcome(c,target,'open_shop',before,after,same_shop(expected,after.get('shopDom',{}).get('identity')) and after['pageType']=='shop',
        'SCOPE_MISMATCH: clicked entry did not reach the expected shop.',source='clicked-shop-entry',clicks=1,expectedShop=expected)


def return_to_shop(c,page):
    from .shopping_research import read,publish,outcome
    before=read(c,page)
    if before['pageType']!='product':raise RuntimeError('WRONG_PAGE_TYPE: return from the current product only.')
    visit=latest_visit(c,before['tabId'])
    if not visit or visit['productId']!=before['product']['productId']:raise RuntimeError('SOURCE_CHANGED: no verified shop visit for this product.')
    target=next((p for p in c.pages if c.tab_id(p)==visit['sourceTabId']),None)
    if target is None:raise RuntimeError('SOURCE_CHANGED: original shop tab is closed; no URL reopened.')
    if visit['sameTab']:
        # Keep the existing strict one-step browser history verification.
        history=c.focus.load().get('returnHistory',{}).get(before['tabId'])
        if not history or history['url']!=visit['source']['url']:raise RuntimeError('SOURCE_CHANGED: original shop history changed.')
        target=c.focus.related_results()
    elif target.url!=visit['source']['url']:
        raise RuntimeError('SOURCE_CHANGED: original shop URL changed; no navigation performed.')
    c.focus.activate(target);after=read(c,target)
    valid=after['pageType']=='shop' and context_key(context(after))==context_key(visit['source'])
    scroll=after.get('shopDom',{}).get('scroll');old=visit['source'].get('scroll')
    return outcome(c,target,'return_to_shop_results',before,after,valid,
        'SOURCE_CHANGED: original list context was not restored; inspect state. No URL reconstruction.',
        sourceVisitId=visit['visitId'],contextRestored=valid,scrollRestored=bool(scroll and old and abs(scroll['y']-old['y'])<3),scrollBefore=old,scrollAfter=scroll)


def run(c,page,operation):
    from .shopping_research import read,publish,saved_record,click,deliver,clicked_target,wait_result,outcome
    if operation=='open_shop':return open_shop(c,page,c.args.get('controlId'))
    if operation=='return_to_shop_results':return return_to_shop(c,page)
    data=read(c,page)
    if operation=='list_shops':
        public=publish(c,data)
        return {'shops':[{'identity':r.get('shopIdentity'),'label':r['label'],'controlId':r['controlId']} for r in public['controls'] if r['action']=='open_shop'],
            'searchTarget':data['shopDom']['searchTarget'],'state':public,'coverage':'loaded actual entries only; names are not unique identities'}
    if data['pageType']!='shop':raise RuntimeError('WRONG_PAGE_TYPE: activate a verified shop page first.')
    if operation=='shop_state':return publish(c,data)
    if operation=='open_shop_product':
        row,_=saved_record(c,page,c.args.get('controlId'))
        if row.get('action')!='open_product':raise RuntimeError('UNSUPPORTED: choose an actual product card.')
        product_id=product_identity(row['href'])['productId'];card=next((p for p in data['products'] if p['productId']==product_id),None)
        if not card or card['region']=='recommendation':raise RuntimeError('UNSUPPORTED: cross-shop recommendation cannot be used as a shop result.')
        result=click(c,page)
        linked=[r.get('shopIdentity') for r in result['state']['controls'] if r.get('action')=='open_shop']
        verified=bool(linked) and all(same_shop(data['shopDom']['identity'],i) for i in linked)
        result['shopEvidence']={'sourceShop':data['shopDom']['identity'],'cardRegion':card['region'],'membership':card['shopMembership'],
            'detailShopVerified':verified,'note':'Visible shop-link/container evidence only, not independent merchant verification.'}
        return result
    action='shop_section' if operation=='open_shop_section' else 'shop_category'
    row,before=saved_record(c,page,c.args.get('controlId'))
    if row.get('action')!=action:raise RuntimeError('UNSUPPORTED: choose the matching discovered shop control.')
    deliver(c,page,before,row);target=clicked_target(c,page,True)
    after=wait_result(c,target,before)
    current=next((r for r in after['controls'] if r['action']==action and r['label']==row['label'] and r['selected']),None)
    # A disclosure can reveal real child categories without selecting a destination.
    opened=action=='shop_category' and any(r['signature']==row['signature'] and r.get('expanded')=='true' for r in after['controls'])
    reason=check_shop_transition(before,after)
    destination=bool(row.get('href') and target.url==row['href'] and target.url!=before['url'])
    return outcome(c,target,operation,before,after,not reason and bool(current or opened or destination),reason,clicks=1)
