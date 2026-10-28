"""Detail research on discovered DOM controls; no network/URL or transaction fallback."""
import hashlib
import json
import base64
import uuid
from random import uniform
from urllib.parse import urlsplit,parse_qsl,urlencode

from .huoyan_browser import atomic_json, load_json, stamp

OPERATIONS={'detail_state','open_detail_section','read_product_parameters','open_reviews','read_reviews',
    'set_review_filter','open_review_menu','load_more_detail','close_detail_panel','view_product_image',
    'read_product_questions','expand_question_answers','read_delivery_services','set_quantity','open_product_shop','read_product_evidence','read_shop_reputation'}
TOOLS={'section':'open_detail_section','open_reviews':'open_reviews','review_filter':'set_review_filter',
    'review_menu':'open_review_menu','close_detail_panel':'close_detail_panel','gallery_image':'view_product_image',
    'image_step':'view_product_image','select_sku':'select_sku','expand_question_answers':'expand_question_answers',
    'open_services':'read_delivery_services','set_quantity':'set_quantity','shop_reputation':'read_shop_reputation'}


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]


def panel_key(product_id,panel):
    return digest([product_id,panel['kind'],panel['elementPath']])


def publish_detail(c,data,generation,records):
    from .shopping_research import revision
    d=data['detail'];product=data['product'];refs={};panel_refs={}
    def register(kind,row):
        ref=digest([generation,kind,row.get('signature') or row.get('elementPath'),row.get('region')])
        records[ref]={**row,'kind':kind,'productId':product['productId']};return ref
    for panel in d['panels']:
        raw={**panel,'panelType':panel['kind'],'signature':json.dumps([panel['kind'],panel['elementPath']]),'panelKey':panel_key(product['productId'],panel),'action':'close_detail_panel'}
        panel_refs[panel['panelId']]=register('detail-panel',raw)
    for row in d['controls']:refs[row['signature']]=register('detail',row)
    def clean(row):
        item={k:v for k,v in row.items() if k not in ('elementPath','signature','panelId')}
        item.update(controlId=refs[row['signature']],tool=TOOLS.get(row['action']))
        item['panelId']=panel_refs.get(row.get('panelId'))
        if row['action']=='section':item['sectionId']=item['controlId']
        if row['action'] in ('gallery_image','image_step'):item['imageId']=item['controlId']
        return item
    controls=[clean(r) for r in d['controls']]
    containers=[]
    for raw in d['containers']:
        ref=register('detail-container',{**raw,'signature':json.dumps([raw['elementPath'],raw['region']]),'action':'detail_scroll'})
        containers.append({k:v for k,v in raw.items() if k not in ('elementPath','containerId')}|{'containerId':ref})
    owned=load_json(c.out/'detail-panels.json',{})
    owned=owned.get('owned',{}) if owned.get('endpoint')==c.endpoint else {}
    panels=[{k:v for k,v in p.items() if k not in ('elementPath','dismissPath','panelId')}|{'panelId':panel_refs[p['panelId']],
        'openedByTool':panel_key(product['productId'],p) in owned} for p in d['panels']]
    groups=[];selection_index=0
    for g in d['skuGroups']:
        needs=len(g['options'])>1
        groups.append({'groupIndex':g['groupIndex'],'selectionIndex':selection_index if needs else None,
            'requiresSelection':needs,'label':g['label'],'options':[clean(r) for r in g['options']]})
        if needs:selection_index+=1
    def allowed(r):
        return not r['disabled'] and (r['action']!='close_detail_panel' or any(p['panelId']==r['panelId'] and p['openedByTool'] for p in panels))
    available=[{'tool':tool,'controlIds':[r['controlId'] for r in controls if r['tool']==tool and allowed(r)],
                'conditions':'Use current IDs; scroll if needsScroll; resolve blocking overlay first.'} for tool in sorted(set(TOOLS.values()))
               if any(r['tool']==tool and allowed(r) for r in controls)]
    owned_panels=[p['panelId'] for p in panels if p['openedByTool']]
    if owned_panels:available.append({'tool':'close_detail_panel','panelIds':owned_panels})
    available.extend([{'tool':tool,'scope':'loaded content only'} for tool,present in
        [('read_product_parameters',bool(d['parameterText'])),('read_reviews',bool(d['reviews'])),
         ('read_product_questions',bool(d['questions'])),('read_delivery_services',bool(d['services'] or d['delivery']))] if present])
    shop_controls=[{'controlId':ref,'label':r['label']} for ref,r in records.items() if r.get('kind')=='controls' and r.get('action')=='open_shop' and not r.get('disabled')]
    if shop_controls:available.append({'tool':'open_product_shop','controlIds':[r['controlId'] for r in shop_controls]})
    available.append({'tool':'read_selected_offer','scope':'visible current-SKU offer; unverified fields remain null'})
    available.append({'tool':'save_local_favorite','scope':'local bookmark and historical SKU summary; does not modify Taobao favorites'})
    available.append({'tool':'favorite_options','scope':'discover actual Taobao favorite toggle and account favorites entry; dedicated controls only'})
    available.append({'tool':'read_product_evidence','scope':'loaded shop score/level, trade metrics, parameters, descriptions and image inventory; optional visible level-icon image'})
    if groups and all(any(o['selected'] and not o['disabled'] for o in g['options']) for g in groups):
        available.append({'tool':'save_candidate','scope':'local exact-SKU evidence'})
    if d['images'] and groups:available.append({'tool':'select_sku_and_collage','imageSources':sorted({r['region'] for r in d['images']}),'scope':'rendered images; SKU association unverified'})
    if d['images'] or groups:available.append({'tool':'product_image_overview','imageSources':['sku','gallery','description'],'scope':'numbered preview from already loaded image resources; no SKU changes'})
    if c.focus.info().get('originTabId'):available.append({'tool':'return_to_results','scope':'verified original results tab/history only'})
    return {'productId':product['productId'],'title':product['title'],'selectedSku':product['selectedSku'],
        'source':'live-page','stateVersion':revision(data),'observedAt':stamp(),'skuGroups':groups,
        'controls':controls,'sections':[r for r in controls if r['action']=='section'],
        'images':[clean(r) for r in d['images']],'panels':panels,'containers':containers,
        'parameters':d['parameters'],'parameterText':d['parameterText'],'reviews':d['reviews'],'reviewSort':d.get('reviewSort',[]),'questions':d['questions'],
        'services':d['services'],'delivery':d['delivery'],'descriptions':d['descriptions'],
        'commerce':d.get('commerce'),
        'availableActions':available,'unverified':d['unverified'],'iframeCount':d['iframeCount'],
        'shopControls':shop_controls,
        'nextAction':'Choose only among discovered options. No SKU or content panel was changed by this read.',
        'skuSelectionOrder':'Pass one exact option text per requiresSelection group, in selectionIndex order; single-option groups are reported separately.',
        'coverage':'Loaded DOM only; rendered is not necessarily in viewport or actionable. Unloaded capabilities are unknown.'}


