"""Native recent-contact list, scoped search and journaled in-tab conversation switching."""
import copy
import json
import random
import time
import uuid
from playwright.sync_api import Error as PlaywrightError

from .merchant_chat import (Store, probe, digest, fail, stamp, verify_recipient,
                            merge_messages, reconcile, state)

OPERATIONS = {'list_merchant_chats', 'search_merchant_chats', 'switch_merchant_chat', 'load_more_merchant_chats', 'cancel_merchant_chat_switch'}
TERMINAL_SWITCH = {'confirmed', 'cancelled'}
# These operations never create or close tabs; exempt them from unrelated tab cleanup.
READONLY = OPERATIONS


def snapshot(c):
    from .shopping_research import page_for, supported
    page = page_for(c)
    c.guard(page)
    c.focus.require(page)
    frames = []
    for frame in page.frames:
        if not supported(frame.url):
            continue
        if frame != page.main_frame and not frame.frame_element().is_visible():
            continue
        c.guard(frame)
        inbox = probe(frame, 'inbox')
        if inbox.get('supported'):
            frames.append((frame, inbox))
    if len(frames) != 1:
        fail('CHAT_LIST_UNSUPPORTED', 'No unique observed WangWang recent-contact list in the bound tab.')
    frame, inbox = frames[0]
    chat = probe(frame)
    if not chat.get('supported'):
        fail('CHAT_NOT_READY', 'Current chat header/editor is not recognized; preserve original tab.')
    return page, frame, inbox, chat


def require_online(page, frame):
    if any(probe(f, 'connection')['status'] == 'disconnected' for f in {page.main_frame, frame}):
        fail('CHAT_DISCONNECTED', 'Read/recover the original tracked conversation before changing the recent-contact list.')


def signature(inbox):
    return digest([inbox['rootPath'], inbox['search'], inbox['scroll']['path'],
                   [{k: e[k] for k in ('entryKey', 'label', 'path', 'selected')} for e in inbox['entries']]])


def filter_matches(inbox, keyword):
    if not keyword:
        return True
    if inbox['entries']:
        return all(keyword.casefold() in entry['label'].casefold() for entry in inbox['entries'])
    # Whole explicit empty-result text, never a merchant preview containing e.g. "没有".
    return (inbox.get('emptyText') or '').strip().rstrip('。') in {
        '暂无搜索结果', '暂无相关联系人', '暂无联系人', '未找到联系人',
        '未找到相关联系人', '没有找到相关联系人', '无搜索结果', '没有搜索结果'}


def candidates(store, entry):
    return [r for r in store.db['conversations'].values()
            if (r.get('inboxEntryKey') == entry['entryKey'] if r.get('inboxEntryKey') else
                not r.get('readOnly') and r.get('source', {}).get('visibleShopName') == entry['label'])]


def thread_signature(raw):
    # Header changes can alter author classification before old bubbles disappear.
    # Only body/time evidence proves the rendered message window changed.
    return digest([{k: m.get(k) for k in ('platformId', 'text', 'timeText', 'images', 'contentUnavailable')}
                   for m in raw['messages']])


def preserve_current(c, store, page, raw, inbox=None):
    ids = []
    for row in store.db['conversations'].values():
        if row['tabId'] != c.tab_id(page) or row['chatUrl'] != page.url or row.get('identity') != raw['identity']:
            continue
        if row.get('inboxEntryKey') and row['inboxEntryKey'] != raw.get('inboxEntryKey'):
            continue  # Filtered-out or different selected row; never merge based on a matching label alone.
        if not row.get('inboxEntryKey') and inbox and sum(e['label'] == raw['identity']['label'] for e in inbox['entries']) > 1:
            continue
        verify_recipient(row, raw)
        if raw.get('inboxEntryKey'):
            row['inboxEntryKey'] = raw['inboxEntryKey']
        merge_messages(row, raw)
        for attempt in store.db['outbox'].values():
            if attempt['conversationId'] == row['conversationId'] and attempt['status'] in ('dispatching', 'sent_unconfirmed', 'observed_outgoing'):
                reconcile(row, attempt)
        ids.append(row['conversationId'])
    store.save()
    return ids


