"""Explicit browser-tab binding, with native visibility reported without spoofing."""
from urllib.parse import urlparse
import uuid
import json


WATCH = '''token=>{
  if(!window.__huoyanTabWatch){
    const watch={token,hiddenCount:0};
    document.addEventListener('visibilitychange',()=>{if(document.hidden)watch.hiddenCount++});
    window.__huoyanTabWatch=watch;
  }
  return {...window.__huoyanTabWatch,visibility:document.visibilityState};
}'''
STATUS = '''()=>({visibility:document.visibilityState,watch:window.__huoyanTabWatch?{...window.__huoyanTabWatch}:null})'''


def page_type(page):
    url=urlparse(page.url);host=url.hostname or ''
    if host in ('item.taobao.com','detail.tmall.com') and url.path=='/item.htm':return 'product'
    from .favorites import favorites_url
    if favorites_url(page.url):return 'favorites'
    if host in ('s.taobao.com','shopsearch.taobao.com'):return 'search'
    if host=='www.taobao.com' and url.path in ('/search','/search/','/search.htm'):return 'search'
    if host=='www.taobao.com' and url.path in ('/','/index.htm','/index.html'):return 'home'
    if host.endswith(('.taobao.com','.tmall.com')):
        from .huoyan_browser import dom_script
        if page.evaluate(dom_script('merchantChatDom.js'), {'mode':'chat'}).get('supported'):return 'merchant-chat'
        from .shop_research import probe
        if probe(page)['isShopPage']:return 'shop'
    return 'other'


