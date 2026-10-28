"""Scoped merchant UI messaging. Merchant content is data, never authorization.

Authorization is provisioned locally for exact drafts, not through an MCP boolean.
This is a local workflow guard, not a security boundary against shell/file access.
"""
import copy
import hashlib
import json
import time
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse

from .huoyan_browser import atomic_json, load_json, dom_script, product_identity, stamp

OPERATIONS = {'merchant_contact_options', 'open_merchant_chat', 'merchant_chat_state',
              'cancel_merchant_contact', 'finish_merchant_read',
              'recover_merchant_chat',
              'prepare_invoice_inquiry', 'send_merchant_message', 'read_merchant_messages',
              'wait_merchant_reply', 'load_merchant_history', 'summarize_invoice_terms',
              'return_from_merchant_chat', 'finish_merchant_inquiry'}
OFFLINE = {'summarize_invoice_terms', 'finish_merchant_inquiry', 'cancel_merchant_contact', 'finish_merchant_read'}
# Cleanup exemption: these operations never create tabs. Reads may recover a known disconnect.
READONLY = OPERATIONS - {'open_merchant_chat', 'send_merchant_message', 'load_merchant_history', 'return_from_merchant_chat'}
AUTO_RECOVERY = {'merchant_chat_state', 'read_merchant_messages', 'wait_merchant_reply', 'prepare_invoice_inquiry', 'recover_merchant_chat'}


def fail(code, message):
    raise RuntimeError(f'{code}: {message}')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class Store:
    def __init__(self, c):
        self.c = c
        self.file = c.out / 'merchant-chat' / 'state.json'
        self.db = load_json(self.file, {'endpoint': c.endpoint, 'conversations': {}, 'inquiries': {}, 'drafts': {}, 'outbox': {}, 'contacts': {}})
        if self.db.get('endpoint') != c.endpoint:
            fail('CHAT_SESSION_CHANGED', 'Chat records belong to another browser endpoint.')

    def save(self):
        atomic_json(self.file, self.db)

    def get(self, table, key):
        result = self.db[table].get(key)
        if result is None:
            fail('CHAT_NOT_FOUND', f'Unknown {table} reference.')
        return result


def protected_tabs(c):
    """Persisted task protection also survives controller restart. Never navigates."""
    protected = set()
    workflows = load_json(c.out / 'workflows.json', {})
    if workflows.get('endpoint') == c.endpoint:
        for row in workflows.get('runs', {}).values():
            if row.get('status') not in ('completed', 'already_asked') and row.get('protectUntil', 0) > time.time():
                protected.update(tab for tab in (row.get('sourceTabId'), row.get('chatTabId')) if tab)
    db = load_json(c.out / 'merchant-chat' / 'state.json', {})
    if db.get('endpoint') != c.endpoint:
        return protected
    unresolved = {r['conversationId'] for r in db.get('outbox', {}).values() if r['status'] in ('dispatching', 'sent_unconfirmed')}
    for cid, row in db.get('conversations', {}).items():
        if row.get('active', False) and row.get('protectUntil', 0) > time.time() or cid in unresolved:
            protected.update((row['tabId'], row['source']['tabId']))
    for inquiry in db.get('inquiries', {}).values():
        if inquiry['status'] == 'active' and inquiry.get('expiresAt', 0) > time.time():
            protected.add(inquiry['source']['tabId'])
    for attempt in db.get('outbox', {}).values():
        if attempt['status'] in ('dispatching', 'sent_unconfirmed'):
            inquiry = db.get('inquiries', {}).get(attempt['inquiryId'], {})
            if inquiry.get('source'):
                protected.add(inquiry['source']['tabId'])
    for attempt in db.get('openAttempts', {}).values():
        if attempt['status'] != 'attached' and attempt.get('protectUntil', 0) > time.time():
            protected.add(attempt['source']['tabId'])
            if attempt.get('targetTabId'):
                protected.add(attempt['targetTabId'])
    return protected


def probe(frame, mode='chat'):
    raw = frame.evaluate(dom_script('merchantChatDom.js'), {'mode': mode})
    # List IDs contain account identifiers. Only opaque keys leave this private adapter.
    if 'selectedEntryId' in raw:
        value = raw.pop('selectedEntryId')
        raw['inboxEntryKey'] = digest(['ww-inbox-v1', value]) if value else None
    for entry in raw.get('entries', []):
        entry['entryKey'] = digest(['ww-inbox-v1', entry.pop('platformId')])
    return raw


def revision(raw):
    return digest({k: raw.get(k) for k in ('rootPath', 'identity', 'field', 'controls')})


def visible_shop_name(page):
    # Only rendered store-name nodes. Never use link labels such as "进店".
    return page.evaluate('''()=>{const names=[...new Set([...document.querySelectorAll('[data-shop-name],[class*="shopName--"],.shop-name')]
      .filter(e=>{const r=e.getBoundingClientRect();return r.width>1&&r.height>1&&getComputedStyle(e).visibility!=='hidden'})
      .map(e=>(e.innerText||'').replace(/\\s+/g,' ').trim()).filter(x=>x&&!/^(进店|进入店铺|进店逛逛|店铺首页)$/.test(x)))];return names.length===1?names[0]:null}''')


def source_context(c, page):
    from .shopping_research import read
    data = read(c, page)
    if data['pageType'] not in ('product', 'shop'):
        fail('WRONG_PAGE_TYPE', 'Open a product or verified shop before contacting a merchant.')
    identities = [x['shopIdentity'] for x in data['controls'] if x['action'] == 'open_shop']
    if data.get('shopDom', {}).get('identity'):
        identities.append(data['shopDom']['identity'])
    unique = {i['key']: i for i in identities}
    if len(unique) != 1:
        fail('RECIPIENT_UNVERIFIED', 'Source page does not identify exactly one merchant.')
    product = data.get('product')
    if product and product.get('skuCandidates'):
        all_selected = all(sum(bool(o['selected']) for o in g['options']) == 1 for g in product['skuCandidates'])
    else:
        all_selected = not product or not product.get('skuCandidates')
    return {'tabId': c.tab_id(page), 'url': page.url, 'shop': next(iter(unique.values())),
            'visibleShopName': visible_shop_name(page),
            'product': {k: product.get(k) for k in ('productId', 'title', 'selectedSku', 'prices')} if product else None,
            'allSkuSelected': all_selected}


def same_source_context(before, after, allow_name_upgrade=False):
    if not before or not after:
        return False
    before, after = copy.deepcopy(before), copy.deepcopy(after)
    # Observed real shop links acquire an analytics spm query on interaction.
    # Stable shop identity remains mandatory; the link is never navigated here.
    for value in (before, after):
        value.get('shop', {}).pop('url', None)
    if allow_name_upgrade and not before.get('visibleShopName'):
        before['visibleShopName'] = after.get('visibleShopName')
    return before == after


def contact_options(c, store):
    from .shopping_research import page_for
    page = page_for(c)
    source = source_context(c, page)
    raw = probe(page, 'contacts')
    generation = uuid.uuid4().hex
    records = {}
    for i, row in enumerate(raw['controls']):
        if row.get('shopId') and row['shopId'] != source['shop'].get('shopId'):
            continue
        ref = f'chat-contact:{generation}:{i}'
        records[ref] = row
    store.db['contacts'][source['tabId']] = {'source': source, 'records': records}
    store.save()
    pending = store.db.get('openAttempts', {}).get(source['tabId'])
    return {'contacts': [{k: v for k, v in row.items() if k != 'path'} | {'controlId': key}
                         for key, row in records.items()], 'source': source,
            'pendingChat': {k: pending.get(k) for k in ('status', 'targetTabId', 'reason')} if pending and pending['status'] != 'attached' else None,
            'coverage': 'rendered top-document contact entries only', 'unsupportedFrames': bool(raw['iframeCount']),
            'note': 'Opening a contact entry may cause platform-generated product cards. Sending requires separate task authorization.'}


def frame_for(c, page, frame_url):
    from .shopping_research import supported
    frames = [f for f in page.frames if f.url == frame_url and supported(f.url)]
    if len(frames) != 1:
        fail('CHAT_UNSUPPORTED', 'Chat frame missing, navigated or ambiguous; no interaction.')
    c.guard(frames[0])
    return frames[0]