def publish(c, store, page, frame, inbox, chat):
    active = preserve_current(c, store, page, chat, inbox)
    token = uuid.uuid4().hex
    refs = {f'inbox:{token}:{i}': e for i, e in enumerate(inbox['entries'])}
    saved = store.db.setdefault('inbox', {}).setdefault(c.tab_id(page), {})
    saved.update(url=page.url, frameUrl=frame.url, revision=signature(inbox), records=refs,
                 listId=token, scroll=inbox['scroll'])
    store.save()
    return {'tabId': c.tab_id(page), 'listId': token, 'currentRecipient': chat['identity'],
            'currentConversationIds': active, 'query': inbox['search']['value'],
            'entries': [{k: v for k, v in e.items() if k != 'path'} | {'controlId': ref,
                'knownConversations': [{'conversationId': r['conversationId'], 'readOnly': r.get('readOnly', False),
                    'productId': (r.get('source', {}).get('product') or {}).get('productId'),
                    'selectedSku': (r.get('source', {}).get('product') or {}).get('selectedSku'),
                    'sourceTabId': r.get('source', {}).get('tabId'),
                    'sourceAvailableRequiredForSend': not r.get('readOnly', False)} for r in candidates(store, e)]}
                for ref, e in refs.items()],
            'scroll': {k: v for k, v in inbox['scroll'].items() if k != 'path'},
            'coverage': inbox['coverage'], 'emptyText': inbox['emptyText'],
            'pendingSwitches': [{k: a.get(k) for k in ('requestId', 'targetLabel', 'status', 'actionAttempted', 'lastObservation')} | {'canCancel': True}
                for a in store.db.get('inboxSwitches', {}).values()
                if a['tabId'] == c.tab_id(page) and a.get('actionAttempted') and a['status'] not in TERMINAL_SWITCH],
            'readSideEffect': 'Opening a thread may mark platform messages read. No messages sent.'}


def pending(store, tab):
    return [a for a in store.db.get('inboxSwitches', {}).values()
            if a['tabId'] == tab and a.get('actionAttempted') and a['status'] not in TERMINAL_SWITCH]


def _entry_locator(frame, entry):
    """Anchor the native locator to actual stable row identity, never its virtualized position.

    Raw platform IDs contain account identifiers. Keep them transient here, without
    returning or persisting them. Click the observed content area, outside close/avatar.
    """
    rows = frame.locator('.ww_conversation_list .conversation-item')
    matches = []
    for index in range(rows.count()):
        platform_id = rows.nth(index).get_attribute('id', timeout=1500)
        if platform_id and digest(['ww-inbox-v1', platform_id]) == entry['entryKey']:
            anchored = frame.locator('.ww_conversation_list .conversation-item[id=' + json.dumps(platform_id) + ']')
            if anchored.count() != 1 or anchored.locator('.conversation .name').count() != 1:
                fail('CHAT_AMBIGUOUS', 'Observed stable contact identity is ambiguous.')
            if ' '.join(anchored.locator('.conversation .name').inner_text(timeout=1500).split()) != entry['label']:
                fail('STALE_CONTROL', 'Stable contact identity now has a different label.')
            content = anchored.locator(':scope > .content')
            if content.count() != 1:
                fail('CHAT_LIST_UNSUPPORTED', 'No unique observed contact content click area.')
            matches.append(content)
    if len(matches) != 1:
        fail('STALE_CONTROL', 'Contact identity is no longer rendered uniquely; rediscover the list.')
    return matches[0]


def entry_locator(frame, entry):
    try:
        return _entry_locator(frame, entry)
    except PlaywrightError:
        raise RuntimeError('CHAT_LIST_CONTROL_UNAVAILABLE: Contact changed during discovery; rediscover current list.') from None


def entry_click_options(locator):
    """Read a safe native point in the row content; avoid name handlers and controls."""
    try:
        point = locator.evaluate('''e=>{
          const r=e.getBoundingClientRect(),row=e.closest('.conversation-item'),points=[];
          for(const child of e.querySelectorAll('.desc,.conversation .time')){
            const b=child.getBoundingClientRect(),left=Math.max(r.left,b.left),right=Math.min(r.right,b.right),
              top=Math.max(r.top,b.top),bottom=Math.min(r.bottom,b.bottom);
            if(right-left>2&&bottom-top>2)points.push({x:(left+right)/2,y:(top+bottom)/2});
          }
          points.push({x:r.left+r.width*.8,y:r.top+r.height*.8});
          for(const p of points){const hit=document.elementFromPoint(p.x,p.y);
            if(hit&&e.contains(hit)&&hit.closest('.conversation-item')===row&&
              !hit.closest('a,button,input,textarea,[role="button"],[contenteditable="true"],.name,.content-close'))
              return {x:p.x-r.left,y:p.y-r.top};}
          return null;
        }''')
    except PlaywrightError:
        raise RuntimeError('CHAT_LIST_CONTROL_UNAVAILABLE: Contact content changed during native point discovery.') from None
    if point is None:
        fail('CHAT_LIST_CONTROL_NOT_ACTIONABLE', 'No observed noninteractive content point; rediscover/scroll the contact list.')
    return {'position': point}


