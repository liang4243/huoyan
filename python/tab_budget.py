"""Bounded product-tab retention. Never evict unknown/user tabs or navigate for cleanup."""
import time

from .huoyan_browser import atomic_json,load_json,product_identity,dom_script,stamp


class TabBudget:
    def __init__(self,c):
        self.c=c
        self.file=c.out/'tab-budget.json'
        self.last_report=None
        self.closed_this_call=[]

    def load(self):
        data=load_json(self.file,{'maxTabs':10})
        if data.get('endpoint')!=self.c.endpoint:
            data={'maxTabs':data.get('maxTabs',10),'endpoint':self.c.endpoint,'tabs':{}}
        data.setdefault('tabs',{})
        return data

    def touch(self,page,managed=False):
        data=self.load();tab=self.c.tab_id(page)
        try:key=product_identity(page.url)['key']
        except ValueError:key=None
        old=data['tabs'].get(tab,{})
        owned=bool(managed or old.get('managed') and old.get('productKey')==key)
        data['tabs'][tab]={'productKey':key,'managed':owned,'lastUsed':time.time_ns()}
        # Drop closed tab metadata. Product snapshots live in a separate registry.
        ids={self.c.tab_id(p) for p in self.c.pages}
        data['tabs']={k:v for k,v in data['tabs'].items() if k in ids}
        atomic_json(self.file,data)

    def configure(self,limit):
        if not isinstance(limit,int) or isinstance(limit,bool) or not 2<=limit<=50:
            raise ValueError('maxTabs must be an integer in 2..50.')
        data=self.load();data['maxTabs']=limit;atomic_json(self.file,data)
        return self.enforce()

    def status(self):
        data=self.load();count=len(self.c.pages)
        return {'maxTabs':data['maxTabs'],'openTabs':count,'scope':'all tabs in connected dedicated Chrome',
            'overLimit':count>data['maxTabs'],'closedTabs':[], 'lastCleanup':data.get('lastCleanup'),
            'note':'Only tool-opened product tabs may be evicted; current/source/manual/non-product tabs are protected. Read-only status.'}

    def enforce(self,reserve=0,protect=()):
        data=self.load();limit=data['maxTabs'];target=limit-reserve
        pages=list(self.c.pages);before=len(pages);closed=[];skipped=[]
        focus=self.c.focus.load();protected=set(protect)
        active=focus.get('activeTabId')
        if active:protected.add(active)
        from .merchant_chat import protected_tabs
        protected.update(protected_tabs(self.c))
        from .favorites import protected_tabs as favorite_protection
        protected.update(favorite_protection(self.c))
        # Keep every recorded return source, including old shop/list associations.
        protected.update(focus.get('origins',{}).values())
        candidates=[]
        for page in pages:
            tab=self.c.tab_id(page);record=data['tabs'].get(tab,{})
            if tab in protected or not record.get('managed'):continue
            try:key=product_identity(page.url)['key']
            except ValueError:continue
            if key!=record.get('productKey'):continue
            candidates.append((record.get('lastUsed',0),tab,page,key))
        for _,tab,page,key in sorted(candidates,key=lambda r:(r[0],r[1])):
            if len(self.c.pages)<=target:break
            try:
                self.c.guard(page)
                busy=page.evaluate('''()=>({focused:document.hasFocus(),
                  editing:[...document.querySelectorAll('input,textarea,[contenteditable=true]')].some(e=>
                    e.isContentEditable||e.type==='password'||!['q','keyword','keywords','quantity'].includes(e.name)&&
                    !['hidden','submit','button','checkbox','radio'].includes(e.type)&&e.value!==e.defaultValue),
                  media:[...document.querySelectorAll('video,audio')].some(e=>!e.paused),
                  unload:typeof window.onbeforeunload==='function',
                  panel:[...document.querySelectorAll('[role=dialog],[data-detail-panel],[class*="Drawer--"],[class*="drawer--"]')].some(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&getComputedStyle(e).visibility!=='hidden'})})''')
                if any(busy.values()):skipped.append({'tabId':tab,'reason':'focused, editing, media, unload handler or open panel'});continue
                url=page.url
                snapshot=page.evaluate(dom_script('productSnapshotDom.js'))
                commerce=page.evaluate(dom_script('commerceEvidenceDom.js'),{'mode':'detail'})
                if page.url!=url or product_identity(page.url)['key']!=key:
                    skipped.append({'tabId':tab,'reason':'product changed while caching'});continue
                self.c.guard(page)
                final_snapshot=page.evaluate(dom_script('productSnapshotDom.js'))
                if page.url!=url or final_snapshot.get('selectedSku')!=snapshot.get('selectedSku') or page.evaluate('document.hasFocus()'):
                    skipped.append({'tabId':tab,'reason':'page focus or SKU changed while caching'});continue
                current=self.c.focus.load()
                if tab==current.get('activeTabId') or tab in current.get('origins',{}).values():continue
                if tab in protected_tabs(self.c) or tab in favorite_protection(self.c):continue
                cache={**snapshot,'commerce':commerce,'productId':product_identity(url)['productId'],'productKey':key,
                    'url':url,'tabId':tab,'observedAt':stamp(),'note':'Cached loaded DOM before tab eviction; stale, no executable control IDs.'}
                # Merge latest disk state so unrelated cache entries survive.
                registry=load_json(self.c.registry_file,{'version':1,'tabs':{},'products':{}})
                registry['products'].setdefault(key,product_identity(url)).update(cache=cache,url=url)
                atomic_json(self.c.registry_file,registry)
                self.c.registry=registry
                # Default run_before_unload=False does not display/accept prompts.
                page.close(run_before_unload=False)
                if not page.is_closed():skipped.append({'tabId':tab,'reason':'close not confirmed'});continue
                closed.append({'tabId':tab,'productKey':key,'cached':True,'reason':'least recently used tool-opened product'})
                self.closed_this_call.append(closed[-1])
                data['tabs'].pop(tab,None)
                session=self.c.focus.sessions.pop(page,None)
                if session:
                    try:session.detach()
                    except Exception:pass
            except Exception:
                skipped.append({'tabId':tab,'reason':'cache/guard/close failed; cleanup stopped'})
                # Verification or unknown state must not cause further site operations.
                break
        ids={self.c.tab_id(p) for p in self.c.pages}
        data['tabs']={k:v for k,v in data['tabs'].items() if k in ids}
        if closed:
            self.c.registry=load_json(self.c.registry_file,{'version':1,'tabs':{},'products':{}})
            self.c.sync_tabs()
            for name in ('shopping-controls.json','favorite-controls.json'):
                file=self.c.out/name;controls=load_json(file,{})
                if controls.get('endpoint')==self.c.endpoint:
                    controls['tabs']={k:v for k,v in controls.get('tabs',{}).items() if k in ids};atomic_json(file,controls)
            current=self.c.focus.load()
            for field in ('origins','returnHistory'):
                current[field]={k:v for k,v in current.get(field,{}).items() if k in ids}
            self.c.focus.save(current)
        count=len(self.c.pages)
        report={'maxTabs':limit,'openTabsBefore':before,'openTabs':count,'reservedSlots':reserve,
            'targetTabs':target,'closedTabs':closed,'skippedTabs':skipped,'blocked':count>target,
            'scope':'all tabs in connected dedicated Chrome','note':'No cache/closed URL is reopened. Protected tabs may prevent reaching the limit.'}
        self.last_report=report
        data['lastCleanup']=report;atomic_json(self.file,data)
        return report

    def before_popup(self,page,locator):
        # Only reserve for an actual observed new-tab link, never for reuse/same-tab reads.
        target=locator.get_attribute('formtarget') or locator.get_attribute('target')
        if not target:
            target=locator.evaluate("e=>e.closest('form')?.target||document.querySelector('base[target]')?.target||''")
        if target.lower()!='_blank':return
        report=self.enforce(reserve=1,protect=[self.c.tab_id(page)])
        if report['blocked']:
            raise RuntimeError('TAB_LIMIT_REACHED: protected tabs fill the budget; no new-tab click delivered. Reuse an existing product tab or close an unneeded tab explicitly.')