def discover_chat(c, page):
    from .shopping_research import supported
    matches = []
    diagnostics = []
    for frame in page.frames:
        if not supported(frame.url):
            continue
        if frame != page.main_frame:
            element = frame.frame_element()
            if not element.is_visible():
                continue
        c.guard(frame)
        raw = probe(frame)
        if raw.get('supported'):
            matches.append((frame, raw))
        elif raw.get('recognized'):
            diagnostics.append(raw)
    if len(matches) != 1:
        if diagnostics:
            fail('CHAT_NOT_READY', 'Recognized Taobao WangWang web shell, but recipient/message template is not verified. No send. Preserve and resume the existing tab; never reopen contact to retry.')
        fail('CHAT_UNSUPPORTED', 'No unique supported rendered web-chat structure. Native clients and unverified domains are unsupported.')
    return matches[0]


def verify_recipient(row, raw):
    identity = raw['identity']
    if row.get('inboxEntryKey') and raw.get('inboxEntryKey') != row['inboxEntryKey']:
        fail('RECIPIENT_CHANGED', 'Selected chat-list identity missing or changed; reselect the original entry.')
    if row.get('readOnly'):
        if not row.get('inboxEntryKey') or identity != row.get('identity'):
            fail('RECIPIENT_CHANGED', 'Read-only list conversation identity changed.')
        return {'verified': True, 'listEntryMatch': True, 'sendEligible': False,
                'scope': 'selected list entry and exact header only; no product/source merchant authentication'}
    shop_id = row['source']['shop'].get('shopId')
    receiver = row.get('receiverId')
    if identity.get('shopId') and shop_id and identity['shopId'] != shop_id:
        fail('RECIPIENT_CHANGED', 'Chat shop identity differs from source merchant.')
    if identity.get('receiverId') and receiver and identity['receiverId'] != receiver:
        fail('RECIPIENT_CHANGED', 'Chat recipient changed.')
    shop_match = bool(shop_id and identity.get('shopId') == shop_id)
    receiver_match = bool(receiver and identity.get('receiverId') == receiver)
    label_match = bool(raw.get('adapter') == 'taobao-ww-web-v1' and row.get('openedByTool') and
                       row['source'].get('visibleShopName') and identity.get('label') == row['source']['visibleShopName'])
    # Local aliases require an explicit human confirmation, never merchant text.
    aliases = load_json(Path(__file__).resolve().parents[1] / 'data' / 'human-confirmed-shop-aliases.json', {}).get('aliases', [])
    human_alias = bool(raw.get('adapter') == 'taobao-ww-web-v1' and row.get('openedByTool') and any(
        a.get('shopKey') == row['source']['shop'].get('key') and
        a.get('sourceLabel') == row['source'].get('visibleShopName') and
        a.get('chatLabel') == identity.get('label') and a.get('userReference') for a in aliases))
    if not (shop_match or receiver_match or label_match or human_alias):
        fail('RECIPIENT_UNVERIFIED', f"Chat lacks identity evidence linking it to the source merchant. sourceShop={row['source'].get('visibleShopName')!r}; chatLabel={identity.get('label')!r}; adapter={raw.get('adapter')!r}; openedByTool={bool(row.get('openedByTool'))}")
    if row.get('identity') and row['identity'] != identity:
        fail('RECIPIENT_CHANGED', 'Conversation identity evidence changed; rediscover explicitly.')
    return {'verified': True, 'shopIdMatch': shop_match, 'receiverIdMatch': receiver_match,
            'humanConfirmedScopedAliasMatch': human_alias,
            'trackedContactAndExactVisibleNameMatch': label_match, 'scope': 'page evidence, not independent merchant authentication; name match is not a numeric seller-ID match'}


def merge_messages(row, raw):
    """Keep immutable evidence revisions. Weak IDs use sequence alignment, not text-set dedup."""
    import difflib
    old = row.setdefault('messages', [])
    previous = row.get('window', [])
    previous_map = {m['evidenceId']: m for m in old}
    def key(m):
        return ('platform', m['platformId']) if m.get('platformId') else ('weak', digest([m.get(x) for x in ('direction', 'text', 'timeText', 'images', 'withdrawn')]))
    current = raw['messages']
    prior_keys = [key(previous_map[e]) for e in previous]
    current_keys = [key(m) for m in current]
    matched = {}
    for block in difflib.SequenceMatcher(a=prior_keys, b=current_keys, autojunk=False).get_matching_blocks():
        for offset in range(block.size):
            matched[block.b + offset] = previous[block.a + offset]
    stable = {m['platformId']: m for m in old if m.get('platformId')}
    window = []
    for i, msg in enumerate(current):
        existing = stable.get(msg.get('platformId')) if msg.get('platformId') else previous_map.get(matched.get(i))
        if existing is None and not msg.get('platformId') and msg.get('timeText') and not msg.get('contentUnavailable'):
            # A previously opaque rich-card can become readable after an adapter
            # upgrade. Preserve its ID only for a unique time/image observation.
            opaque = [previous_map[e] for e in previous if e not in window and
                      not previous_map[e].get('platformId') and previous_map[e].get('contentUnavailable') and
                      previous_map[e].get('timeText') == msg['timeText'] and previous_map[e].get('images') == msg.get('images')]
            if len(opaque) == 1:
                existing = opaque[0]
        if existing:
            eid = existing['evidenceId']
            comparable = {k: existing.get(k) for k in msg}
            if comparable != msg:
                row.setdefault('revisions', []).append({'evidenceId': eid, 'previous': copy.deepcopy(existing), 'observedAt': stamp()})
                existing.update(msg, lastObservedAt=stamp())
        else:
            eid = uuid.uuid4().hex
            old.append({**msg, 'evidenceId': eid, 'sequence': len(old) + 1, 'observedAt': stamp()})
        window.append(eid)
    gap = bool(previous and not set(previous).intersection(window))
    row['window'] = window
    row['historyGap'] = row.get('historyGap', False) or gap
    row['weakIdentity'] = any(not m.get('platformId') for m in current)
    return gap


def connection_health(c, page, row):
    """Only the original document and its tracked chat frame; never inspect arbitrary tabs."""
    frame = frame_for(c, page, row['frameUrl'])
    frames = [page.main_frame] + ([frame] if frame != page.main_frame else [])
    dialogs = []
    for candidate in frames:
        c.guard(candidate)
        for dialog in probe(candidate, 'connection')['dialogs']:
            dialogs.append({**dialog, 'frameUrl': candidate.url})
    return {'status': 'disconnected' if dialogs else 'no_disconnect_observed', 'transportVerified': False,
            'dialogs': dialogs, 'scope': 'visible disconnect dialog, not socket/server health'}


def require_connection(c, page, row):
    if connection_health(c, page, row)['status'] == 'disconnected':
        fail('CHAT_DISCONNECTED', 'Known chat disconnect dialog. Read merchant_chat_state to recover the original tab once; never resend an existing request.')