def validate_record(data,record):
    d=data.get('detail')
    if not d:raise RuntimeError('WRONG_PAGE_TYPE: detail control requires product page.')
    if record.get('productId') and record['productId']!=data['product']['productId']:
        raise RuntimeError('PRODUCT_CHANGED: detail control belongs to another product.')
    kind=record['kind']
    if kind=='detail':
        found=any(r['signature']==record['signature'] for r in d['controls'])
    elif kind=='detail-panel':
        found=any(r['kind']==record.get('panelType') and r['elementPath']==record['elementPath'] for r in d['panels'])
    else:
        found=any(r['elementPath']==record['elementPath'] and r['region']==record['region'] for r in d['containers'])
    if not found:raise RuntimeError('STALE_CONTROL: detail target changed; read detail_state again.')


def own_panels(c,before,after):
    old={panel_key(before['product']['productId'],p) for p in before['detail']['panels']}
    file=c.out/'detail-panels.json';saved=load_json(file,{})
    if saved.get('endpoint')!=c.endpoint:saved={'endpoint':c.endpoint,'owned':{}}
    now={panel_key(after['product']['productId'],p) for p in after['detail']['panels']}
    for key in old-now:
        if saved['owned'].get(key,{}).get('tabId')==after['tabId']:saved['owned'].pop(key,None)
    for p in after['detail']['panels']:
        key=panel_key(after['product']['productId'],p)
        if key not in old:saved['owned'][key]={'tabId':after['tabId'],'kind':p['kind'],'observedAt':stamp()}
    atomic_json(file,saved)


