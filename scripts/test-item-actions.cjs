const fs = require('fs');
const path = require('path');
const Module = require('module');
const root = require('path').resolve(__dirname, '..');
const { chromium } = require(root + '/node_modules/playwright');
const source = root + '/src/core/itemActions.js';
const loaded = new Module(source, module);
loaded.filename = source;
loaded.paths = Module._nodeModulePaths(path.dirname(source));
loaded._compile(fs.readFileSync(source, 'utf8') + '\nmodule.exports.testHelpers = { clickSkuOption, isOptionSelected, setQuantity, clickFavorite, detectFavoriteResult, detectCartSuccess };', source);
const { resolveItemUrl, readSkuGroups, testHelpers: h } = loaded.exports;
const results = [];
async function check(name, fn) {
  try { const detail = await fn(); results.push({name, ...detail}); console.log(JSON.stringify(results.at(-1))); }
  catch(e) { results.push({name, error:e.message}); console.log(JSON.stringify(results.at(-1))); }
}
(async () => {
 const browser = await chromium.launch({executablePath:require(root+'/src/core/browser').getDefaultEdgePath(), headless:true});
 const page = await browser.newPage();
 const html = async content => page.setContent('<html><body>' + content + '</body></html>');
 await check('numeric item ID', async()=>({pass:resolveItemUrl('123')==='https://item.taobao.com/item.htm?id=123'}));
 await check('normal favorite click and state', async()=>{
   await html('<button class="favorite" onclick="this.innerText=\'已收藏\'">收藏</button>');
   const click=await h.clickFavorite(page); const evidence=await h.detectFavoriteResult(page);
   return {pass:click.clicked && evidence==='already-state',click,evidence};
 });
 await check('favorite repeat does not cancel', async()=>{
   const click=await h.clickFavorite(page); return {pass:click.already===true,click};
 });
 await check('legacy favorite success state recognized', async()=>{
   await html('<a id="J_Favorite" onclick="this.innerText=\'已收藏\'">收藏</a>');
   const click=await h.clickFavorite(page); const evidence=await h.detectFavoriteResult(page);
   return {pass:!!evidence,click,evidence};
 });
 await check('cart unrelated success text must not count', async()=>{
   await html('<p>评价添加成功</p><button>加入购物车</button>');
   const evidence=await h.detectCartSuccess(page);return {pass:evidence===null,evidence};
 });
 await check('favorite unrelated success text must not count', async()=>{
   await html('<p>店铺收藏成功</p><button class="favorite">收藏商品</button>');
   const evidence=await h.detectFavoriteResult(page);return {pass:evidence===null,evidence};
 });
 await check('quantity input set', async()=>{
   await html('<input id="J_IptAmount" value="1">');const qty=await h.setQuantity(page,3);return {pass:qty.set && qty.value==='3',qty};
 });
 await check('quantity does not overwrite unrelated input', async()=>{
   await html('<input type="text" maxlength="20" placeholder="搜索商品" value="1K电阻">');
   const qty=await h.setQuantity(page,3);const search=await page.locator('input').inputValue();return {pass:search==='1K电阻' && !qty.set,qty,search};
 });
 await check('single-option SKU group indexing', async()=>{
   await html('<div id="J_isku"><ul class="J_TSaleProp"><li>0805</li></ul><ul class="J_TSaleProp"><li>1K</li><li>2K</li></ul></div>');
   const groups=await readSkuGroups(page);const click=await h.clickSkuOption(page,0,'1K');return {pass:click.clicked,groups,click};
 });
 await check('aria-checked false means not selected', async()=>{
   await html('<div class="skuItem"><span role="radio" aria-checked="false">1K</span><span role="radio" aria-checked="false">2K</span></div>');
   const selected=await h.isOptionSelected(page,0,'1K');return {pass:!selected,selected};
 });
 await check('missing SKU text does not choose prefix', async()=>{
   await html('<div class="skuItem"><li onclick="this.className=\'selected\'">1KΩ</li><li>1KΩ 100只</li></div>');
   const click=await h.clickSkuOption(page,0,'1KΩ 100只 缺货');return {pass:!click.clicked,click};
 });
 await check('favorite does not target shop', async()=>{
   await html('<button class="favoriteShop" onclick="this.dataset.hit=\'1\'">收藏店铺</button><button class="favoriteItem" onclick="this.dataset.hit=\'1\'">收藏商品</button>');
   const click=await h.clickFavorite(page);const target=await page.locator('[data-hit="1"]').innerText();return {pass:target==='收藏商品',click,target};
 });
 await check('modern favorite icon prevents cancellation', async()=>{
   await html('<div id="collectBtn" class="RightButton--test" onclick="this.innerHTML=\'收藏\'"> <i class="icon-taobaoyishoucang"></i>收藏</div>');
   const click=await h.clickFavorite(page);return {pass:click.already===true && !click.clicked,click};
 });
 await check('disabled SKU is rejected',async()=>{
   await html('<div class="skuItem"><li class="isDisabled--test">1K</li><li>2K</li></div>');const click=await h.clickSkuOption(page,0,'1K');return {pass:!click.clicked,click};
 });
 await check('unselected class is not selected',async()=>{
   await html('<div class="skuItem"><li class="unselected">1K</li><li>2K</li></div>');return {pass:!await h.isOptionSelected(page,0,'1K')};
 });
 await check('stale success toast is ignored',async()=>{
   await html('<p>加入购物车成功</p>');const {inspect}=require(root+'/src/core/itemPage');await inspect(page,'snapshot',{action:'cart'});return {pass:await inspect(page,'cart-evidence')===null};
 });
 await check('fresh success toast is accepted',async()=>{
   await page.evaluate(()=>document.body.insertAdjacentHTML('beforeend','<p>加入购物车成功</p>'));const {inspect}=require(root+'/src/core/itemPage');return {pass:await inspect(page,'cart-evidence')==='success-text'};
 });
 await check('invalid item URLs rejected',async()=>{
   const invalid=['https://taobao.com.evil.test/item.htm?id=1','https://evil.test/?taobao.com','https://item.taobao.com/search?id=1','https://user:pass@item.taobao.com/item.htm?id=1','https://detail.tmall.com/item.htm?id=abc'];
   return {pass:invalid.every(url=>{try{resolveItemUrl(url);return false;}catch{return true;}})};
 });
 await check('invalid quantities rejected before browser launch',async()=>{
   const invalid=['0','-1','1.5','3oops','9007199254740992'];let all=true;for(const count of invalid){try{await loaded.exports.runItemAction({action:'cart',item:'123',count});all=false;}catch(e){all=all&&/positive integer/.test(e.message);}}return {pass:all};
 });
 await check('CLI unsuccessful action has nonzero exit code',async()=>{
   const {spawnSync}=require('child_process');
   const setup='require.cache[require.resolve('+JSON.stringify(root+'/src/core/itemActions')+') ]={exports:{runItemAction:async()=>({ok:false,evidence:"no-success-indicator",title:"fixture"})}};process.argv=[process.execPath,'+JSON.stringify(root+'/src/cli.js')+',"fav","--item","123"];require('+JSON.stringify(root+'/src/cli.js')+');';
   const child=spawnSync(process.execPath,['-e',setup],{encoding:'utf8'});return {pass:child.status===4,exitCode:child.status,stdout:child.stdout.trim()};
 });
 await check('shop already-collected state does not suppress item action',async()=>{
   await html('<button class="favoriteShop">已收藏</button><button class="favoriteItem" onclick="this.innerText=\'已收藏\'">收藏商品</button>');
   const click=await h.clickFavorite(page);return {pass:click.clicked===true && !click.already,click};
 });
 await check('account input is not quantity input',async()=>{
   await html('<input class="accountInput" value="sample">');const qty=await h.setQuantity(page,2);return {pass:!qty.set && await page.locator('input').inputValue()==='sample',qty};
 });
 await check('legacy selected class is recognized',async()=>{
   await html('<div id="J_isku"><ul class="J_TSaleProp"><li class="tb-selected">1K</li><li>2K</li></ul></div>');return {pass:await h.isOptionSelected(page,0,'1K')};
 });
 await browser.close();
 if(process.argv[2]) fs.writeFileSync(process.argv[2],JSON.stringify(results,null,2));
 if(results.some(x=>!x.pass)) process.exitCode=1;
 console.log('SUMMARY',JSON.stringify({total:results.length,passed:results.filter(x=>x.pass).length,failed:results.filter(x=>x.pass===false).length}));
})().catch(e=>{console.error(e);process.exitCode=1});
