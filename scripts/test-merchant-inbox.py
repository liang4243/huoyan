"""Isolated, headed Chrome; every request is fulfilled by local WangWang fixtures."""
import copy
import importlib.util
import json
import sys
import unittest
from unittest.mock import patch
from playwright.sync_api import Locator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('chat_fixture_harness', ROOT/'scripts/test-merchant-chat.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
from python.merchant_chat import Store
from python.merchant_inbox import thread_signature, filter_matches

URL = 'https://market.m.taobao.com/app/im/chat-core/index.html'
WW = '''<!doctype html><meta charset=utf-8><style>
.ww_conversation{width:300px}.ww_conversation_list{height:160px;overflow:auto}
.conversation-item{height:42px;display:flex}.conversation .name{min-width:120px;cursor:pointer}
.ww_box{min-height:240px}.message-list{min-height:90px}.ww_input .edit{min-height:45px}
</style><div class=ww_conversation><span class=ww_search><input placeholder="搜索最近联系人"></span>
<div class=ww_conversation_list></div></div>
<div class=ww_header><div class=conversation-header><div class=name>测试店</div></div></div>
<div class=ww_box><div class=ww_message><div class=message-list></div></div><div class=ww_input>
<pre class=edit contenteditable=true></pre><button class=send-btn onclick="sendFixture()">发送</button></div></div>
<script>
window.shops=[{id:'private-account-a',name:'测试店',msg:'A店回复',unread:0},
 {id:'private-account-b',name:'第二店旗舰店',msg:'B店答复',unread:3},
 {id:'private-account-c',name:'第三店',msg:'C店回复',unread:0}];
window.selected=shops[0].id;window.q='';window.switchCount=0;window.sendCount=0;window.deleted=0;window.searchEnters=0;
window.stopSwitch=false;window.keepOldMessages=false;window.noFilter=false;
function bubble(text,self=false){const d=document.createElement('div');d.className='message-item-line';
 d.innerHTML='<div class="message-item '+(self?'self':'')+'"><div class="item"><div class="first-line"><span class="nick"></span><span class="time">12:00</span></div><div class="content"><div class="expression-parser"><pre class="edit" contenteditable="false"></pre></div></div></div></div>';
 d.querySelector('.nick').innerText=document.querySelector('.ww_header .name').innerText;d.querySelector('pre').innerText=text;
 document.querySelector('.message-list').append(d)}
function messages(){document.querySelector('.message-list').innerHTML='';bubble(shops.find(x=>x.id===selected).msg)}
function rows(){const l=document.querySelector('.ww_conversation_list');l.innerHTML='';
 for(const s of shops.filter(s=>noFilter||s.name.toLowerCase().includes(q.toLowerCase()))){const e=document.createElement('div');e.id=s.id;e.className='conversation-item'+(selected===s.id?' active':'');
 e.innerHTML='<button class="content-close">×</button><div class="content"><div class="conversation"><div class="name"></div><div class="time">12:00</div></div><div class="conversation-secondary-line"><div class="desc"></div></div></div>';
 e.querySelector('.name').innerText=s.name;e.querySelector('.desc').innerText=s.msg;
 if(s.unread){const b=document.createElement('div');b.className='unread-badge';b.innerText=String(s.unread);e.append(b)}
 e.querySelector('.content-close').onclick=ev=>{deleted++;ev.stopPropagation()};
 e.onclick=()=>{switchCount++;if(stopSwitch)return;selected=s.id;document.querySelector('.ww_header .name').innerText=s.name;rows();if(!keepOldMessages)messages()};l.append(e)}
 if(!l.children.length)l.innerText='暂无搜索结果';}
document.querySelector('.ww_search input').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();searchEnters++;q=e.target.value;rows()}};
function sendFixture(){sendCount++;const f=document.querySelector('.ww_input .edit');bubble(f.innerText,true);f.innerText=''}
rows();messages();
</script>'''


class InboxTests(unittest.TestCase):
    setUpClass = base.ChatTests.__dict__['setUpClass']
    tearDownClass = base.ChatTests.__dict__['tearDownClass']
    tearDown = base.ChatTests.tearDown
    call = base.ChatTests.call
    draft = base.ChatTests.draft
    authorize = base.ChatTests.authorize
    send = base.ChatTests.send

    def setUp(self):
        base.ChatTests.setUp(self)
        self.source = self.page
        self.source.locator('.shop-name').evaluate("e=>e.innerText='测试店'")
        self.context.route('**/app/im/chat-core/index.html', lambda r:r.fulfill(content_type='text/html; charset=utf-8', body=WW))
        self.source.locator('[data-merchant-contact]').evaluate("(e,url)=>{const a=document.createElement('a');a.href=url;a.target='_blank';a.innerText='联系客服';e.replaceWith(a)}", URL)
        result = base.ChatTests.open(self)
        self.tab = result['state']['tabId']
        self.page = next(p for p in self.c.pages if self.c.tab_id(p) == self.tab)
        self.original_cid = self.cid

    def listing(self):
        return self.call('list_merchant_chats')

    def choose(self, label, request='switch-b', **kwargs):
        listing = self.listing()
        entry = next(e for e in listing['entries'] if e['label'] == label)
        return self.call('switch_merchant_chat', controlId=entry['controlId'], requestId=request, **kwargs)

    def test_list_actual_labels_unread_preview_opaque_ids(self):
        rows = self.listing()
        self.assertEqual([e['label'] for e in rows['entries']], ['测试店','第二店旗舰店','第三店'])
        self.assertEqual(rows['entries'][1]['unreadCount'], 3)
        self.assertEqual(rows['entries'][1]['preview'], 'B店答复')
        self.assertNotIn('private-account', json.dumps(rows))
        self.assertNotIn('path', rows['entries'][0])
        self.assertEqual(self.page.evaluate('[switchCount,sendCount,deleted]'), [0,0,0])

    def test_search_native_enter_and_clear_without_changing_thread(self):
        result = self.call('search_merchant_chats', keyword='第二店')
        self.assertTrue(result['confirmed']); self.assertEqual(len(result['entries']), 1)
        self.assertEqual(result['currentRecipient']['label'], '测试店')
        again = self.call('search_merchant_chats', keyword='第二店')
        self.assertTrue(again['replayed']); self.assertEqual(self.page.evaluate('searchEnters'), 1)
        result = self.call('search_merchant_chats', keyword='')
        self.assertEqual(len(result['entries']), 3); self.assertEqual(self.page.evaluate('[switchCount,sendCount]'), [0,0])

    def test_search_empty_result_and_unverified_filtering(self):
        result = self.call('search_merchant_chats', keyword='不存在的店')
        self.assertTrue(result['confirmed']); self.assertEqual(result['entries'], [])
        self.page.evaluate('noFilter=true')
        result = self.call('search_merchant_chats', keyword='第二')
        self.assertFalse(result['confirmed']); self.assertFalse(result['filteringVerified'])

    def test_switch_unknown_shop_read_only_and_repeat_no_click(self):
        count = len(self.c.pages)
        result = self.choose('第二店旗舰店')
        self.assertTrue(result['confirmed']); self.assertTrue(result['state']['readOnly']); self.assertFalse(result['state']['canCompose'])
        self.assertEqual(result['state']['messages'][0]['text'], 'B店答复')
        self.assertEqual(len(self.c.pages), count)
        cid = result['state']['conversationId']
        self.call('switch_merchant_chat', requestId='switch-b')
        self.assertEqual(self.page.evaluate('[switchCount,sendCount,deleted]'), [1,0,0])
        with self.assertRaisesRegex(RuntimeError, 'CHAT_READ_ONLY'):
            self.call('prepare_invoice_inquiry', conversationId=cid)

    def test_original_id_rejected_on_another_shop_messages_separate(self):
        self.listing(); before = copy.deepcopy(Store(self.c).db['conversations'][self.original_cid]['messages'])
        result = self.choose('第二店旗舰店')
        with self.assertRaisesRegex(RuntimeError, 'RECIPIENT_CHANGED'):
            self.call('read_merchant_messages', conversationId=self.original_cid)
        self.assertEqual(Store(self.c).db['conversations'][self.original_cid]['messages'], before)
        self.assertNotIn('A店回复', [m['text'] for m in result['state']['messages']])

    def test_return_known_conversation_preserves_draft_authorization_send_once(self):
        draft = self.draft(); grant = self.authorize(draft)
        result = self.choose('第二店旗舰店')
        with self.assertRaisesRegex(RuntimeError, 'CHAT_READ_ONLY'):
            self.call('send_merchant_message', conversationId=result['state']['conversationId'], draftId=draft['draft']['draftId'], authorizationId=grant, requestId='wrong-shop')
        back = self.choose('测试店', request='return-a', targetConversationId=self.original_cid)
        self.assertEqual(back['state']['conversationId'], self.original_cid)
        self.assertFalse(back['state']['readOnly']); self.assertTrue(self.send(draft, grant)['confirmed'])
        self.assertTrue(self.send(draft, grant)['replayed']); self.assertEqual(self.page.evaluate('sendCount'), 1)

    def test_unsent_editor_preserved_no_switch(self):
        self.page.locator('.ww_input .edit').fill('我的未发草稿')
        with self.assertRaisesRegex(RuntimeError, 'DRAFT_CONFLICT'): self.choose('第二店旗舰店')
        self.assertEqual(self.page.locator('.ww_input .edit').inner_text(), '我的未发草稿')
        self.assertEqual(self.page.evaluate('switchCount'), 0)

    def test_virtualized_row_replacement_invalidates_control(self):
        ref = self.listing()['entries'][1]['controlId']
        self.page.evaluate("shops[1].id='different-id';rows()")
        with self.assertRaisesRegex(RuntimeError, 'STALE_CONTROL'):
            self.call('switch_merchant_chat', controlId=ref, requestId='stale')
        self.assertEqual(self.page.evaluate('switchCount'), 0)

    def test_row_reorders_after_preflight_stable_identity_still_clicks_target(self):
        original = Locator.click
        changed = []
        def click(locator, *args, **kwargs):
            if not kwargs.get('trial') and not changed:
                changed.append(True)
                self.page.evaluate('shops.unshift(shops.pop());rows()')
            return original(locator, *args, **kwargs)
        with patch.object(Locator, 'click', click):
            result = self.choose('第二店旗舰店')
        self.assertTrue(result['confirmed']); self.assertEqual(result['state']['recipient']['label'], '第二店旗舰店')
        self.assertEqual(self.page.evaluate('[switchCount,deleted]'), [1,0])

    def test_content_area_works_when_name_consumes_click(self):
        self.page.locator('.conversation .name').evaluate_all('rows=>rows.forEach(e=>e.onclick=event=>event.stopPropagation())')
        result = self.choose('第二店旗舰店')
        self.assertTrue(result['confirmed']); self.assertEqual(self.page.evaluate('[switchCount,deleted]'), [1,0])

    def test_search_invalidates_previous_control(self):
        ref = self.listing()['entries'][1]['controlId']
        self.call('search_merchant_chats', keyword='第三')
        with self.assertRaisesRegex(RuntimeError, 'STALE_CONTROL'):
            self.call('switch_merchant_chat', controlId=ref, requestId='old-search-control')

    def test_uncertain_selection_resume_only_reads(self):
        self.page.evaluate('stopSwitch=true')
        result = self.choose('第二店旗舰店')
        self.assertFalse(result['confirmed']); self.assertEqual(result['status'], 'waiting_thread')
        self.assertFalse(result['diagnostics']['selectedEntryMatches'])
        self.assertEqual(result['diagnostics']['currentLabel'], '测试店')
        with self.assertRaisesRegex(RuntimeError, 'CHAT_SWITCH_PENDING'):
            self.choose('第三店', request='cannot-repeat')
        self.page.evaluate("selected=shops[1].id;document.querySelector('.ww_header .name').innerText=shops[1].name;rows();messages()")
        self.assertTrue(self.call('switch_merchant_chat', requestId='switch-b')['confirmed'])
        self.assertEqual(self.page.evaluate('switchCount'), 1)

    def test_cancel_releases_block_without_click_or_claiming_success(self):
        self.page.evaluate('stopSwitch=true')
        result = self.choose('第二店旗舰店')
        self.assertFalse(result['confirmed'])
        record = copy.deepcopy(Store(self.c).db['inboxSwitches']['switch-b'])
        cancelled = self.call('cancel_merchant_chat_switch', requestId='switch-b')
        self.assertTrue(cancelled['localBlockReleased']); self.assertTrue(cancelled['confirmed'])
        self.assertFalse(cancelled['switchConfirmed'])
        self.assertEqual(cancelled['previousClickOutcome'], 'unverified')
        self.assertTrue(self.call('cancel_merchant_chat_switch', requestId='switch-b')['replayed'])
        replay = self.call('switch_merchant_chat', requestId='switch-b')
        self.assertEqual(replay['status'], 'cancelled'); self.assertEqual(self.page.evaluate('switchCount'), 1)
        saved = Store(self.c).db['inboxSwitches']['switch-b']
        self.assertEqual(saved['createdAt'], record['createdAt']); self.assertTrue(saved['actionAttempted'])
        self.assertFalse(self.listing()['pendingSwitches'])
        self.page.evaluate('stopSwitch=false')
        self.assertTrue(self.choose('第三店', request='new-selection')['confirmed'])
        self.assertEqual(self.page.evaluate('[switchCount,sendCount,deleted]'), [2,0,0])

    def test_cancel_does_not_undo_completed_selection(self):
        self.choose('第二店旗舰店')
        result = self.call('cancel_merchant_chat_switch', requestId='switch-b')
        self.assertFalse(result['cancelled']); self.assertEqual(result['status'], 'confirmed')
        self.assertEqual(self.page.evaluate('switchCount'), 1)

    def test_old_message_body_not_merged_after_header_changed(self):
        self.page.evaluate('keepOldMessages=true')
        result = self.choose('第二店旗舰店')
        self.assertFalse(result['confirmed'])
        self.assertFalse(any(r.get('readOnly') for r in Store(self.c).db['conversations'].values()))
        self.page.evaluate('messages()')
        result = self.call('switch_merchant_chat', requestId='switch-b')
        self.assertTrue(result['confirmed']); self.assertEqual(result['state']['messages'][0]['text'], 'B店答复')
        self.assertEqual(self.page.evaluate('switchCount'), 1)

    def test_completed_request_does_not_switch_back_after_manual_change(self):
        self.choose('第二店旗舰店')
        self.page.evaluate("selected=shops[2].id;document.querySelector('.ww_header .name').innerText=shops[2].name;rows();messages()")
        result = self.call('switch_merchant_chat', requestId='switch-b')
        self.assertFalse(result['confirmed']); self.assertEqual(result['status'], 'selection_changed')
        self.assertEqual(self.page.evaluate('switchCount'), 1)

    def test_request_conflict_and_wrong_saved_conversation(self):
        with self.assertRaisesRegex(RuntimeError, 'RECIPIENT_UNVERIFIED'):
            self.choose('第二店旗舰店', targetConversationId=self.original_cid)
        self.choose('第二店旗舰店')
        with self.assertRaisesRegex(RuntimeError, 'CHAT_REQUEST_CONFLICT'):
            self.call('switch_merchant_chat', requestId='switch-b', targetConversationId=self.original_cid)

    def test_duplicate_names_do_not_inherit_existing_send_scope(self):
        self.page.evaluate("shops.push({id:'different-a',name:shops[0].name,msg:'重复店名的另一会话',unread:0});rows()")
        entry = self.listing()['entries'][-1]
        result = self.call('switch_merchant_chat', controlId=entry['controlId'], requestId='duplicate')
        self.assertTrue(result['state']['readOnly'])

    def test_list_scroll_only_current_panel_and_no_shop_switch(self):
        self.page.evaluate("for(let i=0;i<12;i++)shops.push({id:'extra-'+i,name:'额外店'+i,msg:'回复'+i,unread:0});rows()")
        listing = self.listing(); before = self.page.evaluate('window.scrollY')
        result = self.call('load_more_merchant_chats', listId=listing['listId'])
        self.assertTrue(result['scrolled']); self.assertGreater(result['scroll']['top'], 0)
        self.assertEqual(self.page.evaluate('window.scrollY'), before)
        self.assertEqual(self.page.evaluate('[switchCount,sendCount]'), [0,0])

    def test_login_and_disconnect_stop_before_native_switch(self):
        self.page.evaluate("document.body.insertAdjacentHTML('beforeend','<p>请登录</p>')")
        with self.assertRaisesRegex(RuntimeError, 'Verification/login'): self.listing()
        self.page.locator('p').last.evaluate('e=>e.remove()')
        base.ChatTests.disconnect(self)
        with self.assertRaisesRegex(RuntimeError, 'CHAT_DISCONNECTED'): self.choose('第二店旗舰店')
        self.assertEqual(self.page.evaluate('switchCount'), 0)


class InboxEvidenceTests(unittest.TestCase):
    def test_merchant_text_cannot_prove_empty_search(self):
        self.assertFalse(filter_matches({'entries':[],'emptyText':'某店：没有发票'}, '某店'))
        self.assertFalse(filter_matches({'entries':[],'emptyText':None}, '某店'))
        self.assertTrue(filter_matches({'entries':[],'emptyText':'暂无搜索结果'}, '某店'))

    def test_author_reclassification_is_not_message_body_transition(self):
        a = {'messages':[{'text':'旧店气泡','timeText':'12:00','direction':'incoming','authorType':'merchant-side'}]}
        b = copy.deepcopy(a);b['messages'][0].update(direction='unknown',authorType='unknown')
        self.assertEqual(thread_signature(a),thread_signature(b))
        b['messages'][0]['text']='新店正文'
        self.assertNotEqual(thread_signature(a),thread_signature(b))


if __name__ == '__main__':
    unittest.main(verbosity=2)