def observation(attempt, raw):
    return {'currentLabel': raw['identity']['label'],
            'selectedEntryMatches': raw.get('inboxEntryKey') == attempt['entry']['entryKey'],
            'headerMatches': raw['identity']['label'] == attempt['targetLabel'],
            'bodyChanged': thread_signature(raw) != attempt['beforeMessageHash'],
            'messageCount': len(raw['messages']), 'observedAt': stamp()}


def cancel_switch(c, store):
    request = c.args.get('requestId')
    attempt = store.db.get('inboxSwitches', {}).get(request)
    if not attempt:
        fail('CHAT_NOT_FOUND', 'Unknown switch request.')
    page, frame, _, raw = snapshot(c)
    if attempt['tabId'] != c.tab_id(page):
        fail('CHAT_REQUEST_CONFLICT', 'Cancellation belongs to another original chat tab/frame.')
    if attempt['status'] == 'confirmed':
        return {'cancelled': False, 'confirmed': False, 'status': 'confirmed', 'requestId': request, 'clickAttemptedThisCall': False,
                'messageSent': False, 'note': 'Completed switch preserved; no navigation undone.'}
    replayed = attempt['status'] == 'cancelled'
    if not replayed:
        attempt['observationBeforeCancellation'] = copy.deepcopy(attempt.get('lastObservation'))
        attempt.update(status='cancelled', cancelledAt=stamp(), cancellationScope='local pending intent only; previous click outcome remains unverified',
                       cancellationContextChanged=attempt['url'] != page.url or attempt['frameUrl'] != frame.url,
                       lastObservation=observation(attempt, raw))
        store.save()
    remaining = pending(store, c.tab_id(page))
    return {'cancelled': True, 'confirmed': True, 'confirmationScope': 'local pending intent cancelled only',
            'switchConfirmed': False, 'status': 'cancelled', 'requestId': request,
            'replayed': replayed, 'localBlockReleased': not remaining, 'pendingRequestIdsRemaining': [a['requestId'] for a in remaining],
            'previousClickOutcome': 'unverified',
            'clickAttemptedThisCall': False, 'messageSent': False, 'diagnostics': attempt.get('lastObservation'),
            'nextAction': 'Old request is terminal and will never click again. Read a fresh list for any deliberate new selection; do not use cancellation as a retry loop.'}


def search(c, store):
    keyword = c.args.get('keyword')
    if not isinstance(keyword, str) or len(keyword) > 100 or any(ord(x) < 32 for x in keyword):
        raise ValueError('keyword must be a string of at most 100 characters, without control characters; empty clears search.')
    page, frame, inbox, raw = snapshot(c)
    require_online(page, frame)
    if pending(store, c.tab_id(page)):
        fail('CHAT_SWITCH_PENDING', 'Reconcile the saved switch request before changing the search.')
    saved = store.db.setdefault('inbox', {}).setdefault(c.tab_id(page), {})
    saved.update(url=page.url, frameUrl=frame.url)
    prior = saved.get('searchAttempt')
    replay = bool(prior and prior['keyword'] == keyword and inbox['search']['value'] == keyword)
    if not replay:
        if inbox['search']['disabled']:
            fail('CHAT_SEARCH_UNAVAILABLE', 'Observed contact search is disabled.')
        c.focus.prepare_action(page)
        c.pause(page)
        ready = snapshot(c)
        if ready[0] is not page or signature(ready[2]) != signature(inbox) or ready[3]['identity'] != raw['identity']:
            fail('STALE_CONTROL', 'List/search/current recipient changed before contact search.')
        require_online(page, frame)
        preserve_current(c, store, page, raw, inbox)
        saved['searchAttempt'] = {'keyword': keyword, 'startedAt': stamp(), 'enterAttempted': False}
        store.save()
        field = frame.locator(inbox['search']['path'])
        field.fill(keyword, timeout=5000)
        c.guard(frame); c.focus.require(page)
        current = probe(frame)
        if current['identity'] != raw['identity'] or field.input_value() != keyword:
            fail('RECIPIENT_CHANGED', 'Recipient or search input changed before submitting contact search.')
        saved['searchAttempt']['enterAttempted'] = True
        store.save()
        field.press('Enter', timeout=5000)  # Observed real search trigger, never the message editor.
    deadline = time.monotonic() + 3
    while True:
        current = snapshot(c)
        if current[0] is not page or current[3]['identity'] != raw['identity'] or page.url != saved.get('url', page.url):
            fail('RECIPIENT_CHANGED', 'Contact search changed the active recipient/page; no send.')
        data = current[2]
        filtered = filter_matches(data, keyword)
        confirmed = data['search']['value'] == keyword and bool(filtered)
        if confirmed or time.monotonic() >= deadline:
            result = publish(c, store, *current)
            result.update(confirmed=confirmed, replayed=replay, inputMatches=data['search']['value'] == keyword,
                          filteringVerified=bool(filtered), enterAttempted=bool(saved.get('searchAttempt', {}).get('enterAttempted')))
            return result
        page.wait_for_timeout(150)