def recover_connection(c, store, row, page, raw, health):
    """One native refresh per persistent disconnect, journaled before dispatch. Never sends."""
    operation_deadline = min(getattr(c, 'chat_wait_deadline', None) or float('inf'),
                             getattr(c, 'workflow_deadline', None) or float('inf'))
    if operation_deadline - time.monotonic() < .2:
        return {'status': 'budget_exhausted', 'actionAttempted': False, 'reason': 'Read/wait budget exhausted; recover in a later call, no click.'}
    def native_timeout():
        remaining = operation_deadline - time.monotonic()
        if remaining <= 0:
            fail('CHAT_RECOVERY_BUDGET', 'No time for a native recovery action; original tab preserved.')
        return min(5000, max(1, int(remaining * 1000))) if remaining != float('inf') else 5000
    previous = row.get('connectionRecovery')
    if previous and previous.get('actionAttempted'):
        if previous['status'] not in ('recovered', 'cleared_without_retry'):
            return previous  # Crashes, timeouts and persistent dialogs never cause a second click.
        if time.time() - previous['startedEpoch'] < 60:
            return {**previous, 'status': 'cooldown', 'reason': 'Disconnect recurred within 60 seconds; no repeated refresh.'}
    if raw.get('field') and raw['field']['value']:
        return {'status': 'draft_preserved', 'actionAttempted': False, 'reason': 'Unsent input preserved; refresh could discard it.'}
    if not raw.get('field'):
        return {'status': 'unsupported', 'actionAttempted': False, 'reason': 'Cannot verify a unique empty editor; no refresh.'}
    dialogs = health['dialogs']
    if len(dialogs) != 1 or len(dialogs[0]['controls']) != 1 or dialogs[0]['controls'][0]['disabled']:
        return {'status': 'unsupported', 'actionAttempted': False, 'reason': 'No unique enabled refresh inside the recognized disconnect dialog.'}
    attempt = {'attemptId': uuid.uuid4().hex, 'status': 'preparing', 'startedAt': stamp(), 'startedEpoch': time.time(),
               'actionAttempted': False, 'confirmed': False, 'method': 'native-dialog-refresh', 'messageResent': False}
    row['connectionRecovery'] = attempt
    store.save()
    try:
        c.focus.prepare_action(page)
        frame = frame_for(c, page, dialogs[0]['frameUrl'])
        loc = frame.locator(dialogs[0]['controls'][0]['path'])
        loc.click(trial=True, timeout=native_timeout())
        # A successful preflight is not permission to ignore a changed merchant or draft.
        c.guard(page)
        c.focus.require(page)
        ready = probe(frame_for(c, page, row['frameUrl']))
        if not ready.get('supported'):
            fail('CHAT_UNSUPPORTED', 'Chat disappeared before recovery.')
        verify_recipient(row, ready)
        if page.url != row['chatUrl'] or connection_health(c, page, row) != health:
            fail('CHAT_SOURCE_CHANGED', 'Disconnect controls/page changed before recovery.')
        if not ready.get('field') or ready['field']['value']:
            fail('DRAFT_CONFLICT', 'Input changed during recovery preflight; preserved.')
        c.focus.begin(page)
        click_timeout = native_timeout()
        attempt.update(status='dispatching', actionAttempted=True)
        store.save()
        loc.click(timeout=click_timeout)
        deadline = min(time.monotonic() + 8, operation_deadline)
        while True:
            c.guard(page)
            if page.url != row['chatUrl']:
                fail('CHAT_SOURCE_CHANGED', 'Recovery navigated away; no URL reopened.')
            c.focus.require(page)
            try:
                current = probe(frame_for(c, page, row['frameUrl']))
                if current.get('supported'):
                    verify_recipient(row, current)
                    if connection_health(c, page, row)['status'] != 'disconnected':
                        merge_messages(row, current)
                        for outgoing in store.db['outbox'].values():
                            if outgoing['conversationId'] == row['conversationId'] and outgoing['status'] in ('dispatching', 'sent_unconfirmed', 'observed_outgoing'):
                                reconcile(row, outgoing)
                        attempt.update(status='recovered', confirmed=True, recoveredAt=stamp(),
                                       evidence='same tab, URL and verified recipient; known dialog absent; rendered thread readable',
                                       transportVerified=False)
                        store.save()
                        return attempt
            except RuntimeError as error:
                if not str(error).startswith('CHAT_UNSUPPORTED:'):
                    raise
            if time.monotonic() >= deadline:
                attempt.update(status='not_recovered', reason='Original chat not ready or dialog remains after one refresh; no retry.')
                store.save()
                return attempt
            page.wait_for_timeout(200)
    except Exception as error:
        attempt.update(status='uncertain' if attempt['actionAttempted'] else 'not_dispatched',
                       reason=str(error).split(':', 1)[0], confirmed=False)
        store.save()
        # Login, recipient changes and native focus failures retain their original stop semantics.
        raise


def resolve(c, store, require_focus=True):
    cid = c.args.get('conversationId')
    row = store.get('conversations', cid)
    page = next((p for p in c.pages if c.tab_id(p) == row['tabId']), None)
    if not page or page.url != row['chatUrl']:
        fail('CHAT_SOURCE_CHANGED', 'Conversation tab closed or navigated; no URL reopened.')
    if c.args.get('tabId') and c.args['tabId'] != row['tabId']:
        fail('CHAT_SOURCE_CHANGED', 'tabId does not match conversation.')
    c.guard(page)
    if require_focus:
        c.focus.require(page)
    frame = frame_for(c, page, row['frameUrl'])
    raw = probe(frame)
    if not raw.get('supported'):
        fail('CHAT_UNSUPPORTED', 'Recognized conversation is no longer available.')
    evidence = verify_recipient(row, raw)
    # Bind evidence IDs to this conversation even if a platform reuses message IDs.
    merge_messages(row, raw)
    health = connection_health(c, page, row)
    if health['status'] == 'disconnected' and c.args.get('operation') in AUTO_RECOVERY:
        recovery = recover_connection(c, store, row, page, raw, health)
        frame = frame_for(c, page, row['frameUrl'])
        raw = probe(frame)
        if not raw.get('supported'):
            fail('CHAT_RECOVERY_NOT_READY', 'One recovery already attempted. Preserve original tab and request IDs; read later, never resend.')
        evidence = verify_recipient(row, raw)
        merge_messages(row, raw)
        health = connection_health(c, page, row)
        health['recovery'] = copy.deepcopy(recovery)
    elif health['status'] == 'no_disconnect_observed':
        previous = row.get('connectionRecovery')
        if previous and previous.get('actionAttempted') and previous['status'] not in ('recovered', 'cleared_without_retry'):
            previous.update(status='cleared_without_retry', clearedAt=stamp())
    row['connection'] = {k: v for k, v in health.items() if k != 'dialogs'}
    row['connection']['lastRecovery'] = copy.deepcopy(row.get('connectionRecovery'))
    row['connection']['nextAction'] = ('Read original conversation; no message resend. Handle manually if one recovery did not clear the dialog.'
                                      if health['status'] == 'disconnected' else 'Continue from observed messages; transport delivery remains unverified.')
    store.save()
    return row, page, frame, raw, evidence


def state(c, store):
    row, page, frame, raw, evidence = resolve(c, store)
    generation = uuid.uuid4().hex
    controls = {f'chat:{generation}:{i}': x for i, x in enumerate(raw['controls'])
                if (row['connection']['status'] != 'disconnected' or x['action'] == 'close') and not (row.get('readOnly') and x['action'] == 'send')}
    row['controls'] = controls
    row['revision'] = revision(raw)
    store.save()
    return {'conversationId': c.args['conversationId'], 'tabId': row['tabId'], 'recipient': raw['identity'], 'recipientEvidence': evidence,
            'active': row.get('active'), 'stateVersion': generation, 'draftPresent': bool(raw.get('field') and raw['field']['value']),
            'controls': [{k: v for k, v in x.items() if k != 'path'} | {'controlId': ref} for ref, x in controls.items()],
            'canCompose': raw['field'] is not None and row['connection']['status'] != 'disconnected' and not row.get('readOnly', False),
            'readOnly': row.get('readOnly', False), 'inboxEntryKey': row.get('inboxEntryKey'),
            'connection': row['connection'], 'coverage': raw['coverage'], 'historyGap': row.get('historyGap', False),
            'weakMessageIdentity': row.get('weakIdentity', True), 'messages': [m for m in row['messages'] if m['evidenceId'] in row['window']],
            'cursor': cursor(row), 'adapter': raw['adapter'], 'compatibility': raw['compatibility'],
            'readSideEffect': 'Displaying messages may mark them read on the platform.', 'backgroundListener': False}


def cursor(row):
    return {'conversationId': row['conversationId'], 'sequence': len(row.get('messages', [])), 'window': row.get('window', [])[-8:], 'revisionCount': len(row.get('revisions', []))}


