const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const {execFileSync} = require('node:child_process');
const { chromium } = require('playwright');
const { Client } = require('@modelcontextprotocol/sdk/client/index.js');
const { StdioClientTransport } = require('@modelcontextprotocol/sdk/client/stdio.js');

(async () => {
  const root = path.resolve(__dirname, '..');
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'huoyan-mcp-research-'));
  const port = await new Promise(resolve => {
    const server = net.createServer();server.listen(0, '127.0.0.1', () => { const p = server.address().port;server.close(() => resolve(p)); });
  });
  let context, client;
  try {
    context = await chromium.launchPersistentContext(path.join(temporary, 'profile'), {
      executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true,
      args: ['--no-proxy-server', `--remote-debugging-port=${port}`]
    });
    const detailFixture=`<!doctype html><meta charset="utf-8"><title>Local detail MCP fixture</title>
      <img data-shop-level alt="三钻" width="78" height="24" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='78' height='24'%3E%3C/svg%3E"><span data-shop-score>4.6</span><div data-product-metrics>已售1万+ 回头客379人 超400人加购</div>
      <button data-open-shop-reputation onmouseenter="document.querySelector('[data-shop-reputation-panel]').hidden=false">店铺评分信息</button><div data-shop-reputation-panel hidden><div data-shop-rating-row>宝贝质量 5.0</div><div data-shop-rating-row>物流速度 4.4</div><div data-shop-rating-row>服务保障 4.4</div></div>
      <a class="shop-name" href="https://shop123.taobao.com/">测试店铺</a><div class="skuItem"><span class="label">重量</span><li>1kg</li><li>2kg</li></div><div data-product-price>￥36</div>
      <div data-product-parameters><dl data-parameter-row><dt>材料</dt><dd>PLA</dd></dl></div>
      <button data-open-reviews onclick="document.querySelector('[data-detail-panel]').hidden=false">查看全部评价</button>
      <div data-detail-panel="reviews" hidden style="position:fixed;inset:0;background:white"><button data-close-detail onclick="this.parentElement.hidden=true">关闭</button>
      <article data-review><span>PRIVATE_BUYER_NAME</span><p data-review-text>打印稳定</p></article></div>`;
    const shopFixture=`<!doctype html><meta charset="utf-8"><title>Local shop MCP fixture</title><h1 data-shop-name>测试店铺</h1>
      <form data-shop-search onsubmit="event.preventDefault();history.pushState({},'', '/search.htm?keyword='+encodeURIComponent(this.q.value));document.querySelector('#cards').hidden=false"><input name="q"><button>搜本店</button></form>
      <div id="cards" data-shop-products hidden><a target="_blank" data-product-card href="https://item.taobao.com/item.htm?id=123">PLA ￥36</a></div>`;
    await context.route('**/*', r => r.fulfill({contentType: 'text/html; charset=utf-8', body: r.request().url().includes('item.taobao.com')?detailFixture:r.request().url().includes('shop123.taobao.com')?shopFixture:`<!doctype html><meta charset="utf-8"><title>Local MCP fixture</title>
      <button role="tab" aria-selected="true">综合</button><button role="tab" aria-selected="false" onclick="document.querySelectorAll('button').forEach(b=>b.setAttribute('aria-selected',b===this))">销量</button>
      <a href="https://item.taobao.com/item.htm?id=123">PLA ￥36 100人付款</a>`}));
    const page = context.pages()[0];await page.goto('https://s.taobao.com/search');
    const session = await context.newCDPSession(page);
    const tabId = (await session.send('Target.getTargetInfo')).targetInfo.targetId;await session.detach();
    client = new Client({name:'research-test',version:'1.0.0'});
    await client.connect(new StdioClientTransport({command:process.execPath,args:[path.join(root,'src/mcp.js')],cwd:root,stderr:'pipe',env:{...process.env,HUOYAN_WORDING_MODE:'off'}}));
    const names = (await client.listTools()).tools.map(t=>t.name);
    assert(names.includes('preview_merchant_wording'));
    for(const name of ['list_merchant_chats','search_merchant_chats','switch_merchant_chat','load_more_merchant_chats','cancel_merchant_chat_switch'])assert(names.includes(name),name);
    for(const name of ['save_local_favorite','list_local_favorites','remove_local_favorite','open_local_favorite','favorite_options','set_taobao_favorite','open_taobao_favorites','taobao_favorites_state','find_taobao_favorite','open_taobao_favorite'])assert(names.includes(name),name);
    const wordingPreview=await client.callTool({name:'preview_merchant_wording',arguments:{out:path.join(temporary,'wording'),cdp:'http://127.0.0.1:1',intent:'invoice_shop',wordingMode:'off',questionIds:['paid_amount'],answeredQuestionIds:['can_invoice']}});
    assert(!wordingPreview.isError,JSON.stringify(wordingPreview));
    const wordingMetadata=JSON.parse(wordingPreview.content[0].text);
    assert.equal(wordingMetadata.sent,false);assert.equal(wordingMetadata.browserConnected,false);
    assert.equal(wordingMetadata.wording.text,'开票金额和实付金额一样吗？');
    assert(names.includes('set_tab_limit'));assert(names.includes('trim_product_tabs'));
    assert(names.includes('resume_shopping'));
    for(const name of ['search_and_read','ask_shop_invoice','workflow_status'])assert(names.includes(name),name);
    for(const name of ['shopping_state','search_products','set_sort','set_filters','click_shopping_control','list_products','load_more','go_to_page','select_sku','read_selected_offer','save_candidate','compare_candidates','research_progress','activate_shopping_tab','return_to_results'])assert(names.includes(name),name);
    for(const name of ['detail_state','open_detail_section','read_product_parameters','open_reviews','read_reviews','open_review_menu','set_review_filter','load_more_detail','close_detail_panel','view_product_image','read_product_questions','expand_question_answers','read_delivery_services','set_quantity','open_product_shop'])assert(names.includes(name),name);
    for(const name of ['shop_state','list_shops','open_shop','search_shop_products','open_shop_section','open_shop_category','open_shop_product','return_to_shop_results'])assert(names.includes(name),name);
    assert(names.includes('read_product_evidence'));
    assert(names.includes('read_shop_reputation'));
    assert(names.includes('product_image_overview'));assert(names.includes('read_product_image'));
    for(const name of ['merchant_contact_options','open_merchant_chat','merchant_chat_state','recover_merchant_chat','prepare_invoice_inquiry','send_merchant_message','read_merchant_messages','wait_merchant_reply','load_merchant_history','summarize_invoice_terms','return_from_merchant_chat','finish_merchant_inquiry'])assert(names.includes(name),name);
    assert(!names.includes('authorize_invoice_inquiry'));
    const common={tabId,cdp:`http://127.0.0.1:${port}`,out:path.join(temporary,'data'),delayMin:0,delayMax:0};
    const invoke=async(name,args={})=>{
      const r=await client.callTool({name,arguments:{...common,...args}});
      assert(!r.isError,JSON.stringify(r));return JSON.parse(r.content[0].text);
    };
    const rejected=await client.callTool({name:'set_sort',arguments:{...common,field:'sales'}});assert(rejected.isError);
    assert.equal(JSON.parse(rejected.content[0].text).code,'NEEDS_TAB_SWITCH');
    await invoke('activate_shopping_tab');
    await page.evaluate(()=>window.recoveryMarker=42);
    const resumed=await invoke('resume_shopping');assert(resumed.confirmed);assert.equal(resumed.recovery,'reused-existing-tab');
    assert.equal(await page.evaluate(()=>window.recoveryMarker),42);
    assert.equal((await invoke('shopping_state')).tabBudget.maxTabs,10);
    const configuredTabs=await invoke('set_tab_limit',{maxTabs:8});assert.equal(configuredTabs.tabBudget.maxTabs,8);
    assert.equal(configuredTabs.tabBudget.blocked,false);assert.deepEqual(configuredTabs.tabBudget.closedTabs,[]);
    assert.equal((await invoke('trim_product_tabs')).tabBudget.openTabs,1);
    assert.equal((await invoke('shopping_state')).tabBudget.maxTabs,8);
    const before=await invoke('shopping_state');assert.equal(before.sort.field,'comprehensive');assert.equal(before.products.length,1);
    const sorted=await invoke('set_sort',{field:'sales'});assert.equal(sorted.confirmed,true);assert.equal(sorted.after.sort.field,'sales');
    assert.equal((await invoke('set_sort',{field:'sales'})).clicks,0);
    assert.equal((await invoke('research_progress')).progress.lastAction,'set_sort');
    assert.deepEqual((await invoke('compare_candidates')).candidates,[]);
    await page.goto('https://item.taobao.com/item.htm?id=123');
    const active=await invoke('activate_shopping_tab');assert.equal(active.state.detail.skuGroups[0].options.length,2);
    assert.deepEqual(active.state.detail.selectedSku,[]);
    const inspected=await invoke('inspect_product',{item:'123'});assert.equal(inspected.detail.source,'live-page');
    await page.evaluate(()=>{
      window.favoriteClicks=0;
      document.body.insertAdjacentHTML('afterbegin','<button data-favorite-toggle aria-pressed="false">收藏</button>');
      document.querySelector('[data-favorite-toggle]').onclick=e=>{window.favoriteClicks++;e.currentTarget.setAttribute('aria-pressed','true');e.currentTarget.innerText='已收藏'};
    });
    const localFavorite=await invoke('save_local_favorite',{note:'MCP 收藏验收',tags:['local-only']});assert.equal(localFavorite.scope,'local');assert.equal(localFavorite.taobaoAccountChanged,false);
    const localFavorites=await invoke('list_local_favorites',{query:'MCP 收藏验收',cdp:'http://127.0.0.1:1'});assert.equal(localFavorites.totalMatches,1);
    const nativeOptions=await invoke('favorite_options');const nativeToggle=nativeOptions.controls.find(c=>c.action==='set_taobao_favorite');assert(nativeToggle);
    const nativeFavorite=await invoke('set_taobao_favorite',{controlId:nativeToggle.controlId,requestId:'mcp-favorite',selected:true});assert(nativeFavorite.confirmed);
    assert((await invoke('set_taobao_favorite',{requestId:'mcp-favorite',selected:true})).replayed);assert.equal(await page.evaluate(()=>favoriteClicks),1);
    assert.equal((await invoke('open_local_favorite',{favoriteId:localFavorite.favorite.favoriteId})).source,'existing-tab');
    assert((await invoke('remove_local_favorite',{favoriteId:localFavorite.favorite.favoriteId,cdp:'http://127.0.0.1:1'})).removed);
    const evidence=await invoke('read_product_evidence',{includeLevelImage:false});assert.equal(evidence.commerce.shop.level.text,'三钻');assert(evidence.commerce.metrics.some(m=>m.kind==='cart-additions'&&m.numericValue===400));
    const visual=await client.callTool({name:'read_product_evidence',arguments:{...common,includeLevelImage:true}});assert(!visual.isError,JSON.stringify(visual));assert(visual.content.some(c=>c.type==='image'));assert(!visual.content[0].text.includes('levelImageBase64'));
    const reputation=await invoke('read_shop_reputation');assert.equal(reputation.shop.reputation.rows.length,0);
    const reputationControl=reputation.state.detail.controls.find(c=>c.tool==='read_shop_reputation');assert(reputationControl);
    const reputationOpen=await invoke('read_shop_reputation',{controlId:reputationControl.controlId});assert(reputationOpen.confirmed);assert.equal(reputationOpen.clicks,0);assert.equal(reputationOpen.shop.reputation.rows[0].displayValue,'5.0');
    await page.evaluate(()=>document.body.insertAdjacentHTML('beforeend',`<img data-product-main-image width=140 height=140 src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140'%3E%3C/svg%3E">`));
    await page.waitForFunction(()=>document.querySelector('[data-product-main-image]').naturalWidth>0);
    const quietOverview=await client.callTool({name:'product_image_overview',arguments:{...common,maxImages:1}});assert(quietOverview.isError);assert.equal(JSON.parse(quietOverview.content[0].text).code,'IMAGE_UNAVAILABLE');
    const overviewRaw=await client.callTool({name:'product_image_overview',arguments:{...common,maxImages:1,allowScreenshot:true}});assert(!overviewRaw.isError,JSON.stringify(overviewRaw));assert(overviewRaw.content.some(c=>c.type==='image'));assert(!overviewRaw.content[0].text.includes('imageBase64'));
    const overview=JSON.parse(overviewRaw.content[0].text);const singleRaw=await client.callTool({name:'read_product_image',arguments:{...common,overviewId:overview.overviewId,index:overview.images[0].index}});assert(!singleRaw.isError,JSON.stringify(singleRaw));assert(singleRaw.content.some(c=>c.type==='image'));
    assert.equal((await invoke('read_product_parameters')).parameters[0].value,'PLA');
    const opened=await invoke('open_reviews');assert.equal(opened.confirmed,true);
    const reviews=await invoke('read_reviews');assert.equal(reviews.reviews[0].text,'打印稳定');
    assert(!JSON.stringify(reviews).includes('PRIVATE_BUYER_NAME'));
    const closed=await invoke('close_detail_panel',{panelId:reviews.state.detail.panels[0].panelId});assert.equal(closed.confirmed,true);
    await page.evaluate(()=>document.body.insertAdjacentHTML('beforeend','<div id="review-obstruction" style="position:fixed;inset:0;z-index:99999;background:white"></div>'));
    const obstructed=await client.callTool({name:'open_reviews',arguments:common});assert(obstructed.isError);
    const obstructionError=JSON.parse(obstructed.content[0].text);assert.equal(obstructionError.code,'CONTROL_NOT_ACTIONABLE');
    assert(obstructionError.error.includes('no click delivered'));assert(obstructionError.nextAction.includes('no automatic retry'));
    assert(await page.locator('[data-detail-panel="reviews"]').isHidden());
    await page.locator('#review-obstruction').evaluate(e=>e.remove());
    assert.equal(context.pages().length,1);
    const entries=await invoke('list_shops');assert.equal(entries.shops.length,1);
    const shop=await invoke('open_shop',{controlId:entries.shops[0].controlId});assert.equal(shop.confirmed,true);assert.equal(shop.state.shop.identity.shopId,'123');
    const searched=await invoke('search_shop_products',{keyword:'PLA'});assert.equal(searched.confirmed,true);assert.equal(searched.state.shop.query,'PLA');
    const products=await invoke('list_products');assert.equal(products.products[0].region,'shop-products');
    const product=await invoke('open_shop_product',{controlId:products.products[0].controlIds[0]});assert.equal(product.confirmed,true);assert(product.state.detail.skuGroups.length);
    common.tabId=product.state.tabId;
    const returned=await invoke('return_to_shop_results');assert.equal(returned.confirmed,true);assert.equal(returned.state.shop.query,'PLA');
    common.tabId=tabId;await page.goto('https://item.taobao.com/item.htm?id=123');await invoke('activate_shopping_tab');
    await page.evaluate(()=>{
      document.querySelector('.skuItem li').className='selected';
      document.body.insertAdjacentHTML('beforeend',`<button data-merchant-contact onclick="document.querySelector('[data-merchant-chat]').hidden=false">联系客服</button>
        <section data-merchant-chat data-shop-id="123" hidden><h2 data-chat-recipient>测试店客服</h2><div role="log"></div><textarea></textarea>
        <button id="chat-send">发送</button><button onclick="this.parentElement.hidden=true">关闭聊天</button></section>`);
      window.chatSends=0;
      document.querySelector('#chat-send').onclick=()=>{
        window.chatSends++;const f=document.querySelector('textarea'),e=document.createElement('article');e.dataset.chatMessage='';e.dataset.messageId='sent-1';e.dataset.direction='outgoing';
        const p=document.createElement('p');p.dataset.messageText='';p.innerText=f.value;e.append(p);document.querySelector('[role=log]').append(e);f.value='';
      };
    });
    const contacts=await invoke('merchant_contact_options');assert.equal(contacts.contacts.length,1);
    const chat=await invoke('open_merchant_chat',{controlId:contacts.contacts[0].controlId});assert(chat.confirmed);
    const conversationId=chat.state.conversationId;
    const draft=await invoke('prepare_invoice_inquiry',{conversationId,quantity:2});assert.equal(draft.sent,false);
    const denied=await client.callTool({name:'send_merchant_message',arguments:{...common,conversationId,draftId:draft.draft.draftId,authorizationId:'fake',requestId:'denied'}});
    assert(denied.isError);assert.equal(JSON.parse(denied.content[0].text).code,'CHAT_AUTH_REQUIRED');
    const grant=JSON.parse(execFileSync(path.join(root,'.venv/Scripts/python.exe'),['-X','utf8',path.join(root,'scripts/authorize-invoice-inquiry.py'),'--out',common.out,'--cdp',common.cdp,'--draft',draft.draft.draftId,'--user-reference','local MCP fixture consent'],{encoding:'utf8',windowsHide:true}));
    const sent=await invoke('send_merchant_message',{conversationId,draftId:draft.draft.draftId,authorizationId:grant.authorizationId,requestId:'send-once'});assert(sent.confirmed);assert.equal(sent.attempt.deliveryStatus,'unknown');
    const replay=await invoke('send_merchant_message',{conversationId,draftId:draft.draft.draftId,authorizationId:grant.authorizationId,requestId:'send-once'});assert(replay.replayed);assert.equal(await page.evaluate(()=>window.chatSends),1);
    await page.evaluate(()=>{
      window.chatRefreshes=0;const d=document.createElement('div');d.className='next-dialog';d.setAttribute('role','alertdialog');
      d.innerHTML='<div class="next-message-title">连接断开</div><div class="next-message-content">连接中断，请刷新重试</div><button>刷新</button>';
      d.querySelector('button').onclick=()=>{chatRefreshes++;d.remove()};document.body.append(d);
    });
    const recoveredChat=await invoke('recover_merchant_chat',{conversationId});
    assert(recoveredChat.confirmed);assert.equal(recoveredChat.connection.lastRecovery.status,'recovered');
    assert.equal(recoveredChat.connection.transportVerified,false);
    await invoke('recover_merchant_chat',{conversationId});
    assert.deepEqual(await page.evaluate(()=>[chatRefreshes,chatSends]),[1,1]);
    const chatRead=await invoke('read_merchant_messages',{conversationId});
    await page.evaluate(()=>document.querySelector('[role=log]').insertAdjacentHTML('beforeend','<article data-chat-message data-message-id="reply" data-direction="incoming"><p data-message-text>可以开票，含税72元，运费另算</p></article>'));
    const reply=await invoke('wait_merchant_reply',{conversationId,afterCursor:chatRead.cursor,timeoutSeconds:0});assert(!reply.pending);
    const summary=await invoke('summarize_invoice_terms',{inquiryId:draft.inquiry.inquiryId,terms:{canIssue:{value:'yes',status:'seller_confirmed',evidence:[{evidenceId:reply.messages[0].evidenceId,quote:'可以开票'}]}}});assert(summary.saved);
    assert((await invoke('return_from_merchant_chat',{conversationId})).confirmed);
    assert.equal((await invoke('finish_merchant_inquiry',{inquiryId:draft.inquiry.inquiryId})).status,'completed');
    const shopWorkflow=await invoke('ask_shop_invoice',{requestId:'mcp-shop-workflow',waitSeconds:0});
    assert.equal(shopWorkflow.workflow.status,'awaiting_authorization',JSON.stringify(shopWorkflow));
    assert.equal(shopWorkflow.workflow.draft,'你好，你们家能开票吗？开票金额和实付金额一样吗？');
    assert.equal(await page.evaluate(()=>window.chatSends),1);
    const workflowGrant=JSON.parse(execFileSync(path.join(root,'.venv/Scripts/python.exe'),['-X','utf8',path.join(root,'scripts/authorize-invoice-inquiry.py'),'--out',common.out,'--cdp',common.cdp,'--draft',shopWorkflow.workflow.draftId,'--user-reference','local workflow fixture consent'],{encoding:'utf8',windowsHide:true}));
    // Fixture keeps a distinct message ID per native click, as the real adapter does.
    await page.evaluate(()=>{document.querySelector('#chat-send').onclick=()=>{
      window.chatSends++;const f=document.querySelector('textarea'),e=document.createElement('article');e.dataset.chatMessage='';e.dataset.messageId='workflow-'+window.chatSends;e.dataset.direction='outgoing';
      const p=document.createElement('p');p.dataset.messageText='';p.innerText=f.value;e.append(p);document.querySelector('[role=log]').append(e);f.value='';
    }});
    const workflowSent=await invoke('ask_shop_invoice',{requestId:'mcp-shop-workflow',authorizationId:workflowGrant.authorizationId});
    assert.equal(workflowSent.workflow.status,'waiting_reply',JSON.stringify(workflowSent));
    await invoke('ask_shop_invoice',{requestId:'mcp-shop-workflow'});assert.equal(await page.evaluate(()=>window.chatSends),2);
    const savedWorkflow=await invoke('workflow_status',{requestId:'mcp-shop-workflow'});assert.equal(savedWorkflow.workflow.draftId,shopWorkflow.workflow.draftId);
    await page.goto('https://s.taobao.com/search?q=old');
    await page.evaluate(()=>{
      window.workflowSearches=0;
      document.body.insertAdjacentHTML('afterbegin','<form><input name="q" value="old"><button>搜索</button></form>');
      document.querySelector('form').onsubmit=e=>{e.preventDefault();window.workflowSearches++;history.pushState({},'','/search?q='+encodeURIComponent(e.target.q.value))};
    });
    const searchedWorkflow=await invoke('search_and_read',{requestId:'mcp-search-workflow',keyword:'PLA灰色'});
    assert(searchedWorkflow.confirmed,JSON.stringify(searchedWorkflow));
    assert((await invoke('search_and_read',{requestId:'mcp-search-workflow',keyword:'PLA灰色'})).replayed);
    assert.equal(await page.evaluate(()=>window.workflowSearches),1);
    const inboxFixture=fs.readFileSync(path.join(root,'scripts/test-merchant-inbox.py'),'utf8').match(/WW = '''([\s\S]*?)'''/)[1];
    await context.route('**/app/im/chat-core/index.html',r=>r.fulfill({contentType:'text/html; charset=utf-8',body:inboxFixture}));
    await page.goto('https://market.m.taobao.com/app/im/chat-core/index.html');
    await invoke('activate_shopping_tab',{background:true});
    const inbox=await invoke('list_merchant_chats');assert.equal(inbox.entries.length,3);
    assert(!JSON.stringify(inbox).includes('private-account'));
    const filteredInbox=await invoke('search_merchant_chats',{keyword:'第二'});
    assert(filteredInbox.confirmed);assert.equal(filteredInbox.entries.length,1);
    const inboxPageCount=context.pages().length;
    const switchedInbox=await invoke('switch_merchant_chat',{requestId:'mcp-inbox-b',controlId:filteredInbox.entries[0].controlId});
    assert(switchedInbox.confirmed);assert(switchedInbox.state.readOnly);assert.equal(switchedInbox.state.messages[0].text,'B店答复');
    assert.equal(context.pages().length,inboxPageCount);
    assert((await invoke('switch_merchant_chat',{requestId:'mcp-inbox-b'})).replayed);
    assert.deepEqual(await page.evaluate(()=>[switchCount,sendCount,deleted]),[1,0,0]);
    const readInbox=await invoke('read_merchant_messages',{conversationId:switchedInbox.state.conversationId});
    assert.equal(readInbox.messages[0].text,'B店答复');
    const inboxDenied=await client.callTool({name:'prepare_invoice_inquiry',arguments:{...common,conversationId:switchedInbox.state.conversationId}});
    assert(inboxDenied.isError);assert.equal(JSON.parse(inboxDenied.content[0].text).code,'CHAT_READ_ONLY');
    const restoredInbox=await invoke('search_merchant_chats',{keyword:''});assert.equal(restoredInbox.entries.length,3);
    const inboxBottom=await invoke('load_more_merchant_chats',{listId:restoredInbox.listId});
    assert(inboxBottom.reachedBottom);assert.equal(inboxBottom.scrolled,false);
    await page.evaluate(()=>{window.stopSwitch=true});
    const beforeBlocked=await invoke('list_merchant_chats');
    const third=beforeBlocked.entries.find(e=>e.label==='第三店');
    const blockedSwitch=await invoke('switch_merchant_chat',{controlId:third.controlId,requestId:'mcp-inbox-blocked'});
    assert.equal(blockedSwitch.status,'waiting_thread');assert.equal(blockedSwitch.diagnostics.selectedEntryMatches,false);
    const abandoned=await invoke('cancel_merchant_chat_switch',{requestId:'mcp-inbox-blocked'});
    assert(abandoned.cancelled);assert(abandoned.localBlockReleased);assert.equal(abandoned.confirmed,true);assert.equal(abandoned.switchConfirmed,false);
    const cancelledReplay=await invoke('switch_merchant_chat',{requestId:'mcp-inbox-blocked'});assert.equal(cancelledReplay.status,'cancelled');
    await page.evaluate(()=>{window.stopSwitch=false});
    const freshContacts=await invoke('list_merchant_chats');
    const finalSwitch=await invoke('switch_merchant_chat',{controlId:freshContacts.entries.find(e=>e.label==='第三店').controlId,requestId:'mcp-inbox-final'});
    assert(finalSwitch.confirmed);assert.equal(finalSwitch.state.recipient.label,'第三店');
    assert.deepEqual(await page.evaluate(()=>[switchCount,sendCount,deleted]),[3,0,0]);
    console.log('PASS MCP registration/schema/defaults, research/detail/shop, authorized chat, recovery, inbox search/switch/read/replay/read-only isolation');
  } finally {
    if(client)await client.close();if(context)await context.close();
    if(!path.resolve(temporary).startsWith(path.resolve(os.tmpdir())+path.sep))throw Error('Unsafe temporary cleanup path');
    fs.rmSync(temporary,{recursive:true,force:true});
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