def bind_target(c, store, attempt, page, frame, inbox, raw):
    target = attempt['entry']
    requested = attempt.get('targetConversationId')
    choices = candidates(store, target)
    if requested:
        row = store.get('conversations', requested)
        if row not in choices:
            fail('RECIPIENT_UNVERIFIED', 'Requested saved conversation does not match selected list identity/name.')
        if not row.get('inboxEntryKey') and sum(e['label'] == target['label'] for e in inbox['entries']) != 1:
            fail('CHAT_AMBIGUOUS', 'Duplicate shop labels cannot bind an unanchored send-capable conversation.')
    elif len(choices) == 1 and sum(e['label'] == target['label'] for e in inbox['entries']) == 1:
        row = choices[0]
    else:
        readonly = [r for r in choices if r.get('readOnly') and r.get('inboxEntryKey') == target['entryKey']]
        if len(readonly) > 1:
            fail('CHAT_AMBIGUOUS', 'Multiple saved list-only views; choose targetConversationId explicitly.')
        row = readonly[0] if readonly else None
    if row is None:
        row = {'conversationId': uuid.uuid4().hex, 'readOnly': True, 'openedByTool': False,
               'source': {'tabId': c.tab_id(page), 'url': page.url, 'kind': 'chat-list-only',
                          'shop': {'key': 'chat-list-entry:' + target['entryKey'], 'shopId': None},
                          'visibleShopName': target['label'], 'product': None, 'allSkuSelected': False},
               'identity': raw['identity'], 'receiverId': None, 'sameTabNavigation': False}
    staged = copy.deepcopy(row)
    staged.update(tabId=c.tab_id(page), chatUrl=page.url, frameUrl=frame.url, inboxEntryKey=target['entryKey'],
                  active=True, protectUntil=time.time() + 86400, boundFromInboxAt=stamp())
    if row.get('tabId') != c.tab_id(page):
        staged['sameTabNavigation'] = False
    verify_recipient(staged, raw)
    merge_messages(staged, raw)
    store.db['conversations'][staged['conversationId']] = staged
    for outgoing in store.db['outbox'].values():
        if outgoing['conversationId'] == staged['conversationId'] and outgoing['status'] in ('dispatching', 'sent_unconfirmed', 'observed_outgoing'):
            reconcile(staged, outgoing)
    attempt.update(status='confirmed', conversationId=staged['conversationId'], confirmedAt=stamp())
    store.save()
    return staged