def read_messages(c, store):
    row, _, _, raw, _ = resolve(c, store)
    before = c.args.get('cursor') or c.args.get('afterCursor')
    limit = c.args.get('limit', 50)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
        raise ValueError('limit must be an integer in 1..200.')
    seq = 0
    if before:
        seq = before.get('sequence')
        if before.get('conversationId') != row['conversationId'] or not isinstance(seq, int) or not 0 <= seq <= len(row['messages']):
            fail('CHAT_CURSOR_INVALID', 'Cursor is not valid for this conversation.')
    all_new = [m for m in row['messages'] if m['sequence'] > seq]
    result = all_new[:limit]
    next_cursor = cursor(row)
    next_cursor['sequence'] = result[-1]['sequence'] if result else seq
    gap = bool(before and before.get('window') and not set(before['window']).intersection(row['window']))
    revisions = row.get('revisions', [])[before.get('revisionCount', 0) if before else 0:]
    return {'conversationId': row['conversationId'], 'messages': result, 'revisions': revisions, 'cursor': next_cursor,
            'connection': row['connection'],
            'hasMoreStored': len(all_new) > limit, 'historyGap': row.get('historyGap', False) or gap,
            'coverage': raw['coverage'], 'receivedNewMerchantMessage': any(m['direction'] == 'incoming' for m in result),
            'backgroundListener': False}


def attach_chat(c, store, page, target, source, entry, reused=False):
    pending = store.db.get('openAttempts', {}).get(source['tabId'])
    try:
        seconds = c.args.get('chatReadyTimeoutSeconds', 8)
        if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or not 0 <= seconds <= 15:
            raise ValueError('chatReadyTimeoutSeconds must be 0..15.')
        c.focus.prepare_action(target)
        deadline = time.monotonic() + seconds
        while True:
            try:
                frame, raw = discover_chat(c, target)
                break
            except RuntimeError as error:
                if not str(error).startswith('CHAT_NOT_READY:') or time.monotonic() >= deadline:
                    raise
                if getattr(c, 'workflow_check', None):
                    c.workflow_check()
                target.wait_for_timeout(200)
    except RuntimeError as error:
        if pending:
            pending.update(status='not_ready', reason=str(error))
            store.save()
        raise
    row = {'conversationId': uuid.uuid4().hex, 'source': source, 'receiverId': entry.get('receiverId'),
           'tabId': c.tab_id(target), 'chatUrl': target.url, 'frameUrl': frame.url, 'active': True,
           'protectUntil': time.time() + 86400,
           'openedByTool': True, 'sameTabNavigation': target is page and source['url'] != target.url, 'createdAt': stamp()}
    verify_recipient(row, raw)
    row['identity'] = raw['identity']
    store.db['conversations'][row['conversationId']] = row
    if pending:
        pending.update(status='attached', conversationId=row['conversationId'])
    store.save()
    c.args['conversationId'] = row['conversationId']
    c.args['tabId'] = row['tabId']
    return {'confirmed': True, 'clicks': 0 if reused else 1, 'reused': reused, 'state': state(c, store),
            'automaticPlatformMessages': 'Unknown; opening contact may send platform-generated context cards.'}


def open_chat(c, store):
    from .shopping_research import page_for, supported
    page = page_for(c)
    source = source_context(c, page)
    saved = store.db['contacts'].get(source['tabId'], {})
    entry = saved.get('records', {}).get(c.args.get('controlId'))
    if not entry or not same_source_context(saved.get('source'), source) or entry not in probe(page, 'contacts')['controls']:
        fail('STALE_CONTROL', 'Read current merchant_contact_options first.')
    existing = [x for x in store.db['conversations'].values() if x['source']['shop']['key'] == source['shop']['key'] and x.get('receiverId') == entry.get('receiverId')]
    live = {c.tab_id(p): p for p in c.pages}
    existing = [x for x in existing if x['tabId'] in live and live[x['tabId']].url == x['chatUrl'] and not x.get('panelClosedByTool')]
    if len(existing) > 1:
        fail('CHAT_AMBIGUOUS', 'Multiple existing conversations; choose their conversationId explicitly.')
    if existing:
        row = existing[0]
        # Reuse only after checking current identity. Never navigate or refresh.
        target = live[row['tabId']]
        frame = frame_for(c, target, row['frameUrl'])
        verify_recipient(row, probe(frame))
        row['source'] = source
        row['active'] = True
        row['protectUntil'] = time.time() + 86400
        store.save()
        c.focus.bind(target, origin=page)
        c.args['conversationId'] = row['conversationId']
        c.args['tabId'] = row['tabId']
        return {'confirmed': True, 'reused': True, 'clicks': 0, 'state': state(c, store)}
    pending = store.db.get('openAttempts', {}).get(source['tabId'])
    if pending and pending['status'] != 'attached':
        target = live.get(pending.get('targetTabId'))
        if not same_source_context(pending['source'], source, allow_name_upgrade=True) or not target or target.url != pending.get('chatUrl'):
            fail('CHAT_OPEN_UNCONFIRMED', 'Previous contact click is unresolved or its target closed/changed; inspect tabs. No repeat click or URL reopening.')
        pending['source'] = source
        store.save()
        c.focus.bind(target, origin=page)
        return attach_chat(c, store, page, target, source, entry, reused=True)
    if entry.get('href') and not supported(entry['href']):
        fail('CHAT_UNSUPPORTED', 'Observed contact opens an unverified domain or native application; not clicked.')
    c.focus.prepare_action(page)
    c.pause(page)
    c.guard(page)
    c.focus.require(page)
    if not same_source_context(source_context(c, page), source) or entry not in probe(page, 'contacts')['controls']:
        fail('STALE_CONTROL', 'Contact or source changed before click.')
    loc = page.locator(entry['path'])
    loc.click(trial=True, timeout=5000)
    c.tab_budget.before_popup(page, loc)
    c.guard(page)
    c.focus.require(page)
    if not same_source_context(source_context(c, page), source) or entry not in probe(page, 'contacts')['controls']:
        fail('STALE_CONTROL', 'Contact/source changed during native preflight; not clicked.')
    pages_before = set(c.pages)
    c.focus.begin(page)
    pending = {'source': source, 'entry': entry, 'status': 'dispatching', 'targetTabId': None, 'createdAt': stamp(), 'protectUntil': time.time() + 86400}
    store.db.setdefault('openAttempts', {})[source['tabId']] = pending
    store.save()
    loc.click(timeout=5000)
    page.wait_for_timeout(500)
    popups = [p for p in c.pages if p not in pages_before]
    if len(popups) > 1:
        fail('CHAT_AMBIGUOUS', 'Multiple new tabs; inspect inventory, do not click again.')
    target = popups[0] if popups else page
    if not supported(target.url):
        fail('CHAT_UNSUPPORTED', 'Contact left supported shopping domains; no further interaction.')
    pending.update(status='opened', targetTabId=c.tab_id(target), chatUrl=target.url)
    store.save()
    c.guard(target)
    if target is not page:
        c.focus.adopt_popup(page, target)
    else:
        c.focus.bind(target)
    return attach_chat(c, store, page, target, source, entry)


def validate_source(c, row):
    page = next((p for p in c.pages if c.tab_id(p) == row['source']['tabId']), None)
    if page is not None and row.get('sameTabNavigation') and page.url == row.get('chatUrl'):
        session = page.context.new_cdp_session(page)
        try:
            history = session.send('Page.getNavigationHistory')
        finally:
            session.detach()
        index = history['currentIndex']
        if index < 1 or history['entries'][index - 1]['url'] != row['source']['url']:
            fail('CHAT_SOURCE_CHANGED', 'Original source history changed; no context reconstruction.')
        return page
    if page is None or page.url != row['source']['url']:
        fail('CHAT_SOURCE_CHANGED', 'Original product/shop is closed or navigated.')
    # Pure DOM read here; no focus changes to inspect a source behind the chat.
    c.guard(page)
    if row['source'].get('visibleShopName') and visible_shop_name(page) != row['source']['visibleShopName']:
        fail('RECIPIENT_CHANGED', 'Visible source shop name changed.')
    from .shop_research import probe as shop_probe
    shop = shop_probe(page)
    keys = {r['shopIdentity']['key'] for r in shop['controls'] if r['action'] == 'open_shop'}
    if shop.get('identity'):
        keys.add(shop['identity']['key'])
    if keys != {row['source']['shop']['key']}:
        fail('RECIPIENT_CHANGED', 'Source merchant identity changed.')
    if row['source'].get('product'):
        current = page.evaluate(dom_script('productSnapshotDom.js'))
        old = row['source']['product']
        if current['selectedSku'] != old['selectedSku']:
            fail('PRODUCT_CHANGED', 'SKU changed after conversation was opened.')
        if product_identity(page.url)['productId'] != old['productId']:
            fail('PRODUCT_CHANGED', 'Product changed.')
    return page


