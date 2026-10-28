"""Bounded semantic workflows. Persist before side effects; never replay a send/click."""
import copy
import time
from urllib.parse import parse_qs, urlparse

from .huoyan_browser import atomic_json, load_json, stamp
from .merchant_chat import Store, digest, prior_questions

OPERATIONS = {'search_and_read', 'ask_shop_invoice', 'workflow_status'}
QUESTION = '你好，你们家能开票吗？开票金额和实付金额一样吗？'


def status(c):
    db = load_json(c.out / 'workflows.json', {'endpoint': c.endpoint, 'runs': {}})
    if db['endpoint'] != c.endpoint:
        raise RuntimeError('WORKFLOW_SESSION_CHANGED: endpoint changed.')
    row = db['runs'].get(c.args.get('requestId'))
    if not row:
        raise ValueError('Unknown workflow requestId.')
    return {'workflow': copy.deepcopy(row), 'stateDir': str(c.out), 'confirmed': row['status'] == 'completed'}


def run(c):
    from . import shopping_research as research
    if c.args['operation'] == 'workflow_status':
        return status(c)
    original = dict(c.args)
    operation = original['operation']
    request = original.get('requestId')
    if not isinstance(request, str) or not 1 <= len(request) <= 120:
        raise ValueError('Workflow requestId required, length 1..120.')
    seconds = original.get('timeBudgetSeconds', 60)
    max_steps = original.get('maxSteps', 12)
    if isinstance(seconds, bool) or not isinstance(seconds, (float, int)) or not 1 <= seconds <= 120:
        raise ValueError('timeBudgetSeconds must be 1..120.')
    if isinstance(max_steps, bool) or not isinstance(max_steps, int) or not 1 <= max_steps <= 20:
        raise ValueError('maxSteps must be 1..20.')
    wait = original.get('waitSeconds', 0)
    if not isinstance(wait, (int, float)) or isinstance(wait, bool) or not 0 <= wait <= 30:
        raise ValueError('waitSeconds must be 0..30.')
    if not original.get('tabId'):
        raise ValueError('Workflow requires an explicitly selected existing tabId.')
    if operation == 'search_and_read' and (not isinstance(original.get('keyword'), str) or not original['keyword'].strip()):
        raise ValueError('Nonempty search keyword required.')
    file = c.out / 'workflows.json'
    db = load_json(file, {'endpoint': c.endpoint, 'runs': {}})
    if db['endpoint'] != c.endpoint:
        raise RuntimeError('WORKFLOW_SESSION_CHANGED: endpoint changed.')
    parameters = {k: original.get(k) for k in ('operation', 'tabId', 'keyword', 'scope', 'shopKey', 'questionIds', 'answeredQuestionIds')}
    # Keep old workflow signatures valid when no new question selector is supplied.
    parameters = {k: v for k, v in parameters.items() if k not in ('questionIds', 'answeredQuestionIds') or v is not None}
    parameters['scope'] = original.get('scope', 'global')
    signature = digest(parameters)
    row = db['runs'].get(request)
    if row and row['signature'] != signature:
        raise RuntimeError('WORKFLOW_REQUEST_CONFLICT: requestId belongs to different inputs.')
    if not row:
        row = {'requestId': request, 'signature': signature, 'parameters': parameters, 'status': 'running',
               'steps': [], 'createdAt': stamp(), 'progress': {}, 'sourceTabId': original['tabId'], 'protectUntil': time.time() + 86400}
        db['runs'][request] = row
    deadline = time.monotonic() + seconds
    count = 0

    def save(**values):
        row.update(values, updatedAt=stamp())
        atomic_json(file, db)

    def check():
        if time.monotonic() >= deadline:
            raise RuntimeError('WORKFLOW_TIME_LIMIT: checkpoint saved; inspect/resume same requestId.')

    def step(name, fn):
        nonlocal count
        check()
        if count >= max_steps:
            raise RuntimeError('WORKFLOW_STEP_LIMIT: checkpoint saved; resume same requestId.')
        count += 1
        save(currentStep=name, status='running')
        value = fn()
        if name not in row['steps']:
            row['steps'].append(name)
        save()
        return value

    def call(op, **kwargs):
        c.args = {**original, 'operation': op, **kwargs}
        c.args.pop('controlId', None)
        if 'controlId' in kwargs:
            c.args['controlId'] = kwargs['controlId']
        return research._run(c)

    def bind(tab):
        page = next((p for p in c.pages if c.tab_id(p) == tab), None)
        if page is None:
            raise RuntimeError('WORKFLOW_TAB_CLOSED: existing tab was closed; no URL reopened.')
        c.guard(page)
        c.focus.activate(page, background=True, restore_window=True)
        c.args['tabId'] = tab
        return page

    c.workflow_check = check
    c.workflow_deadline = deadline
    c.workflow_checkpoint = lambda progress: save(progress=copy.deepcopy(progress))
    had_attempt = bool(row.get('attempt'))
    if row.get('error'):
        row.setdefault('previousErrors', []).append({'error': row['error'], 'at': row.get('updatedAt')})
        row['error'] = None
    save()
    try:
        if row['status'] == 'completed' and operation == 'search_and_read':
            return {'confirmed': True, 'replayed': True, 'workflow': copy.deepcopy(row), 'stateDir': str(c.out), 'cached': True}
        page = step('bind_source' if operation == 'search_and_read' or not row.get('conversationId') else 'bind_chat',
                    lambda: bind(row.get('chatTabId') or row['sourceTabId']))
        if operation == 'search_and_read':
            c.args = dict(original)
            if row.get('searchStarted'):
                # Even if the process died immediately before native click, do not
                # guess whether it ran. Read the existing page, never submit again.
                current = step('reconcile_search', lambda: research.read(c, page))
                committed = parse_qs(urlparse(current['url']).query).get('q', [None])[0]
                shop_evidence = (current.get('shopDom', {}).get('queryEvidence') or {}).get('value')
                correct = committed == original['keyword'] if parameters['scope'] == 'global' else shop_evidence == original['keyword']
                confirmed = bool(row['progress'].get('clickAttempted') and correct and current['query'] == original['keyword'] and (current['products'] or current['noResults']))
                result = {'confirmed': confirmed, 'state': research.publish(c, current), 'reconciledWithoutClick': True}
            else:
                c.search_progress = {'inputChanged': False, 'clickAttempted': False, 'outcomeUnknown': False}
                def search():
                    save(searchStarted=True)
                    return call('search_products')
                result = step('search', search)
            save(result=result, status='completed' if result['confirmed'] else 'needs_review',
                 nextAction='AI selects a product from verified results.' if result['confirmed'] else 'Read current state; this request never submits search again.')
        else:
            c.args = {**original, 'tabId': row['sourceTabId']}
            if not row.get('shopKey'):
                options = step('discover_contact', lambda: call('merchant_contact_options', tabId=row['sourceTabId']))
                key = options['source']['shop']['key']
                if original.get('shopKey') and original['shopKey'] != key:
                    raise RuntimeError('RECIPIENT_CHANGED: requested shop does not match actual source.')
                save(shopKey=key)
            if not row.get('draftId'):
                # Deduplicate shop capability question across workflows and legacy
                # conversations, not just within a single caller requestId.
                store = Store(c)
                from .merchant_wording import build_spec
                questions = build_spec('invoice_shop', original.get('questionIds'))['questionIds']
                previous = prior_questions(store, {'source': {'shop': {'key': row['shopKey']}},
                                           'context': {'scope': 'shop'}}, questions)
                if previous:
                    save(status='already_asked', previousAttempts=copy.deepcopy(previous), nextAction='Read the recorded conversation; do not ask this shop again.')
                    return {'confirmed': False, 'workflow': copy.deepcopy(row), 'stateDir': str(c.out)}
            if not row.get('conversationId'):
                # Always discover a fresh contact ID. open_chat resumes its saved
                # pending popup without a second native contact click.
                options = step('discover_contact', lambda: call('merchant_contact_options', tabId=row['sourceTabId']))
                if options['source']['shop']['key'] != row['shopKey']:
                    raise RuntimeError('RECIPIENT_CHANGED: source shop changed during workflow.')
                entries = options['contacts']
                if len(entries) != 1:
                    raise RuntimeError('CHAT_AMBIGUOUS: AI must choose among actual contact entries.')
                result = step('open_chat', lambda: call('open_merchant_chat', tabId=row['sourceTabId'], controlId=entries[0]['controlId'], chatReadyTimeoutSeconds=min(8, max(0, deadline-time.monotonic()))))
                save(conversationId=result['state']['conversationId'], chatTabId=result['state']['tabId'])
            cid = row['conversationId']
            if not row.get('draftId'):
                result = step('prepare_draft', lambda: call('prepare_invoice_inquiry', tabId=row['chatTabId'], conversationId=cid,
                              inquiryScope='shop', inquiryStyle='school_project', _workflowRequestId=request))
                save(draftId=result['draft']['draftId'], inquiryId=result['inquiry']['inquiryId'], draft=result['draft']['text'],
                     wording=result['draft'].get('wording'))
            # Search outbox BEFORE considering authorization or sending. This
            # survives a crash after native dispatch but before workflow save.
            attempts = [a for a in Store(c).db['outbox'].values() if a['draftId'] == row['draftId']]
            if not attempts and not original.get('authorizationId'):
                save(status='awaiting_authorization', nextAction='AI compares wording with originalText/questionIds first; if requiresAiReview, operator uses --wording-reviewed. Authorize exact final draft from existing human consent, then resume same requestId with authorizationId.')
                return {'confirmed': False, 'workflow': copy.deepcopy(row), 'stateDir': str(c.out)}
            if not attempts:
                ready = step('check_chat_connection', lambda: call('merchant_chat_state', tabId=row['chatTabId'], conversationId=cid))
                if ready.get('connection', {}).get('status') == 'disconnected':
                    save(status='waiting_connection', result=ready,
                         nextAction='One original-chat recovery was blocked or insufficient; preserve existing draft/request and read original chat later.')
                    return {'confirmed': False, 'workflow': copy.deepcopy(row), 'stateDir': str(c.out)}
                step('send_once', lambda: call('send_merchant_message', tabId=row['chatTabId'], conversationId=cid, draftId=row['draftId'],
                     authorizationId=original['authorizationId'], requestId='workflow:' + request))
            result = step('read_conversation', lambda: call('merchant_chat_state', tabId=row['chatTabId'], conversationId=cid))
            attempts = [a for a in result['outbox'] if a['draftId'] == row['draftId']]
            save(attempt=attempts[0] if attempts else None, result=result)
            if result.get('connection', {}).get('status') == 'disconnected':
                save(status='waiting_connection', nextAction='One original-chat recovery was blocked or insufficient. Preserve draft/request/outbox; inspect original chat, never resend.')
                return {'confirmed': False, 'workflow': copy.deepcopy(row), 'stateDir': str(c.out)}
            if not attempts or not attempts[0]['outgoingObserved']:
                save(status='send_unconfirmed', nextAction='Only read original conversation; never resend.')
            else:
                incoming = [m for m in result['messages'] if m['direction'] == 'incoming' and m['sequence'] > attempts[0]['beforeSequence']]
                if not incoming and wait:
                    reply = step('wait_reply', lambda: call('wait_merchant_reply', tabId=row['chatTabId'], conversationId=cid,
                                 afterCursor=result['cursor'], timeoutSeconds=min(wait, max(0, deadline-time.monotonic()))))
                    if reply.get('connection', {}).get('status') == 'disconnected':
                        save(status='waiting_connection', result=reply, nextAction='Original chat recovery blocked; preserve request/outbox and read later, never resend.')
                        return {'confirmed': False, 'workflow': copy.deepcopy(row), 'stateDir': str(c.out)}
                    incoming = [m for m in reply['messages'] if m['direction'] == 'incoming']
                save(status='completed' if incoming else 'waiting_reply', merchantMessages=incoming,
                     nextAction='AI interprets exact merchant text; shop capability is not SKU price confirmation.' if incoming else 'Proceed to next shop; resume this request later for replies. No background listener.')
    except Exception as error:
        code = str(error).split(':', 1)[0]
        save(status='paused' if code in ('WORKFLOW_TIME_LIMIT', 'WORKFLOW_STEP_LIMIT') else 'waiting_connection' if code in ('CHAT_DISCONNECTED', 'CHAT_RECOVERY_NOT_READY', 'CHAT_RECOVERY_BUDGET') else 'waiting_page' if code == 'CHAT_NOT_READY' else 'needs_review',
             error=str(error), progress=copy.deepcopy(getattr(c, 'search_progress', row.get('progress', {}))),
             nextAction='Inspect saved progress. Resume same requestId; dispatched search/messages are never repeated.')
    finally:
        c.args = original
        c.workflow_check = None
        c.workflow_deadline = None
        c.workflow_checkpoint = None
    return {'confirmed': row['status'] == 'completed', 'workflow': copy.deepcopy(row), 'stateDir': str(c.out),
            'replayed': had_attempt, 'cached': False}