class TabFocus:
    def __init__(self, controller):
        self.c=controller
        self.file=controller.out/'focus-state.json'
        self.pending=None
        self.sessions={}

    def close(self):
        self.pending=None
        for session in self.sessions.values():
            try:session.detach()
            except Exception:pass
        self.sessions={}

    def evaluate(self,page,script,arg=None):
        session=self.sessions.get(page)
        if session is None:
            session=page.context.new_cdp_session(page);self.sessions[page]=session
        frame=session.send('Page.getFrameTree')['frameTree']['frame']['id']
        context=session.send('Page.createIsolatedWorld',{'frameId':frame,'worldName':'HuoYanTabFocus'})['executionContextId']
        result=session.send('Runtime.evaluate',{'expression':f'({script})({json.dumps(arg)})','contextId':context,'returnByValue':True})
        if result.get('exceptionDetails'):raise RuntimeError('Unable to read native tab visibility; stopped.')
        return result['result'].get('value')

    def load(self):
        from .huoyan_browser import load_json
        data=load_json(self.file,{})
        return data if data.get('endpoint')==self.c.endpoint else {'endpoint':self.c.endpoint,'origins':{}}

    def save(self,data):
        from .huoyan_browser import atomic_json
        atomic_json(self.file,data)

    def window(self,page,restore=False):
        """CDP window state is not evidence of OS foreground focus or occlusion."""
        session=page.context.new_cdp_session(page)
        try:
            result=session.send('Browser.getWindowForTarget')
            state=result['bounds']['windowState']
            if restore and state=='minimized':
                session.send('Browser.setWindowBounds',{'windowId':result['windowId'],'bounds':{'windowState':'normal'}})
                result=session.send('Browser.getWindowBounds',{'windowId':result['windowId']})
                state=result['bounds']['windowState']
                if state=='minimized':raise RuntimeError('WINDOW_RESTORE_FAILED: Chrome window remains minimized.')
            return {'state':state,'foreground':'unverified','occlusion':'unverified'}
        finally:session.detach()

    def info(self):
        data=self.load();active=data.get('activeTabId')
        page=next((p for p in self.c.pages if self.c.tab_id(p)==active),None) if active else None
        state=self.evaluate(page,STATUS) if page else None
        background=data.get('background',False)
        valid=bool(state and state['watch'] and state['watch']['token']==data.get('watchToken') and
            (background or state['visibility']=='visible' and state['watch']['hiddenCount']==data.get('hiddenCount')))
        try:window=self.window(page) if page else None
        except Exception:window={'state':'unverified','foreground':'unverified','occlusion':'unverified'}
        return {'activeTabId':active,'boundTabId':active,'pageType':page_type(page) if page else None,'bindingValid':valid,
                'mode':'background' if background else 'visible','nativeVisibility':state['visibility'] if state else None,
                'window':window,'originTabId':data.get('origins',{}).get(active),
                'lastWindowRecovery':data.get('lastWindowRecovery'),
                'scope':'explicitly bound browser tab; OS foreground and occlusion unverified'}

    def prepare_action(self,page):
        """Native Playwright actionability needs rendering; restore before, never retry a click."""
        self.require(page)
        status=self.evaluate(page,STATUS)
        if status['visibility']=='visible':return
        before=self.window(page)
        self.window(page,restore=True)
        page.bring_to_front()
        page.wait_for_timeout(100)
        self.c.guard(page);self.require(page)
        after=self.evaluate(page,STATUS)
        data=self.load()
        data['lastWindowRecovery']={'tabId':self.c.tab_id(page),'beforeVisibility':status['visibility'],
            'beforeWindowState':before['state'],'afterVisibility':after['visibility'],
            'reason':'native interaction requires rendering; no click delivered before recovery'}
        self.save(data)
        if after['visibility']!='visible':
            raise RuntimeError('WINDOW_NOT_VISIBLE: restore/select did not make the bound tab visible; no native action delivered.')

    def bind(self,page,origin=None,bring=False,background=None):
        from .shopping_research import supported
        if not supported(page.url):raise RuntimeError('Cannot activate a tab outside supported shopping sites.')
        self.c.guard(page)
        data=self.load()
        if background is None:background=data.get('background',True)
        # Background reuse must not pull another application or tab to the front.
        bring=bring and not background
        if bring:page.bring_to_front()
        if not background and page.evaluate('document.visibilityState')!='visible':
            raise RuntimeError('FOCUS_CHANGED: destination tab is hidden; activate_shopping_tab explicitly.')
        state=self.evaluate(page,WATCH,uuid.uuid4().hex)
        data.update(activeTabId=self.c.tab_id(page),watchToken=state['token'],hiddenCount=state['hiddenCount'],background=background)
        if origin is not None and origin is not page:
            source=self.c.tab_id(origin)
            original=source if page_type(origin) in ('search','shop','home','favorites') else data.setdefault('origins',{}).get(source,source)
            data.setdefault('origins',{})
            data['origins'][data['activeTabId']]=original
        self.save(data);self.pending=None
        self.c.tab_budget.touch(page)
        return self.info()

    def activate(self,page,background=None,restore_window=False):
        self.pending=None
        if background is None:background=self.load().get('background',True)
        if restore_window or not background:
            self.window(page,restore=True)
            page.bring_to_front()
        return self.bind(page,background=background)

    def require(self,page):
        data=self.load();tab=self.c.tab_id(page)
        if data.get('activeTabId')!=tab:
            raise RuntimeError(f'NEEDS_TAB_SWITCH: call activate_shopping_tab for tabId={tab} before using this page.')
        status=self.evaluate(page,STATUS)
        background=data.get('background',False)
        if not background and status['visibility']!='visible':
            raise RuntimeError('FOCUS_CHANGED: bound tab is hidden; no background operation. Activate it explicitly.')
        watch=status['watch']
        if self.pending and self.pending['source']==tab and (watch is None or watch['token']!=data.get('watchToken') and page.url!=self.pending['url']):
            # A delivered click/back/reload may replace this document. A manual switch
            # within the same document is never forgiven by this branch.
            self.bind(page)
            return
        if not watch or watch['token']!=data.get('watchToken') or not background and watch['hiddenCount']!=data.get('hiddenCount'):
            raise RuntimeError('FOCUS_CHANGED: tab switched away or document changed; activate it again before continuing.')

    def begin(self,page):
        self.require(page)
        self.pending={'source':self.c.tab_id(page),'url':page.url,'pages':set(self.c.pages)}

    def adopt_popup(self,source,target):
        if not self.pending or self.pending['source']!=self.c.tab_id(source) or target in self.pending['pages']:
            raise RuntimeError('Untracked tab transition; activate_shopping_tab explicitly.')
        info=self.bind(target,origin=source)
        self.c.tab_budget.touch(target,managed=True)
        self.c.tab_budget.enforce(protect=[self.c.tab_id(source),self.c.tab_id(target)])
        return info

    def related_results(self):
        data=self.load();active=data.get('activeTabId')
        current=next((p for p in self.c.pages if self.c.tab_id(p)==active),None)
        if current is None:raise RuntimeError('Bound tab is closed; choose an existing tab explicitly.')
        self.require(current)
        if page_type(current)=='search':return current
        target=data.get('origins',{}).get(active)
        if target==active:
            expected=data.get('returnHistory',{}).get(active)
            session=current.context.new_cdp_session(current)
            try:history=session.send('Page.getNavigationHistory')
            finally:session.detach()
            index=history['currentIndex']
            if not expected or index<1 or history['entries'][index-1]['url']!=expected['url']:
                raise RuntimeError('Original result history changed; no automatic navigation.')
            self.begin(current);current.go_back(wait_until='commit',timeout=8000)
            current.wait_for_function("document.readyState==='interactive'||document.readyState==='complete'",timeout=8000)
            self.c.guard(current);self.require(current);self.pending=None
            if page_type(current) not in ('home','search','shop','favorites'):raise RuntimeError('History did not return to a result page.')
            return current
        page=next((p for p in self.c.pages if self.c.tab_id(p)==target),None)
        if page is None or page_type(page) not in ('search','shop','home','favorites'):
            raise RuntimeError('Original result tab is closed or changed; choose an existing result tab explicitly. No page reopened.')
        return page

    def remember_same_tab(self,page,url,kind):
        if kind not in ('home','search','shop','favorites'):return
        data=self.load();tab=self.c.tab_id(page)
        data.setdefault('origins',{})[tab]=tab
        data.setdefault('returnHistory',{})[tab]={'url':url,'pageType':kind}
        self.save(data)

    def check_wait(self,page):
        if not self.pending and self.load().get('activeTabId')==self.c.tab_id(page):self.require(page)

    def allow(self,page,action):
        kind=page_type(page)
        allowed={
            'search':{'home','search','shop'},'sort':{'search','shop'},'sort_direction':{'search','shop'},
            'filter_panel':{'search','shop'},'close_filter_panel':{'search','shop'},'filter_option':{'search','shop'},
            'apply_filters':{'search','shop'},'clear_filters':{'search','shop'},'price_panel':{'search','shop'},
            'next_page':{'search','shop'},'previous_page':{'search','shop'},'page_number':{'search','shop'},'page_jump':{'search','shop'},
            'section':{'product'},'gallery_image':{'product'},'select_sku':{'product'},
            'open_reviews':{'product'},'review_filter':{'product'},'review_menu':{'product'},
            'close_detail_panel':{'product'},'expand_question_answers':{'product'},'open_services':{'product'},
            'set_quantity':{'product'},'detail_scroll':{'product'},'image_step':{'product'},
            'open_product':{'home','search','shop','favorites'},'open_shop':{'product','home','search','shop'},'search_suggestion':{'home','search','shop'},
            'set_taobao_favorite':{'product'},
            'shop_section':{'shop'},'shop_category':{'shop'},'search_target':{'home','search'},'search_target_menu':{'home','search'},
            'home':{'home','search','shop','product'}
        }
        if action not in allowed or kind not in allowed[action]:
            raise RuntimeError(f'WRONG_PAGE_TYPE: {action} is not allowed on {kind}; switch to an appropriate tab first.')