FOLLOWUPS = {
    'tax_price': '这个价含税吗？开票还要另外加钱吗？',
    'total_shipping': '含运费一共多少钱？',
    'invoice_type': '可以开哪种发票？'}


def inquiry_target(inquiry, intent=None):
    context = inquiry['context']
    shop = inquiry['source']['shop']['key']
    if context.get('scope') == 'shop' or intent == 'invoice_shop':
        return digest({'shop': shop, 'scope': 'shop'})
    return digest({'shop': shop, 'scope': 'product', 'productId': context.get('productId'),
                   'selectedSku': context.get('selectedSku'), 'quantity': context.get('quantity', 1)})


def prior_questions(store, inquiry, question_ids, intent=None):
    """Use intent evidence, not model wording. Conservatively include uncertain sends."""
    from .merchant_wording import build_spec, INTENTS
    matches = []
    for attempt in store.db['outbox'].values():
        old = store.db['inquiries'].get(attempt['inquiryId'])
        if not old or old['source']['shop']['key'] != inquiry['source']['shop']['key']:
            continue
        draft = store.db['drafts'].get(attempt['draftId'], {})
        ids = draft.get('questionIds')
        target = inquiry_target(old, draft.get('intent'))
        if ids is None:
            # Historical fixed templates remain evidence; never rewrite old records.
            text = attempt['text']
            if text == build_spec('invoice_shop')['originalText']:
                ids = INTENTS['invoice_shop']
                target = digest({'shop': old['source']['shop']['key'], 'scope': 'shop'})
            elif draft.get('followup') in INTENTS:
                ids = INTENTS[draft['followup']]
            elif text == build_spec('invoice_product', quantity=old['context'].get('quantity', 1))['originalText']:
                ids = INTENTS['invoice_product']
            else:
                ids = []
        if target == inquiry_target(inquiry, intent) and set(ids).intersection(question_ids):
            matches.append(attempt)
    return matches


def wording_conversation_hash(raw):
    return digest([{k: m.get(k) for k in ('direction', 'text', 'withdrawn', 'contentUnavailable', 'images')} for m in raw['messages']])


def check_wording_basis(draft, raw):
    if draft.get('wordingConversationHash') and draft['wordingConversationHash'] != wording_conversation_hash(raw):
        fail('WORDING_CONVERSATION_CHANGED', 'Chat changed after wording was prepared. Read replies and prepare a new exact draft; nothing sent.')


def prepare(c, store):
    row, page, frame, raw, _ = resolve(c, store)
    if row.get('readOnly'):
        fail('CHAT_READ_ONLY', 'List-only conversation has no verified product/shop source. Rebind a known conversation or use a real source contact before preparing messages.')
    require_connection(c, page, row)
    scope = c.args.get('inquiryScope', 'product')
    if scope not in ('shop', 'product'):
        raise ValueError('inquiryScope must be shop or product.')
    initial_intent = c.args.get('inquiryIntent')
    if initial_intent and (scope != 'shop' or c.args.get('followup') or initial_intent not in ('tax_price', 'total_shipping')):
        raise ValueError('Initial fee inquiry requires shop scope and a supported fee intent.')
    source = copy.deepcopy(row['source'])
    if scope == 'shop':
        source['product'] = None
        source['allSkuSelected'] = True
    validate_source(c, {**row, 'source': source})
    if scope == 'product' and (not source.get('product') or not source['allSkuSelected']):
        fail('PRODUCT_CHANGED', 'Prepare an inquiry from an exact selected product SKU, not a shop-only context.')
    quantity = c.args.get('quantity', 1)
    if not isinstance(quantity, int) or isinstance(quantity, bool) or not 1 <= quantity <= 1000:
        raise ValueError('quantity must be an integer in 1..1000.')
    inquiry_style = c.args.get('inquiryStyle', 'short')
    if inquiry_style not in ('short', 'school_project'):
        raise ValueError('Unknown invoice inquiry style.')
    workflow_request = c.args.get('_workflowRequestId')
    if workflow_request:
        prior = [d for d in store.db['drafts'].values() if d.get('workflowRequestId') == workflow_request]
        if len(prior) > 1:
            fail('CHAT_AMBIGUOUS', 'Multiple workflow drafts; inspect without sending.')
        if prior:
            draft = prior[0]
            inquiry = store.get('inquiries', draft['inquiryId'])
            if draft['conversationId'] != row['conversationId'] or inquiry['context'].get('scope') != scope or inquiry['context']['quantity'] != quantity:
                fail('CHAT_SOURCE_CHANGED', 'Workflow draft context changed.')
            return {'inquiry': inquiry, 'draft': draft, 'sent': False, 'reused': True}
    followup = c.args.get('followup')
    if followup:
        inquiry = store.get('inquiries', c.args.get('inquiryId'))
        if inquiry['conversationId'] != row['conversationId'] or inquiry['status'] != 'active':
            fail('CHAT_SOURCE_CHANGED', 'Follow-up inquiry is not active in this conversation.')
        validate_source(c, {**row, 'source': inquiry['source']})
        if followup == 'product_context':
            if inquiry['context'].get('scope') == 'shop':
                fail('PRODUCT_CHANGED', 'Shop-only inquiry has no authorized exact SKU context.')
            identity = product_identity(inquiry['source']['url'])
            if identity['productId'] != inquiry['context']['productId']:
                fail('PRODUCT_CHANGED', 'Observed source link does not match inquiry product.')
            sku = '、'.join(inquiry['context']['selectedSku'])
            label = f'这款，{sku}。' if sku else '这款。'
            if inquiry['context']['quantity'] != 1:
                label += f"买{inquiry['context']['quantity']}件。"
            text = label + '\n' + identity['url']
        else:
            text = FOLLOWUPS.get(followup)
        if text is None:
            raise ValueError('Unknown followup template.')
    else:
        context = copy.deepcopy(source['product']) if scope == 'product' else {'scope': 'shop', 'shopKey': source['shop']['key']}
        context['quantity'] = quantity
        inquiry = {'inquiryId': uuid.uuid4().hex, 'conversationId': row['conversationId'], 'context': context,
                   'source': copy.deepcopy(source), 'createdAt': stamp(), 'expiresAt': time.time() + 86400, 'status': 'active'}
        # Exact product/SKU/quantity remain bound in context, not dumped into the
        # merchant message. Start naturally; ask missing details after a reply.
        quantity_text = f'买{quantity}件，' if quantity != 1 else ''
        if scope == 'shop' or inquiry_style == 'school_project':
            # Latest user wording: two casual questions only. Exact scope stays
            # bound in the inquiry; do not dump links/SKU/quantity into chat.
            text = '你好，你们家能开票吗？开票金额和实付金额一样吗？'
        else:
            text = f'你好，这款{quantity_text}能开票吗？开票一共多少钱？'
    wording = None
    if followup != 'product_context':
        from .merchant_wording import build_spec, rewrite
        intent = followup or initial_intent or ('invoice_shop' if scope == 'shop' or inquiry_style == 'school_project' else 'invoice_product')
        spec = build_spec(intent, c.args.get('questionIds'), inquiry['context']['quantity'])
        # school_project historically binds product context; retain its identity.
        previous = prior_questions(store, inquiry, spec['questionIds'], intent)
        if previous:
            fail('CHAT_QUESTION_ALREADY_ATTEMPTED', 'These questions were already attempted for this shop/scope. Read existing outbox; do not rephrase and resend.')
        timeout = 10
        if getattr(c, 'workflow_check', None):
            c.workflow_check()
            timeout = min(timeout, max(0, getattr(c, 'workflow_deadline', time.monotonic() + 10) - time.monotonic()))
        wording = rewrite(spec, row.get('messages', []), mode=c.args.get('wordingMode'), timeout=timeout,
                          answered=c.args.get('answeredQuestionIds'))
        if getattr(c, 'workflow_check', None):
            c.workflow_check()
        text = wording['text']
        # A model call may take seconds. Re-read original chat/source before freezing.
        fresh, _, _, fresh_raw, _ = resolve(c, store)
        validate_source(c, {**fresh, 'source': inquiry['source']})
        if 'elapsedMs' in wording and wording_conversation_hash(raw) != wording_conversation_hash(fresh_raw):
            fail('WORDING_CONVERSATION_CHANGED', 'New chat content arrived while rewriting; read it and select remaining questions.')
    draft = {'draftId': uuid.uuid4().hex, 'inquiryId': inquiry['inquiryId'], 'conversationId': row['conversationId'],
             'text': text, 'contextHash': digest(inquiry['context']), 'createdAt': stamp(), 'followup': followup, 'expiresAt': time.time() + 3600}
    if wording:
        draft.update(wording=wording, intent=wording['intent'], questionIds=wording['questionIds'], intentTarget=inquiry_target(inquiry, wording['intent']))
        if 'elapsedMs' in wording:
            draft['wordingConversationHash'] = wording_conversation_hash(fresh_raw)
    if workflow_request:
        draft['workflowRequestId'] = workflow_request
    draft['textHash'] = digest(text)
    store.db['inquiries'][inquiry['inquiryId']] = inquiry
    store.db['drafts'][draft['draftId']] = draft
    row['active'] = True
    row['protectUntil'] = time.time() + 86400
    store.save()
    return {'inquiry': inquiry, 'draft': draft, 'sent': False, 'authorization': 'Exact draft requires explicit user authorization, provisioned by local authorize script. No MCP approval boolean.'}