def switch(c, store):
    request = c.args.get('requestId')
    if not isinstance(request, str) or not 1 <= len(request) <= 120:
        raise ValueError('A stable requestId (1..120 characters) is required.')
    page, frame, inbox, raw = snapshot(c)
    attempts = store.db.setdefault('inboxSwitches', {})
    attempt = attempts.get(request)
    replay = attempt is not None
    if replay:
        if (attempt['tabId'] != c.tab_id(page) or attempt['url'] != page.url or attempt['frameUrl'] != frame.url or
            c.args.get('targetConversationId') is not None and c.args['targetConversationId'] != attempt.get('targetConversationId') or
            c.args.get('controlId') and c.args['controlId'] != attempt['controlId']):
            fail('CHAT_REQUEST_CONFLICT', 'Switch request belongs to a different tab/entry/conversation.')
        if attempt['status'] == 'cancelled':
            return {'confirmed': False, 'replayed': True, 'status': 'cancelled', 'requestId': request,
                    'clickAttemptedThisCall': False, 'messageSent': False,
                    'nextAction': 'This pending intent was cancelled; old request never clicks again. Read fresh list for a deliberate new selection.'}
        if attempt['status'] == 'confirmed' and (raw.get('inboxEntryKey') != attempt['entry']['entryKey'] or raw['identity']['label'] != attempt['targetLabel']):
            return {'confirmed': False, 'replayed': True, 'status': 'selection_changed', 'messageSent': False,
                    'clickAttemptedThisCall': False,
                    'nextAction': 'Selection changed since this completed request. Read list and use a new requestId; old request never clicks again.'}
    else:
        require_online(page, frame)
        if pending(store, c.tab_id(page)):
            fail('CHAT_SWITCH_PENDING', 'An earlier attempted switch is unresolved; resume that request, never click again.')
        saved = store.db.get('inbox', {}).get(c.tab_id(page), {})
        entry = saved.get('records', {}).get(c.args.get('controlId'))
        if not entry or saved.get('url') != page.url or saved.get('frameUrl') != frame.url or saved.get('revision') != signature(inbox):
            fail('STALE_CONTROL', 'Read list_merchant_chats/search results and use their current controlId.')
        if not raw.get('field') or raw['field']['value']:
            fail('DRAFT_CONFLICT', 'Unsent/ambiguous editor preserved; no conversation switch.')
        if c.args.get('targetConversationId') and store.get('conversations', c.args['targetConversationId']) not in candidates(store, entry):
            fail('RECIPIENT_UNVERIFIED', 'Saved conversation does not match the selected entry.')
        if c.args.get('targetConversationId') and not store.get('conversations', c.args['targetConversationId']).get('inboxEntryKey') and sum(e['label'] == entry['label'] for e in inbox['entries']) > 1:
            fail('CHAT_AMBIGUOUS', 'Duplicate shop labels cannot bind a saved source without its list identity.')
        preserve_current(c, store, page, raw, inbox)
        c.focus.prepare_action(page)
        c.pause(page)
        loc = entry_locator(frame, entry)
        try:
            loc.scroll_into_view_if_needed(timeout=5000)
            loc.click(trial=True, timeout=5000, **entry_click_options(loc))
        except PlaywrightError:
            raise RuntimeError('CHAT_LIST_CONTROL_NOT_ACTIONABLE: Native contact preflight failed; no selection click dispatched.') from None
        ready = snapshot(c)
        require_online(page, frame)
        same_target = [e for e in ready[2]['entries'] if e['entryKey'] == entry['entryKey'] and e['label'] == entry['label']]
        if len(same_target) != 1 or ready[2]['search'] != inbox['search'] or ready[3]['identity'] != raw['identity'] or ready[3].get('inboxEntryKey') != raw.get('inboxEntryKey'):
            fail('STALE_CONTROL', 'Virtualized list or current recipient changed during native preflight.')
        if not ready[3].get('field') or ready[3]['field']['value']:
            fail('DRAFT_CONFLICT', 'Input changed during switch preflight; preserved.')
        click_options = entry_click_options(loc)
        c.focus.require(page)
        already = raw.get('inboxEntryKey') == entry['entryKey'] and raw['identity']['label'] == entry['label']
        attempt = {'requestId': request, 'tabId': c.tab_id(page), 'url': page.url, 'frameUrl': frame.url,
                   'controlId': c.args['controlId'], 'targetConversationId': c.args.get('targetConversationId'),
                   'targetLabel': entry['label'], 'entry': entry, 'beforeMessageHash': thread_signature(raw),
                   'beforeEntryKey': raw.get('inboxEntryKey'), 'beforeLabel': raw['identity']['label'],
                   'locatorKind': 'stable-row-id/content',
                   'alreadySelected': already, 'actionAttempted': not already, 'status': 'dispatching', 'createdAt': stamp()}
        attempts[request] = attempt
        store.save()  # A crash here must not cause a second native click.
        if not already:
            try:
                loc.click(timeout=5000, **click_options)
                attempt['nativeClickCompleted'] = True
            except PlaywrightError:
                attempt.update(nativeClickCompleted=False, clickError='native-click-outcome-unverified')
            store.save()
    deadline = time.monotonic() + 6
    stable, count = None, 0
    while True:
        page_now, frame_now, inbox_now, raw_now = snapshot(c)
        if page_now is not page or page.url != attempt['url'] or frame_now.url != attempt['frameUrl']:
            fail('CHAT_SOURCE_CHANGED', 'Chat page/frame changed after list selection; no URL reopened.')
        require_online(page, frame_now)
        selected = raw_now.get('inboxEntryKey') == attempt['entry']['entryKey'] and raw_now['identity']['label'] == attempt['targetLabel']
        messages = thread_signature(raw_now)
        readable = attempt['alreadySelected'] or not raw_now['messages'] or messages != attempt['beforeMessageHash']
        attempt['lastObservation'] = observation(attempt, raw_now)
        if selected and readable:
            observed = digest([raw_now['identity'], messages])
            count = count + 1 if observed == stable else 1
            stable = observed
            if count >= 3 or attempt['alreadySelected'] or attempt['status'] == 'confirmed':
                row = bind_target(c, store, attempt, page, frame_now, inbox_now, raw_now)
                original = c.args
                try:
                    c.args = {**original, 'conversationId': row['conversationId']}
                    result = state(c, store)
                finally:
                    c.args = original
                return {'confirmed': True, 'replayed': replay, 'clickAttempted': attempt['actionAttempted'],
                        'clickAttemptedThisCall': not replay and attempt['actionAttempted'],
                        'messageSent': False, 'state': result, 'inbox': publish(c, store, page, frame_now, inbox_now, raw_now)}
        else:
            stable, count = None, 0
        if time.monotonic() >= deadline:
            attempt['status'] = 'waiting_thread'
            store.save()
            return {'confirmed': False, 'replayed': replay, 'clickAttempted': attempt['actionAttempted'],
                    'clickAttemptedThisCall': not replay and attempt['actionAttempted'],
                    'requestId': request, 'status': 'waiting_thread', 'messageSent': False,
                    'diagnostics': attempt['lastObservation'], 'canCancel': True,
                    'nextAction': 'Read diagnostics. Same request only reads. To abandon this unverified intent, call cancel_merchant_chat_switch(requestId), then rediscover controls for a deliberate new selection; never repeatedly cancel/reclick.'}
        page.wait_for_timeout(150)