def require_owned(c,page,before,panel_id):
    p=next((p for p in before['detail']['panels'] if p['panelId']==panel_id),None)
    saved=load_json(c.out/'detail-panels.json',{})
    key=panel_key(before['product']['productId'],p) if p else None
    owner=saved.get('owned',{}).get(key,{}) if saved.get('endpoint')==c.endpoint else {}
    if not p or owner.get('tabId')!=c.tab_id(page):raise RuntimeError('UNOWNED_PANEL: only a research panel opened by this tool may be closed.')
    return p


def click_control(c,page,record,before):
    from .shopping_research import deliver, read, wait_result, outcome, changed
    action=record['action']
    if record['kind']!='detail' or action in ('set_quantity','select_sku','shop_reputation'):
        raise ValueError('Use the corresponding semantic tool, not generic clicking, for this control.')
    if action=='close_detail_panel':require_owned(c,page,before,record['panelId'])
    before_sku=before['product']['selectedSku'];product=before['product']['productId']
    delivered=deliver(c,page,before,record)
    c.focus.pending=None
    predicate=None
    if action=='open_reviews':predicate=lambda x:any(p['kind']=='reviews' for p in x['detail']['panels'])
    elif action=='open_services':predicate=lambda x:any(p['kind']=='services' for p in x['detail']['panels'])
    elif action=='close_detail_panel':predicate=lambda x:not any(p['panelId']==record['panelId'] and p['elementPath']==next((p['elementPath'] for p in before['detail']['panels'] if p['panelId']==record['panelId']),None) for p in x['detail']['panels'])
    elif action in ('section','review_filter'):predicate=lambda x:is_selected(x,record)
    after=wait_result(c,page,before,predicate)
    if after['product']['productId']!=product or after['product']['selectedSku']!=before_sku:
        raise RuntimeError('PRODUCT_CHANGED: research action changed product/SKU; inspect current state.')
    own_panels(c,before,after)
    if predicate:confirmed=predicate(after)
    elif action=='gallery_image':
        confirmed=before['currentImages']!=after['currentImages'] or len(after['detail']['panels'])>len(before['detail']['panels']) or any(r['signature']==record['signature'] and r['selected'] for r in after['detail']['controls'])
    elif action=='expand_question_answers':
        confirmed=after['detail']['questions']!=before['detail']['questions'] or any(p['kind']=='questions' for p in after['detail']['panels'] if p not in before['detail']['panels'])
    else:confirmed=changed(before,after)
    return outcome(c,page,action,before,after,confirmed,clicks=1 if delivered else 0,
        evidence={'controlLabel':record['label'],'region':record['region'],'scope':'observable UI only'})


def result_read(c,data,**values):
    from .shopping_research import publish
    return {**values,'observedAt':stamp(),'coverage':'currently loaded DOM only; not all reviews/questions',
            'state':publish(c,data)}


def is_selected(data,record):
    return any(r['signature']==record['signature'] and r['selected'] for r in data['detail']['controls']) or (
        record.get('action')=='review_filter' and record.get('group')=='sort' and
        any(r['label']==record['label'] for r in data['detail'].get('reviewSort',[])))


