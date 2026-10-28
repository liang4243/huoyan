// HUOYAN_DOM_BEGIN
function readMerchantChat(arg = {}) {
  const text = e => (e?.innerText || e?.getAttribute('aria-label') || e?.title || '').replace(/\s+/g, ' ').trim();
  const visible = e => { if (!e || e.closest('[hidden],[inert]')) return false; const r = e.getBoundingClientRect(), s = getComputedStyle(e); return r.width > 1 && r.height > 1 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const path = e => { const a = []; for (; e?.nodeType === 1; e = e.parentElement) { if (e === document.documentElement) { a.unshift('html'); break; } a.unshift(e.tagName.toLowerCase() + ':nth-child(' + ([...e.parentElement.children].indexOf(e) + 1) + ')'); } return a.join(' > '); };
  const control = (e, action) => ({ action, label: text(e), path: path(e), href: e.tagName === 'A' ? e.href : null, target: e.getAttribute('target'), disabled: !!e.disabled || e.getAttribute('aria-disabled') === 'true' });
  if (arg.mode === 'inbox') {
    if (location.hostname !== 'market.m.taobao.com' || location.pathname !== '/app/im/chat-core/index.html') return { supported: false };
    const roots = [...document.querySelectorAll('.ww_conversation')].filter(visible);
    if (roots.length !== 1) return { supported: false };
    const root = roots[0], lists = [...root.querySelectorAll('.ww_conversation_list')].filter(visible);
    const inputs = [...root.querySelectorAll('.ww_search input[placeholder="搜索最近联系人"]')].filter(visible);
    if (lists.length !== 1 || inputs.length !== 1) return { supported: false };
    const list = lists[0];
    const entries = [...list.querySelectorAll('.conversation-item')].filter(visible).filter(e => e.id)
      .map(e => { const name = e.querySelector('.conversation .name'), badge = e.querySelector('.unread-badge');
        const nr = name?.getBoundingClientRect(), er = e.getBoundingClientRect(), lr = list.getBoundingClientRect();
        return { platformId: e.id, label: text(name), selected: e.classList.contains('active'),
          preview: text(e.querySelector('.desc')).slice(0, 500), timeText: text(e.querySelector('.time')) || null,
          unreadCount: badge ? (/^\d+$/.test(text(badge)) ? Number(text(badge)) : null) : 0,
          unreadText: badge ? text(badge) : null, path: path(name),
          labelMayBeTruncated: !!name && (name.scrollWidth > name.clientWidth + 1 || !nr),
          inViewport: er.bottom > lr.top && er.top < lr.bottom };
      }).filter(e => e.label && e.path);
    const scrolls = [...list.querySelectorAll('div')].filter(visible).filter(e => !e.closest('.resize-triggers') && /auto|scroll/.test(getComputedStyle(e).overflowY));
    const scroll = scrolls.find(e => e.scrollHeight > e.clientHeight + 1) || scrolls[0] || list;
    return { supported: true, adapter: 'taobao-ww-inbox-v1', rootPath: path(root), entries,
      search: { path: path(inputs[0]), value: inputs[0].value, disabled: inputs[0].disabled || inputs[0].readOnly, trigger: 'Enter' },
      scroll: { path: path(scroll), top: scroll.scrollTop, height: scroll.clientHeight, total: scroll.scrollHeight,
        atBottom: scroll.scrollTop + scroll.clientHeight >= scroll.scrollHeight - 2 },
      emptyText: !entries.length ? text(list).slice(0, 300) : null,
      coverage: 'rendered recent-contact rows only; virtualized, not account-wide complete history' };
  }
  if (arg.mode === 'connection') {
    // Observed WangWang alertdialog. Merchant message text is never a reconnect control.
    const dialogs = [...document.querySelectorAll('[role="alertdialog"],.next-dialog')].filter(visible)
      .filter(e => !e.closest('[role="log"],.message-list,[data-chat-message]'))
      .filter(e => text(e.querySelector('.next-message-title')) === '连接断开' &&
        /^连接中断[，,]请刷新(?:后)?重试[。！!]?$/u.test(text(e.querySelector('.next-message-content'))));
    const unique = dialogs.filter(e => !dialogs.some(p => p !== e && p.contains(e)));
    return { status: unique.length ? 'disconnected' : 'no_disconnect_observed', transportVerified: false,
      dialogCount: unique.length, dialogs: unique.map(e => ({ path: path(e), title: '连接断开',
        controls: [...e.querySelectorAll('button,[role="button"]')].filter(visible)
          .filter(b => text(b) === '刷新').map(b => control(b, 'refresh_chat')) })),
      scope: 'recognized visible WangWang disconnect dialog only; no socket/server health claim' };
  }
  if (arg.mode === 'contacts') {
    const entries = [...document.querySelectorAll('a,button,[role="button"],[data-merchant-contact],.ww-inline,.ww-light')]
      .filter(visible).filter(e => /^(联系客服|联系卖家|联系商家|和我联系|在线客服|客服|旺旺联系)$/.test(text(e)) || e.matches('[data-merchant-contact],.ww-inline,.ww-light'))
      .filter(e => !e.closest('[data-recommendation],[class*="recommend"],[class*="Recommend"]'));
    return { controls: entries.filter(e => !entries.some(p => p !== e && p.contains(e))).map(e => ({ ...control(e, 'contact'), receiverId: e.getAttribute('data-receiver-id') || e.getAttribute('data-nick') || null, shopId: e.getAttribute('data-shop-id') || null })), iframeCount: document.querySelectorAll('iframe').length };
  }
  const roots = [...document.querySelectorAll('[data-merchant-chat],[role="dialog"],[role="region"]')].filter(visible)
    .filter(e => e.matches('[data-merchant-chat]') || /聊天|客服|会话/.test(e.getAttribute('aria-label') || ''));
  const unique = roots.filter(e => !roots.some(p => p !== e && e.contains(p)));
  // Observed 2026-10-20 on the real Taobao web-WangWang frame. A shell is
  // NOT a verified recipient or a functioning message adapter.
  if (unique.length === 0 && location.hostname === 'market.m.taobao.com' && location.pathname === '/app/im/chat-core/index.html') {
    const box = document.querySelector('.ww_box'), list = box?.querySelector('.ww_message .message-list');
    const editor = box?.querySelector('.ww_input .edit[contenteditable="true"]'), send = box?.querySelector('.send-btn');
    const headers = [...document.querySelectorAll('.ww_header .conversation-header .name')].filter(visible);
    const wwMessages = list ? [...list.querySelectorAll('.message-item-line .message-item')].filter(visible).map(e => {
      const body = e.querySelector('.content .expression-parser pre.edit[contenteditable="false"]');
      const card = e.querySelector('.content .im-template-msg.dx-msg-wrap');
      const bodyText = text(body) || text(card);
      const nick = text(e.querySelector('.first-line .nick'));
      const self = e.classList.contains('self');
      // Observed real counterparty layout (including an agent-named product
      // card). Direction is distinct from verifying a named human sender.
      const counterpartyLayout = !self && !!e.querySelector('.item:not(.self) .first-line .nick') && !!nick;
      const namedMerchant = !self && headers.length === 1 && nick === text(headers[0]);
      const incoming = counterpartyLayout || namedMerchant;
      const statusText = text(e.querySelector('.content')?.nextElementSibling);
      return { platformId: null, direction: self ? 'outgoing' : incoming ? 'incoming' : 'unknown',
        authorType: self ? 'self' : namedMerchant ? 'merchant-side' : counterpartyLayout ? 'conversation-counterparty' : 'unknown',
        senderIdentityVerified: !!namedMerchant, contentType: card ? 'rich-card' : body ? 'text' : 'unrecognized',
        directionEvidence: self ? 'observed-self-class' : counterpartyLayout ? 'observed-nonself-item-and-sender-line' : namedMerchant ? 'exact-header-name' : null,
        text: bodyText.slice(0, 8000) || null,
        timeText: text(e.querySelector('.first-line .time')) || null, absoluteTime: null,
        platformStatus: null, deliveryStatus: 'unknown', readStatus: statusText === '未读' ? 'unread' : statusText === '已读' ? 'read' : 'unknown',
        withdrawn: false, images: [...e.querySelectorAll('.content img')].filter(visible).map(i => ({ description: i.alt || null, parsed: false })).slice(0, 8),
        contentUnavailable: !bodyText };
    }).slice(-200) : [];
    if (visible(box) && visible(list) && visible(editor) && visible(send) && headers.length === 1 && text(headers[0])) return {
      supported: true, adapter: 'taobao-ww-web-v1', compatibility: 'Observed real web-WangWang header/editor/self text messages; unrecognized author roles stay unknown',
      rootPath: path(box), identity: { shopId: null, receiverId: null, label: text(headers[0]) },
      selectedEntryId: (() => { const rows = [...document.querySelectorAll('.ww_conversation_list .conversation-item.active')].filter(visible); return rows.length === 1 ? rows[0].id || null : null; })(),
      messages: wwMessages, controls: [control(send, 'send')], field: { path: path(editor), value: editor.innerText, contentEditable: true }, listPath: path(list),
      coverage: { scope: 'current WangWang conversation only', historyComplete: false, truncated: !!list && list.querySelectorAll('.message-item-line .message-item').length > 200,
        messageIdentity: 'weak-observation-sequence', unparsedThreadContent: !!text(list) && (!wwMessages.length || wwMessages.some(m => m.contentUnavailable)), unclassifiedMessageCount: wwMessages.filter(m => m.direction === 'unknown').length },
      iframeCount: document.querySelectorAll('iframe').length
    };
    if (visible(box) && visible(list) && visible(editor) && visible(send)) return {
      supported: false, recognized: true, adapter: 'taobao-ww-web-shell-observed-20261020', reason: 'recipient-and-message-template-unverified',
      readiness: { messageRegionPresent: true, editablePresent: true, sendButtonPresent: true, recipientVerified: false, currentThreadHasText: !!text(list) },
      note: 'Observed shell only. Do not send or infer recipient from the page title/URL.', iframeCount: document.querySelectorAll('iframe').length
    };
  }
  if (unique.length !== 1) return { supported: false, reason: unique.length ? 'ambiguous-chat-panels' : 'no-recognized-chat-panel', iframeCount: document.querySelectorAll('iframe').length };
  const root = unique[0], headers = [...root.querySelectorAll('[data-chat-recipient],[data-receiver-name],[role="heading"]')].filter(visible);
  const identity = { shopId: root.getAttribute('data-shop-id'), receiverId: root.getAttribute('data-receiver-id'), label: headers.length === 1 ? text(headers[0]) : null };
  const lists = [...root.querySelectorAll('[data-chat-messages],[role="log"]')].filter(visible);
  const fields = [...root.querySelectorAll('textarea,[contenteditable="true"],[role="textbox"]')].filter(visible).filter(e => !e.disabled && !e.readOnly).filter((e, _, all) => !all.some(p => p !== e && p.contains(e)));
  const list = lists.length === 1 ? lists[0] : null;
  const nodes = list ? [...list.querySelectorAll('[data-message-id],[data-chat-message],[role="listitem"]')].filter(visible) : [];
  const messages = nodes.filter(e => !nodes.some(p => p !== e && p.contains(e))).slice(-200).map(e => {
    const bodies = [...e.querySelectorAll('[data-message-text],.message-content,.msg-content')].filter(visible);
    const body = bodies.length === 1 ? text(bodies[0]) : null;
    const direction = e.getAttribute('data-direction');
    const tm = e.querySelector('time,[data-message-time]');
    const platformStatus = e.getAttribute('data-send-status') || null;
    return { platformId: e.getAttribute('data-message-id') || null, direction: ['incoming', 'outgoing', 'system'].includes(direction) ? direction : 'unknown',
      authorType: e.getAttribute('data-bot') === 'true' ? 'bot' : direction === 'incoming' ? 'merchant-side' : direction === 'outgoing' ? 'self' : 'unknown',
      text: body?.slice(0, 8000) || null, timeText: text(tm) || null, absoluteTime: tm?.getAttribute('datetime') || null,
      platformStatus, deliveryStatus: e.getAttribute('data-delivery-status') || 'unknown', readStatus: e.getAttribute('data-read-status') || 'unknown',
      withdrawn: e.getAttribute('data-withdrawn') === 'true', images: [...e.querySelectorAll('img')].filter(visible).map(i => ({ description: i.alt || null, parsed: false })).slice(0, 8),
      contentUnavailable: !body };
  });
  const buttons = [...root.querySelectorAll('button,[role="button"],input[type="submit"]')].filter(visible);
  const controls = buttons.map(e => { const label = text(e) || e.value || ''; const action = /^(发送|发送消息|Send)$/.test(label) ? 'send' : /^(加载更多消息|查看更多消息|历史消息|加载历史消息)$/.test(label) ? 'history' : /^(关闭|关闭聊天|Close)$/.test(label) ? 'close' : null; return action ? control(e, action) : null; }).filter(Boolean);
  return { supported: true, adapter: 'semantic-chat-v1', compatibility: 'observed semantic structure only; platform template not certified', rootPath: path(root), identity,
    messages, controls, field: fields.length === 1 ? { path: path(fields[0]), value: fields[0].isContentEditable ? fields[0].innerText : fields[0].value, contentEditable: fields[0].isContentEditable } : null,
    listPath: list ? path(list) : null, coverage: { scope: 'currently rendered conversation only', historyComplete: false, truncated: nodes.length > 200, messageIdentity: messages.every(m => m.platformId) ? 'platform-visible-id' : 'weak-observation-sequence' }, iframeCount: document.querySelectorAll('iframe').length };
}
// HUOYAN_DOM_END
module.exports = { readMerchantChat };