def authorize_drafts(c, draft_ids, user_reference, ttl=3600, wording_reviewed=False):
    """Local-only entry. Operator must have real user authorization for exact texts.

    No MCP registration; a model-supplied reference cannot prove human consent.
    """
    if not user_reference.strip() or not 60 <= ttl <= 3600 or not 1 <= len(set(draft_ids)) <= 3:
        raise ValueError('Need user authorization reference, 1..3 exact draft IDs and TTL 60..3600.')
    store = Store(c)
    for key in draft_ids:
        draft = store.get('drafts', key)
        if draft['expiresAt'] < time.time():
            fail('CHAT_AUTH_REQUIRED', 'Draft expired; prepare it again.')
        if draft.get('wording', {}).get('requiresAiReview') and not wording_reviewed:
            fail('WORDING_REVIEW_REQUIRED', 'Operator must inspect final wording for preserved meaning before exact-draft authorization. This is not new human consent.')
    token = uuid.uuid4().hex
    file = c.out / 'merchant-chat' / 'authorizations.json'
    db = load_json(file, {'endpoint': c.endpoint, 'grants': {}})
    if db['endpoint'] != c.endpoint:
        fail('CHAT_SESSION_CHANGED', 'Authorization endpoint changed.')
    db['grants'][token] = {'draftHashes': {d: digest(store.get('drafts', d)) for d in set(draft_ids)},
                           'expiresAt': time.time() + ttl, 'userReference': user_reference[:500], 'used': [],
                           'wordingReviewed': bool(wording_reviewed)}
    atomic_json(file, db)
    return {'authorizationId': token, 'draftIds': list(dict.fromkeys(draft_ids)), 'expiresAt': db['grants'][token]['expiresAt']}


def check_authorization(c, store, draft):
    file = c.out / 'merchant-chat' / 'authorizations.json'
    db = load_json(file, {})
    grant = db.get('grants', {}).get(c.args.get('authorizationId')) if db.get('endpoint') == c.endpoint else None
    if not grant or grant['expiresAt'] < time.time() or draft['expiresAt'] < time.time() or grant['draftHashes'].get(draft['draftId']) != digest(draft):
        fail('CHAT_AUTH_REQUIRED', 'No valid local authorization for this exact draft and context.')
    if draft['draftId'] in grant['used'] or any(x['draftId'] == draft['draftId'] for x in store.db['outbox'].values()):
        fail('CHAT_ALREADY_DISPATCHED', 'Draft already attempted; reconcile outbox, do not resend.')
    attempts = [x for x in store.db['outbox'].values() if x['inquiryId'] == draft['inquiryId']]
    if len(attempts) >= 3:
        fail('CHAT_SEND_LIMIT', 'Inquiry has reached the three-attempt limit.')
    if draft.get('questionIds') and prior_questions(store, store.get('inquiries', draft['inquiryId']), draft['questionIds'], draft.get('intent')):
        fail('CHAT_QUESTION_ALREADY_ATTEMPTED', 'Same questions already attempted under another draft/request. Read outbox; never resend.')
    return file, db, grant


def reconcile(row, attempt):
    known = next((m for m in row.get('messages', []) if m['evidenceId'] == attempt.get('evidenceId')), None)
    # Rendered message text collapses whitespace (including native editor newlines).
    # Only reconcile the unique later outgoing bubble; authorization and editor
    # preflight still compare the exact original draft, without normalization.
    rendered_text = lambda text: ' '.join(text.split())
    candidates = [known] if known else [m for m in row.get('messages', []) if m['sequence'] > attempt['beforeSequence'] and m['direction'] == 'outgoing' and rendered_text(m['text']) == rendered_text(attempt['text'])]
    if len(candidates) == 1:
        m = candidates[0]
        attempt.update(status='observed_outgoing', outgoingObserved=True, evidenceId=m['evidenceId'],
                       platformStatus=m['platformStatus'], deliveryStatus=m['deliveryStatus'], readStatus=m['readStatus'])
    else:
        attempt.update(status='sent_unconfirmed', outgoingObserved=False)
    return attempt


def send(c, store):
    request_id = c.args.get('requestId')
    if not isinstance(request_id, str) or not 1 <= len(request_id) <= 160:
        raise ValueError('requestId required, length 1..160.')
    prior = store.db['outbox'].get(request_id)
    if prior:
        if prior['draftId'] != c.args.get('draftId') or prior['conversationId'] != c.args.get('conversationId'):
            fail('CHAT_REQUEST_CONFLICT', 'requestId already belongs to a different draft/conversation.')
        # Offline replay avoids an accidental second click, even if the tab is gone.
        return {'replayed': True, 'attempt': prior, 'confirmed': prior['status'] == 'observed_outgoing', 'retryAllowed': False}
    row, page, frame, raw, _ = resolve(c, store)
    draft = store.get('drafts', c.args.get('draftId'))
    if row.get('readOnly'):
        fail('CHAT_READ_ONLY', 'No send authorization is inherited by a list-only conversation.')
    require_connection(c, page, row)
    inquiry = store.get('inquiries', draft['inquiryId'])
    if not row.get('active') or inquiry['status'] != 'active' or draft['conversationId'] != row['conversationId']:
        fail('CHAT_SOURCE_CHANGED', 'Draft/inquiry not active in this conversation.')
    if draft['contextHash'] != digest(inquiry['context']) or draft['textHash'] != digest(draft['text']):
        fail('CHAT_AUTH_REQUIRED', 'Draft content/context integrity changed.')
    source_row = {**row, 'source': inquiry['source']}
    validate_source(c, source_row)
    auth_file, auth_db, grant = check_authorization(c, store, draft)
    check_wording_basis(draft, raw)
    if not raw['field']:
        fail('CHAT_UNSUPPORTED', 'No unique editable input.')
    if raw['field']['value']:
        fail('DRAFT_CONFLICT', 'Existing input is preserved; no overwrite.')
    controls = [x for x in raw['controls'] if x['action'] == 'send']
    if len(controls) != 1:
        fail('CHAT_UNSUPPORTED', 'No unique actual send button.')
    c.focus.prepare_action(page)
    c.pause(page)
    ready = probe(frame)
    verify_recipient(row, ready)
    check_wording_basis(draft, ready)
    validate_source(c, source_row)
    c.guard(frame)
    c.focus.require(page)
    require_connection(c, page, row)
    if revision(ready) != revision(raw):
        fail('STALE_CONTROL', 'Conversation/input changed before composing.')
    # Write intent before touching the draft field: a crash cannot silently lose it.
    attempt = {'requestId': request_id, 'draftId': draft['draftId'], 'inquiryId': draft['inquiryId'], 'conversationId': row['conversationId'],
               'text': draft['text'], 'beforeSequence': len(row.get('messages', [])), 'createdAt': stamp(),
               'status': 'dispatching', 'dispatchAttempted': False, 'outgoingObserved': False,
               'platformStatus': None, 'deliveryStatus': 'unknown', 'readStatus': 'unknown'}
    store.db['outbox'][request_id] = attempt
    store.save()
    grant['used'].append(draft['draftId'])
    atomic_json(auth_file, auth_db)
    try:
        field = frame.locator(ready['field']['path'])
        field.fill(draft['text'], timeout=5000)
        current = probe(frame)
        verify_recipient(row, current)
        check_wording_basis(draft, current)
        validate_source(c, source_row)
        c.guard(frame)
        c.focus.require(page)
        require_connection(c, page, row)
        new_controls = [x for x in current['controls'] if x['action'] == 'send']
        if not current['field'] or current['field']['value'] != draft['text'] or current['field']['path'] != ready['field']['path'] or len(new_controls) != 1 or new_controls[0]['path'] != controls[0]['path']:
            fail('STALE_CONTROL', 'Composed text or send control changed; not clicked.')
        loc = frame.locator(new_controls[0]['path'])
        loc.click(trial=True, timeout=5000)
        final = probe(frame)
        verify_recipient(row, final)
        check_wording_basis(draft, final)
        validate_source(c, source_row)
        c.guard(frame)
        c.focus.require(page)
        require_connection(c, page, row)
        if revision(final) != revision(current):
            fail('STALE_CONTROL', 'State changed during native actionability check.')
        # Persist unknown outcome BEFORE click. Never repeat a timed-out native click.
        attempt['dispatchAttempted'] = True
        store.save()
        loc.click(timeout=5000)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            row, _, _, _, _ = resolve(c, store)
            reconcile(row, attempt)
            if attempt['outgoingObserved']:
                break
            page.wait_for_timeout(100)
        store.save()
    except Exception:
        attempt['status'] = 'sent_unconfirmed' if attempt['dispatchAttempted'] else 'explicit_failure'
        attempt['reason'] = 'Outcome uncertain; inspect original chat. No automatic retry.' if attempt['dispatchAttempted'] else 'No send click attempted; composed text may remain. Inspect before preparing another draft.'
        store.save()
        raise
    return {'confirmed': attempt['outgoingObserved'], 'attempt': attempt, 'retryAllowed': False, 'state': state(c, store),
            'note': 'Observed outgoing bubble is not proof of delivery, read receipt or final price.'}