def run(c,page,operation):
    from .shopping_research import read,publish,saved_record,outcome,native_locator,wait_result
    c.focus.allow(page,'section');before=read(c,page);d=before['detail']
    if operation in ('read_reviews','read_product_questions'):
        limit=c.args.get('limit',20)
        if not isinstance(limit,int) or isinstance(limit,bool) or not 1<=limit<=100:raise ValueError('limit must be 1..100.')
    if operation=='detail_state':return publish(c,before)
    if operation=='read_shop_reputation':
        shop=before['product']['commerce']['shop']
        if not c.args.get('controlId'):
            return result_read(c,before,shop=shop,interaction='none',note='Read only. To reveal an unopened shop card, pass its current read_shop_reputation controlId for native hover.')
        record,current=saved_record(c,page,c.args['controlId'])
        if record['kind']!='detail' or record.get('action')!='shop_reputation':raise ValueError('Choose a current shop-reputation hover control, not a shop/contact link.')
        if record.get('disabled'):raise RuntimeError('UNSUPPORTED: shop-reputation trigger is disabled.')
        if shop['reputation']['panelCount']==1 and shop['reputation']['panelInViewport']:
            return outcome(c,page,operation,before,before,True,alreadySatisfied=True,shop=shop,interaction='none')
        c.pause(page);c.guard(page);c.focus.require(page)
        current=read(c,page);validate_record(current,record)
        if any(current['product'][k]!=before['product'][k] for k in ('productId','selectedSku')):raise RuntimeError('PRODUCT_CHANGED: product/SKU changed before shop-card hover.')
        loc=native_locator(page,current,record);loc.scroll_into_view_if_needed();c.guard(page);c.focus.require(page)
        current=read(c,page);validate_record(current,record)
        if any(current['product'][k]!=before['product'][k] for k in ('productId','selectedSku')):raise RuntimeError('PRODUCT_CHANGED: product/SKU changed while locating shop-card hover.')
        loc.hover(timeout=2500)
        after=wait_result(c,page,before,lambda x:x['product']['commerce']['shop']['reputation']['panelCount']==1 and x['product']['commerce']['shop']['reputation']['panelInViewport'])
        if any(after['product'][k]!=before['product'][k] for k in ('productId','selectedSku')):raise RuntimeError('PRODUCT_CHANGED: product/SKU changed during shop-card hover.')
        shop=after['product']['commerce']['shop'];visible=shop['reputation']['panelCount']==1 and shop['reputation']['panelInViewport']
        return outcome(c,page,operation,before,after,visible,shop=shop,interaction='native-hover',clicks=0,
            evidence={'scope':'visible shop-card DOM text only; rating is not credit level','ratingRows':len(shop['reputation']['rows'])})
    if operation=='read_product_evidence':
        image=None;image_file=None;capture_status='not-requested'
        if c.args.get('includeLevelImage',True):
            capture_status='not-observed-or-not-visible'
            locs=page.locator('img[data-shop-level],[data-shop-level] img,img[class*="creditLevelIconImg--"]').all()
            candidates=[]
            for loc in locs:
                if loc.evaluate('''e=>{const r=e.getBoundingClientRect();const h=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);return e.complete&&e.naturalWidth>0&&r.width>0&&r.height>0&&r.width<=500&&r.height<=300&&r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight&&(h===e||e.contains(h))}'''):candidates.append(loc)
            if len(candidates)==1:
                c.focus.prepare_action(page)
                c.guard(page);c.focus.require(page)
                image=candidates[0].screenshot(timeout=3000)
                c.focus.require(page);now=read(c,page)
                if now['product']['productId']!=before['product']['productId'] or now['product']['selectedSku']!=before['product']['selectedSku']:raise RuntimeError('PRODUCT_CHANGED: evidence context changed during image capture.')
                before=now;d=now['detail'];capture_status='captured-visible-level-icon'
                image_file=c.out/'images'/'evidence'/f"{before['product']['productId']}-{uuid.uuid4().hex}.png"
                image_file.parent.mkdir(parents=True,exist_ok=True);image_file.write_bytes(image)
            elif len(candidates)>1:capture_status='ambiguous-level-icons'
        result=result_read(c,before,commerce=d.get('commerce'),parameters=d['parameters'],parameterText=d['parameterText'],
            descriptions=d['descriptions'],images=[{k:v for k,v in r.items() if k not in ('elementPath','signature','panelId')} for r in d['images']],
            selectedSku=before['product']['selectedSku'],levelImage={'status':capture_status,'file':str(image_file) if image_file else None,'interpretation':'Image evidence only; no inferred grade from asset URL.'},
            coverage='Already loaded content only. Open the real parameters/description section and scroll its container to expose more. No automatic section/SKU changes.')
        if image:result['levelImageBase64']=base64.b64encode(image).decode('ascii')
        return result
    if operation=='read_product_parameters':
        return result_read(c,before,parameters=d['parameters'],rawText=d['parameterText'],scope='product-general; selected-SKU association unverified')
    if operation=='read_reviews':return result_read(c,before,reviews=d['reviews'][:c.args.get('limit',20)],panelOpen=any(p['kind']=='reviews' for p in d['panels']))
    if operation=='read_product_questions':return result_read(c,before,questions=d['questions'][:c.args.get('limit',20)])
    if operation=='read_delivery_services' and not c.args.get('controlId'):
        return result_read(c,before,delivery=d['delivery'],services=d['services'],fulfillment=d.get('commerce',{}).get('fulfillment'),shipping=None,finalPrice=None,destination='redacted')
    if operation=='read_delivery_services' and any(p['kind']=='services' for p in d['panels']):
        return outcome(c,page,operation,before,before,True,alreadySatisfied=True,delivery=d['delivery'],services=d['services'],fulfillment=d.get('commerce',{}).get('fulfillment'),shipping=None,finalPrice=None)
    if operation=='load_more_detail':
        ref=c.args.get('containerId');record,current=saved_record(c,page,ref)
        if record['kind']!='detail-container':raise ValueError('Choose a current detail containerId.')
        steps=c.args.get('maxSteps',1)
        if not isinstance(steps,int) or isinstance(steps,bool) or not 1<=steps<=5:raise ValueError('maxSteps must be 1..5.')
        changes=0;reason=None;after=before
        def metrics():
            if record['elementPath'] is None:return page.evaluate('({top:scrollY,height:document.documentElement.scrollHeight,viewport:innerHeight})')
            return page.locator(record['elementPath']).evaluate('e=>({top:e.scrollTop,height:e.scrollHeight,viewport:e.clientHeight})')
        for _ in range(steps):
            c.focus.require(page);c.guard(page);validate_record(read(c,page),record);m=metrics()
            if m['top']+m['viewport']>=m['height']-2:reason='AT_BOTTOM';break
            if record['elementPath'] is None and d['panels']:raise RuntimeError('BLOCKED_BY_PANEL: choose the active panel scroll container.')
            c.pause(page);c.focus.require(page)
            if record['elementPath'] is None:page.mouse.move(page.viewport_size['width']//2 if page.viewport_size else 300,250)
            else:
                loc=page.locator(record['elementPath']);loc.scroll_into_view_if_needed();loc.hover(timeout=1500)
            c.focus.require(page);page.mouse.wheel(0,round(m['viewport']*uniform(.5,2.5)))
            page.wait_for_timeout(350);c.focus.require(page);after=wait_result(c,page,current)
            moved=metrics()['top']!=m['top']
            content_changed=any(after['detail'][k]!=current['detail'][k] for k in ('reviews','questions','descriptions'))
            if content_changed:changes+=1
            if not moved:reason='NO_MOVEMENT';break
            if not content_changed:reason='NO_NEW_CONTENT';break
            current=after
        at_bottom=metrics()['top']+metrics()['viewport']>=metrics()['height']-2
        if at_bottom and metrics()['top']>2:
            c.focus.require(page);page.mouse.wheel(0,-round(metrics()['viewport']*uniform(.2,.5)))
        return outcome(c,page,operation,before,read(c,page),bool(changes) or at_bottom,stopReason=reason or ('AT_BOTTOM' if at_bottom else 'STEP_LIMIT'),newContentSteps=changes,atBottom=at_bottom)
    if operation=='set_review_filter':
        options=c.args.get('options',[])
        if not options or len(options)>10:raise ValueError('Provide 1..10 current review options with desired selected booleans.')
        resolved=[]
        for option in options:
            r,_=saved_record(c,page,option['controlId'])
            if r['kind']!='detail' or r['action']!='review_filter':raise ValueError('Not a discovered review filter.')
            if not isinstance(option.get('selected'),bool):raise ValueError('selected must be boolean.')
            resolved.append((r,option['selected']))
        current=before
        for r,desired in resolved:
            row=next((x for x in current['detail']['controls'] if x['signature']==r['signature']),None)
            if not row:return outcome(c,page,operation,before,current,False,'Dependent review controls changed; inspect partial selection.')
            if row['selected']!=desired:
                if desired is False:raise ValueError('Choose an explicit alternative; radio/filter deselection is not inferred.')
                click_control(c,page,{'kind':'detail',**row},current)
                current=read(c,page)
        confirmed=all(is_selected(current,r)==desired for r,desired in resolved)
        return outcome(c,page,operation,before,current,confirmed,evidence={'scope':'visible review-filter selection, not server completeness'})
    if operation=='open_product_shop':
        from .shop_research import open_shop
        result=open_shop(c,page,c.args.get('controlId'));result['action']=operation
        return result
    if operation=='close_detail_panel':
        panel,now=saved_record(c,page,c.args.get('panelId'))
        if panel['kind']!='detail-panel':raise ValueError('Choose a current panelId.')
        require_owned(c,page,now,panel['panelId'])
        if panel.get('dismissal')=='trigger-toggle':
            rows=[r for r in now['detail']['controls'] if r['elementPath']==panel.get('dismissPath') and r['action']=='open_services']
            if len(rows)!=1:raise RuntimeError('STALE_CONTROL: service dismissal trigger changed.')
            from .shopping_research import deliver
            deliver(c,page,now,{'kind':'detail',**rows[0]});c.focus.pending=None
            after=wait_result(c,page,now,lambda x:not any(p['elementPath']==panel['elementPath'] for p in x['detail']['panels']))
            own_panels(c,now,after)
            confirmed=not any(p['elementPath']==panel['elementPath'] for p in after['detail']['panels'])
            return outcome(c,page,operation,now,after,confirmed,evidence={'interaction':'native trigger click','scope':'known service explanation'})
        rows=[r for r in now['detail']['controls'] if r['action']=='close_detail_panel' and r['panelId']==panel['panelId']]
        if len(rows)!=1:raise RuntimeError('UNSUPPORTED: no unique safe close control for this panel.')
        return click_control(c,page,{'kind':'detail',**rows[0]},now)
    if operation=='set_quantity':
        q=c.args.get('quantity')
        if not isinstance(q,int) or isinstance(q,bool) or not 1<=q<=1000:raise ValueError('quantity must be an integer in 1..1000.')
        rows=[r for r in d['controls'] if r['action']=='set_quantity' and not r['disabled']]
        if len(rows)!=1:raise RuntimeError('UNSUPPORTED: no unique enabled quantity input.')
        row=rows[0]
        for attr,ok in [('min',lambda x:q>=x),('max',lambda x:q<=x)]:
            if row.get(attr):
                try:bound=float(row[attr])
                except ValueError:continue
                if not ok(bound):raise ValueError('Quantity outside visible input limits.')
        c.pause(page);c.focus.require(page);c.guard(page)
        from .shopping_research import revision
        if revision(read(c,page))!=revision(before):raise RuntimeError('STALE_CONTROL: quantity state changed.')
        from .shopping_research import detail_actionable
        loc=native_locator(page,before,{'kind':'detail',**row});detail_actionable(c,page,loc)
        c.focus.require(page);loc.fill(str(q));c.focus.require(page);loc.press('Tab')
        after=wait_result(c,page,before,lambda x:any(r['action']=='set_quantity' and r.get('value')==str(q) for r in x['detail']['controls']))
        confirmed=(after['product']['productId']==before['product']['productId'] and after['product']['selectedSku']==before['product']['selectedSku'] and
            any(r['action']=='set_quantity' and r.get('value')==str(q) for r in after['detail']['controls']))
        return outcome(c,page,operation,before,after,confirmed,quantity=q,priceImpact='unverified',evidence={'scope':'quantity input only; no cart/checkout'})
    ref=c.args.get('sectionId') if operation=='open_detail_section' else c.args.get('imageId') if operation=='view_product_image' else c.args.get('controlId')
    if operation=='expand_question_answers' and not ref:
        rows=[r for r in d['controls'] if r['action']=='expand_question_answers' and r.get('questionId')==c.args.get('questionId') and r.get('questionId')]
        if len(rows)!=1:raise RuntimeError('UNSUPPORTED: question has no uniquely associated answer control; inspect detail_state.')
        record={'kind':'detail',**rows[0]}
    elif operation=='open_reviews' and not ref:
        rows=[r for r in d['controls'] if r['action']=='open_reviews' and not r['disabled']]
        if any(p['kind']=='reviews' for p in d['panels']):return outcome(c,page,operation,before,before,True,alreadySatisfied=True)
        if len(rows)!=1:raise RuntimeError('UNSUPPORTED: no unique actual all-reviews button.')
        record={'kind':'detail',**rows[0]}
    else:record,before=saved_record(c,page,ref)
    expected={'open_detail_section':{'section'},'open_reviews':{'open_reviews'},'view_product_image':{'gallery_image','image_step'},
        'expand_question_answers':{'expand_question_answers'},'read_delivery_services':{'open_services'},'open_review_menu':{'review_menu'}}
    if record['kind']!='detail' or record.get('action') not in expected.get(operation,set()):raise ValueError('Control does not match this semantic operation.')
    if operation=='read_delivery_services' and c.args.get('interaction','click')=='hover':
        c.pause(page);c.focus.require(page);c.guard(page);current=read(c,page);validate_record(current,record)
        if any(current['product'][k]!=before['product'][k] for k in ('productId','selectedSku')):raise RuntimeError('PRODUCT_CHANGED: product/SKU changed before service hover.')
        loc=native_locator(page,before,record);loc.scroll_into_view_if_needed();c.focus.require(page);loc.hover(timeout=2000)
        after=wait_result(c,page,before,lambda x:any(p['kind']=='services' for p in x['detail']['panels']))
        own_panels(c,before,after)
        return outcome(c,page,operation,before,after,any(p['kind']=='services' for p in after['detail']['panels']),
            delivery=after['detail']['delivery'],services=after['detail']['services'],shipping=None,finalPrice=None,
            evidence={'interaction':'native hover','scope':'visible service explanation, eligibility unverified'})
    if operation=='open_detail_section' and record['selected']:return outcome(c,page,operation,before,before,True,alreadySatisfied=True)
    if operation=='open_review_menu':
        interaction=c.args.get('interaction','click')
        if interaction not in ('click','hover'):raise ValueError('interaction must be click or hover.')
        if interaction=='click':
            from .shopping_research import deliver
            deliver(c,page,before,record);c.focus.pending=None
            after=wait_result(c,page,before)
            confirmed=any(r['action']=='review_filter' and r['signature'] not in {x['signature'] for x in before['detail']['controls']} for r in after['detail']['controls'])
            return outcome(c,page,operation,before,after,confirmed,evidence={'interaction':'native click','scope':'new visible menu choices'})
        c.focus.require(page);c.pause(page);c.focus.require(page);c.guard(page)
        current=read(c,page);validate_record(current,record)
        if any(current['product'][k]!=before['product'][k] for k in ('productId','selectedSku')):raise RuntimeError('PRODUCT_CHANGED: product/SKU changed before menu hover.')
        loc=native_locator(page,before,record);loc.scroll_into_view_if_needed();loc.hover(timeout=2000)
        after=wait_result(c,page,before)
        confirmed=any(r['action']=='review_filter' and r['signature'] not in {x['signature'] for x in before['detail']['controls']} for r in after['detail']['controls'])
        return outcome(c,page,operation,before,after,confirmed,evidence={'interaction':'native hover','scope':'new visible menu choices'})
    result=click_control(c,page,record,before)
    if operation=='read_delivery_services':
        detail=result['state']['detail']
        result.update(delivery=detail['delivery'],services=detail['services'],fulfillment=detail.get('commerce',{}).get('fulfillment'),shipping=None,finalPrice=None)
    return result