def load_more(c, store):
    page, frame, inbox, raw = snapshot(c)
    require_online(page, frame)
    saved = store.db.get('inbox', {}).get(c.tab_id(page), {})
    if c.args.get('listId') != saved.get('listId') or saved.get('revision') != signature(inbox):
        fail('STALE_CONTROL', 'Use the current recent-contact listId before scrolling.')
    if pending(store, c.tab_id(page)):
        fail('CHAT_SWITCH_PENDING', 'Reconcile the saved selection before scrolling its virtualized list.')
    if inbox['scroll']['atBottom']:
        return {**publish(c, store, page, frame, inbox, raw), 'scrolled': False, 'reachedBottom': True, 'newEntryCount': 0}
    c.focus.prepare_action(page); c.pause(page)
    ready = snapshot(c)
    if signature(ready[2]) != signature(inbox) or ready[3]['identity'] != raw['identity']:
        fail('STALE_CONTROL', 'Contact list changed before scroll.')
    region = frame.locator(inbox['scroll']['path'])
    region.hover(timeout=5000)
    pixels = round(inbox['scroll']['height'] * random.uniform(.5, 2.5))
    page.mouse.wheel(0, pixels)
    page.wait_for_timeout(random.randint(350, 650))
    current = snapshot(c)
    if current[3]['identity'] != raw['identity']:
        fail('RECIPIENT_CHANGED', 'Current thread changed during list-only scroll.')
    bottom = current[2]['scroll']['atBottom']
    if bottom:
        page.mouse.wheel(0, -round(inbox['scroll']['height'] * .15))
        page.wait_for_timeout(150)
        current = snapshot(c)
    new = {e['entryKey'] for e in current[2]['entries']} - {e['entryKey'] for e in inbox['entries']}
    return {**publish(c, store, *current), 'scrolled': True, 'scrollPixels': pixels,
            'reachedBottom': bottom, 'newEntryCount': len(new)}


def run(c):
    store = Store(c)
    operation = c.args['operation']
    if operation == 'list_merchant_chats':
        return publish(c, store, *snapshot(c))
    if operation == 'search_merchant_chats':
        return search(c, store)
    if operation == 'switch_merchant_chat':
        return switch(c, store)
    if operation == 'load_more_merchant_chats':
        return load_more(c, store)
    if operation == 'cancel_merchant_chat_switch':
        return cancel_switch(c, store)
    raise ValueError('Unknown merchant inbox operation.')