def summary(c, store):
    inquiry = store.get('inquiries', c.args.get('inquiryId'))
    row = store.get('conversations', inquiry['conversationId'])
    facts = {m['evidenceId']: m for m in row.get('messages', [])}
    fields = c.args.get('terms')
    if fields is None:
        return {'inquiry': inquiry, 'messages': list(facts.values()), 'previousSummaries': inquiry.get('summaries', []),
                'nextAction': 'Current AI extracts terms, then calls with evidenceId and exact quote for every field. No automatic NLP or legal conclusion.'}
    allowed = {'canIssue', 'invoiceType', 'taxIncluded', 'extraFee', 'shipping', 'quotedTotal', 'conditions', 'issuer', 'issueTiming', 'applicationProcess'}
    if not isinstance(fields, dict) or set(fields) - allowed:
        raise ValueError('Unknown invoice term fields.')
    for name, item in fields.items():
        if not isinstance(item, dict) or set(item) - {'value', 'evidence', 'status'} or item.get('status') not in ('seller_confirmed', 'conditional', 'conflicting', 'unconfirmed'):
            raise ValueError('Each term needs value, status and evidence.')
        evidence = item.get('evidence') or []
        if item['status'] != 'unconfirmed' and not evidence:
            fail('CHAT_EVIDENCE_INVALID', 'Confirmed/conditional/conflicting terms require merchant evidence.')
        for ref in evidence:
            msg = facts.get(ref.get('evidenceId'))
            if not msg or msg['direction'] != 'incoming' or msg.get('withdrawn') or not ref.get('quote') or ref['quote'] not in (msg.get('text') or ''):
                fail('CHAT_EVIDENCE_INVALID', 'Evidence must quote an observed merchant message in this conversation.')
    calculation = None
    values = c.args.get('calculation')
    if values:
        try:
            if set(values) != {'base', 'extraFee', 'shipping', 'currency'} or values['currency'] != 'CNY':
                raise ValueError('Explicit CNY base, extraFee and shipping required.')
            nums = [Decimal(values[x]) for x in ('base', 'extraFee', 'shipping')]
            if any(not x.is_finite() or x < 0 for x in nums):
                raise ValueError('Amounts must be finite nonnegative decimal strings.')
            calculation = {'inputs': values, 'total': str(sum(nums)), 'scope': 'AI-supplied arithmetic only, not seller-confirmed or checkout total'}
        except (InvalidOperation, TypeError):
            raise ValueError('Amounts must be decimal strings.')
    result = {'summaryId': uuid.uuid4().hex, 'inquiryId': inquiry['inquiryId'], 'context': inquiry['context'], 'terms': fields,
              'calculation': calculation, 'createdAt': stamp(), 'interpretation': 'Current AI interpretation of seller claims; exact SKU/quantity association and legal/tax validity are not independently verified.'}
    candidate_id = c.args.get('candidateId')
    quoted_ids = {ref['evidenceId'] for term in fields.values() for ref in term.get('evidence', [])}
    result['evidenceMessages'] = [copy.deepcopy(facts[k]) for k in sorted(quoted_ids)]
    if candidate_id:
        file = c.out / 'research-candidates.json'
        db = load_json(file, {'candidates': {}})
        candidate = db['candidates'].get(candidate_id)
        context = inquiry['context']
        if context.get('scope') == 'shop' or not candidate or candidate['productId'] != context['productId'] or candidate['selectedSku'] != context['selectedSku']:
            fail('PRODUCT_CHANGED', 'Candidate product/SKU does not match inquiry.')
        candidate.setdefault('invoiceEvidence', []).append(result)
        atomic_json(file, db)
    inquiry.setdefault('summaries', []).append(result)
    store.save()
    return {'saved': True, 'summary': result}


def finish(c, store):
    inquiry = store.get('inquiries', c.args.get('inquiryId'))
    inquiry['status'] = 'cancelled' if c.args.get('cancel', False) else 'completed'
    cid = inquiry['conversationId']
    others = [i for i in store.db['inquiries'].values() if i['conversationId'] == cid and i['status'] == 'active']
    store.db['conversations'][cid]['active'] = bool(others)
    store.save()
    unresolved = any(a['conversationId'] == cid and a['status'] in ('dispatching', 'sent_unconfirmed') for a in store.db['outbox'].values())
    released = []
    # An explicitly finished inquiry must also release its workflow lease.
    # Keep pending-reply status and all evidence; uncertain sends stay protected.
    if not others and not unresolved:
        file = c.out / 'workflows.json'
        workflows = load_json(file, {})
        if workflows.get('endpoint') == c.endpoint:
            for wid, row in workflows.get('runs', {}).items():
                if row.get('inquiryId') == inquiry['inquiryId'] and row.get('conversationId') == cid and row.get('protectUntil', 0) > 0:
                    row['protectUntil'] = 0
                    row['protectionReleasedAt'] = time.time()
                    row['protectionReleaseReason'] = 'explicit-inquiry-finish'
                    released.append(wid)
            if released:
                atomic_json(file, workflows)
    return {'inquiryId': inquiry['inquiryId'], 'status': inquiry['status'], 'unresolvedSendsRemainProtected': unresolved, 'releasedWorkflowIds': released}


