const root = require('path').resolve(__dirname, '..');
const fs=require('fs');
const path=require('path');
const out=fs.mkdtempSync(path.join(require('os').tmpdir(),'huoyan-item-flow-'));
const {chromium}=require(root+'/node_modules/playwright');
const browserModule=require(root+'/src/core/browser');
const utils=require(root+'/src/core/utils');
utils.sleepRandom=async()=>0;
let active;
browserModule.acquireBrowser=async()=>active;
const {runItemAction}=require(root+'/src/core/itemActions');
(async()=>{
 const browser=await chromium.launch({executablePath:require(root+'/src/core/browser').getDefaultEdgePath(),headless:true});
 const results=[];
 const scenarios=[
  {name:'supplied SKU is rejected when no groups are recognized',html:'<input id="J_IptAmount" value="1"><button onclick="document.body.insertAdjacentHTML(\'beforeend\',\'<p>加入购物车成功</p>\')">加入购物车</button>',options:{sku:['1K']},mustReject:true},
  {name:'requested quantity 1 overwrites page default 5',html:'<input id="J_IptAmount" value="5"><button onclick="document.body.insertAdjacentHTML(\'beforeend\',\'<p>加入购物车成功</p>\')">加入购物车</button>',options:{count:'1'},expectedQuantity:'1'},
  {name:'failed quantity setting prevents cart click',html:'<button onclick="document.body.insertAdjacentHTML(\'beforeend\',\'<p>加入购物车成功</p>\')">加入购物车</button>',options:{count:'3'},mustReject:true},
  {name:'unconfirmed SKU prevents cart click',html:'<div class="skuItem"><li>1K</li><li>2K</li></div><button onclick="document.body.insertAdjacentHTML(\'beforeend\',\'<p>加入购物车成功</p>\')">加入购物车</button>',options:{sku:['1K']},mustReject:true}
 ];
 for(const s of scenarios){
  const context=await browser.newContext();
  await context.route('**/*',route=>route.fulfill({contentType:'text/html; charset=utf-8',body:'<html><title>fixture 1K resistor</title><body>'+s.html+'</body></html>'}));
  let observed={};
  const realNewPage=context.newPage.bind(context);
  context.newPage=async()=>{
   const page=await realNewPage();page.waitForTimeout=async()=>{};
   const close=page.close.bind(page);
   page.close=async()=>{observed=await page.evaluate(()=>({quantity:document.querySelector('#J_IptAmount')?.value,cartSuccess:document.body.innerText.includes('加入购物车成功')}));return close();};
   return page;
  };
  const userOpened=await context.newPage();
  await userOpened.goto('https://item.taobao.com/item.htm?id=123');
  active={source:'cdp',browser:{contexts:()=>[context],close:async()=>{
   const page=context.pages()[0];
   if(page) observed=await page.evaluate(()=>({quantity:document.querySelector('#J_IptAmount')?.value,cartSuccess:document.body.innerText.includes('加入购物车成功')}));
   return context.close();
  }}};
  let result,error;const logs=[];
  try{result=await runItemAction({action:'cart',item:'123',out,interactiveLogin:false,...s.options},{log:(name,payload)=>logs.push({name,payload})});}catch(e){error=e.message;}
  const pass=s.mustReject?Boolean(error):observed.quantity===s.expectedQuantity;
  results.push({name:s.name,pass,result,error,observed,logs});console.log(JSON.stringify(results.at(-1)));
 }
 await browser.close();fs.rmSync(out,{recursive:true,force:true});if(process.argv[2]) fs.writeFileSync(process.argv[2],JSON.stringify(results,null,2));
 if(results.some(x=>!x.pass)) process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1});