def finish_read(c, store):
    """End an explicitly reviewed read task; never relax inquiry or send protection."""
    row = store.get('conversations', c.args.get('conversationId'))
    reference = c.args.get('userReference')
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError('Explicit task completion reference required.')
    cid = row['conversationId']
    if any(i.get('conversationId') == cid and i.get('status') == 'active'
           for i in store.db['inquiries'].values()):
        fail('CHAT_INQUIRY_ACTIVE', 'Finish the active inquiry first; read completion cannot release it.')
    if any(a.get('conversationId') == cid and a.get('status') in ('dispatching', 'sent_unconfirmed')
           for a in store.db['outbox'].values()):
        fail('CHAT_SEND_UNCONFIRMED', 'Uncertain text send remains protected.')
    row.update(active=False, readFinishedAt=stamp(), readFinishReference=reference)
    store.save()
    return {'conversationId': cid, 'confirmed': True, 'confirmationScope': 'local read task ended only',
            'browserChanged': False, 'messageSent': False, 'evidencePreserved': True}


def cancel_contact(c, store):
    source_id, shop_key = c.args.get('sourceTabId'), c.args.get('shopKey')
    reference = c.args.get('userReference')
    pending = store.db.get('openAttempts', {}).get(source_id)
    if not reference or not pending or pending.get('status') == 'attached' or pending.get('source', {}).get('shop', {}).get('key') != shop_key:
        fail('CHAT_SOURCE_CHANGED', 'Cancellation requires an exact pending source/shop and explicit task reference.')
    for attempt in store.db.get('outbox', {}).values():
        conversation = store.db.get('conversations', {}).get(attempt['conversationId'], {})
        if conversation.get('source', {}).get('shop', {}).get('key') == shop_key and attempt.get('status') in ('dispatching', 'sent_unconfirmed'):
            fail('CHAT_SEND_UNCONFIRMED', 'Uncertain text send remains protected; contact cannot be reset.')
    archive_id = uuid.uuid4().hex
    store.db.setdefault('cancelledOpenAttempts', {})[archive_id] = {**copy.deepcopy(pending), 'cancelledAt': stamp(), 'userReference': reference}
    del store.db['openAttempts'][source_id]
    store.save()
    return {'cancelled': True, 'archiveId': archive_id, 'sourceTabId': source_id, 'browserChanged': False, 'textSendProtectionPreserved': True}


def run(c):
    store = Store(c)
    op = c.args['operation']
    if op == 'finish_merchant_read':
        return finish_read(c, store)
    if op == 'cancel_merchant_contact':
        return cancel_contact(c, store)
    if op == 'merchant_contact_options':
        return contact_options(c, store)
    if op == 'open_merchant_chat':
        return open_chat(c, store)
    if op == 'summarize_invoice_terms':
        return summary(c, store)
    if op == 'finish_merchant_inquiry':
        return finish(c, store)
    if op in ('merchant_chat_state', 'recover_merchant_chat'):
        # State refresh also reconciles a previous uncertain attempt without clicking.
        row, _, _, _, _ = resolve(c, store)
        for attempt in store.db['outbox'].values():
            if attempt['conversationId'] == row['conversationId'] and attempt['status'] in ('dispatching', 'sent_unconfirmed', 'observed_outgoing'):
                reconcile(row, attempt)
        store.save()
        result = state(c, store)
        result['outbox'] = [a for a in store.db['outbox'].values() if a['conversationId'] == row['conversationId']]
        if op == 'recover_merchant_chat':
            result.update(confirmed=result['connection']['status'] == 'no_disconnect_observed',
                          confirmationScope='Known disconnect dialog absent and original verified conversation readable; transport delivery unverified.',
                          messageResent=False)
        return result
    if op == 'prepare_invoice_inquiry':
        return prepare(c, store)
    if op == 'send_merchant_message':
        return send(c, store)
    if op == 'read_merchant_messages':
        return read_messages(c, store)
    if op == 'wait_merchant_reply':
        seconds = c.args.get('timeoutSeconds', 15)
        if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or not 0 <= seconds <= 30:
            raise ValueError('timeoutSeconds must be 0..30.')
        if not (c.args.get('afterCursor') or c.args.get('cursor')):
            fail('CHAT_CURSOR_INVALID', 'Read current messages first and pass afterCursor.')
        deadline = time.monotonic() + seconds
        previous_deadline = getattr(c, 'chat_wait_deadline', None)
        c.chat_wait_deadline = deadline
        try:
            while True:
                result = read_messages(c, store)
                if result['receivedNewMerchantMessage'] or result['connection']['status'] == 'disconnected' or time.monotonic() >= deadline:
                    result['pending'] = not result['receivedNewMerchantMessage']
                    return result
                _, page, _, _, _ = resolve(c, store)
                page.wait_for_timeout(min(250, max(1, int((deadline - time.monotonic()) * 1000))))
        finally:
            c.chat_wait_deadline = previous_deadline
    if op == 'load_merchant_history':
        row, page, frame, raw, _ = resolve(c, store)
        require_connection(c, page, row)
        control = row.get('controls', {}).get(c.args.get('controlId'))
        if not control or control['action'] != 'history' or row.get('revision') != revision(raw):
            fail('STALE_CONTROL', 'Use a freshly discovered history control.')
        c.focus.prepare_action(page)
        c.pause(page)
        c.guard(frame)
        c.focus.require(page)
        ready = probe(frame)
        verify_recipient(row, ready)
        if revision(ready) != revision(raw):
            fail('STALE_CONTROL', 'History control changed before click.')
        count = len(row.get('messages', []))
        loc = frame.locator(control['path'])
        loc.click(trial=True, timeout=5000)
        ready = probe(frame)
        verify_recipient(row, ready)
        c.guard(frame)
        c.focus.require(page)
        if revision(ready) != revision(raw):
            fail('STALE_CONTROL', 'History state changed during native preflight.')
        require_connection(c, page, row)
        loc.click(timeout=5000)
        page.wait_for_timeout(200)
        result = state(c, store)
        result.update(loadedCount=len(row['messages']) - count, confirmed=len(row['messages']) > count)
        return result
    if op == 'return_from_merchant_chat':
        row, page, frame, raw, _ = resolve(c, store)
        if row.get('readOnly'):
            fail('CHAT_NO_PRODUCT_SOURCE', 'List-only conversation has no original product/shop to return to. Use inbox switching.')
        if raw.get('field') and raw['field']['value']:
            fail('DRAFT_CONFLICT', 'Unsent draft remains; chat panel is preserved.')
        source = validate_source(c, row)
        if row.get('sameTabNavigation'):
            c.focus.prepare_action(page)
            c.focus.begin(page)
            # Back/forward-cache restoration may not emit DOMContentLoaded again.
            page.go_back(wait_until='commit', timeout=8000)
            page.wait_for_function("document.readyState==='interactive'||document.readyState==='complete'", timeout=8000)
            c.guard(page)
            c.focus.bind(page)
            if page.url != row['source']['url']:
                fail('CHAT_SOURCE_CHANGED', 'History did not restore the exact source.')
            validate_source(c, {**row, 'sameTabNavigation': False})
            return {'confirmed': True, 'sourceTabId': row['source']['tabId'], 'closedTab': False, 'contextEvidence': 'one-step verified history; source SKU checked after return'}
        if source is page:
            if not row.get('openedByTool'):
                fail('UNOWNED_PANEL', 'Chat panel was not opened by this tool.')
            controls = [x for x in raw['controls'] if x['action'] == 'close']
            if len(controls) != 1:
                fail('CHAT_UNSUPPORTED', 'No unique chat close control.')
            c.focus.prepare_action(page)
            c.pause(page)
            ready = probe(frame)
            verify_recipient(row, ready)
            if revision(ready) != revision(raw):
                fail('STALE_CONTROL', 'Chat changed before close.')
            c.guard(frame)
            c.focus.require(page)
            loc = frame.locator(controls[0]['path'])
            loc.click(trial=True, timeout=5000)
            final = probe(frame)
            verify_recipient(row, final)
            c.guard(frame)
            c.focus.require(page)
            if revision(final) != revision(raw):
                fail('STALE_CONTROL', 'Chat changed during close preflight.')
            loc.click(timeout=5000)
            closed = not probe(frame).get('supported')
            if closed:
                row['panelClosedByTool'] = True
                store.save()
            return {'confirmed': closed, 'sourceTabId': row['source']['tabId'], 'closedTab': False}
        c.focus.activate(source, restore_window=True)
        return {'confirmed': True, 'sourceTabId': row['source']['tabId'], 'closedTab': False}
    raise ValueError('Unknown merchant chat operation.')
