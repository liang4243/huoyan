#!/usr/bin/env node

const { Command } = require('commander');
const { collect } = require('./core/collector');
const { runItemAction } = require('./core/itemActions');
const { inspectProduct } = require('./core/productResearch');
const { selectSkuAndCollage } = require('./core/skuCollage');

function logEvent(name, payload) {
  console.log(`${name}: ${JSON.stringify(payload)}`);
  if (name === 'login_recovery_waiting_user') {
    console.log('>> 已弹出可见 Chrome 窗口，请在窗口中完成登录/安全验证；完成后采集会自动继续，无需关闭窗口（关掉窗口也会视为完成）。');
  }
  if (name === 'manual_clear_waiting') {
    console.log('>> 页面又出现登录/安全验证，请在当前 Chrome 窗口里处理一下（如拖动滑块），采集会自动继续。');
  }
}

async function collectCommand(options) {
  const result = await collect(options, { log: logEvent });

  console.log(`site: ${result.site}`);
  console.log(`page: ${result.page}`);
  console.log(`items: ${result.itemCount}`);
  if (result.outputs.jsonl) console.log(`jsonl: ${result.outputs.jsonl}`);
  if (result.outputs.markdown) console.log(`markdown: ${result.outputs.markdown}`);
  if (result.warning) console.log(`warning: ${result.warning}`);
}

async function itemActionCommand(action, options) {
  try {
    const result = await runItemAction({ ...options, action }, { log: logEvent });
    console.log(`ok: ${result.ok}`);
    console.log(`evidence: ${result.evidence}`);
    if (result.sku && result.sku.length) console.log(`sku: ${result.sku.join(' / ')}`);
    if (action === 'cart') console.log(`count: ${result.count}`);
    console.log(`title: ${result.title}`);
    if (!result.ok) process.exitCode = 4;
  } catch (error) {
    if (error.skuGroups) {
      console.log('skuGroups:');
      error.skuGroups.forEach((group, index) => {
        console.log(`  [${index}] ${group.label || '(dimension)'}: ${group.options.slice(0, 12).join(' | ')}${group.options.length > 12 ? ' ...' : ''}`);
      });
    }
    throw error;
  }
}

const program = new Command();

program
  .name('huoyan')
  .description('HuoYan: extract loaded shopping list items from an already-open Chrome page.')
  .version('0.1.0');

program
  .command('collect')
  .description('Collect items from the current loaded page via Chrome DevTools Protocol.')
  .option('--site <site>', 'auto/goofish/jd/taobao/1688/smzdm/pinduoduo', 'auto')
  .option('--keyword <keyword>', 'search keyword used for output names and item records')
  .option('--max <number>', 'maximum item count', '50')
  .option('--pages <number>', 'maximum result pages to collect, default 1', '1')
  .option('--cdp <url>', 'Chrome DevTools endpoint', 'http://127.0.0.1:9222')
  .option('--browser <mode>', 'cdp/launch/auto. Default cdp reuses an existing Chrome; launch and auto are explicit alternatives.', 'cdp')
  .option('--debug-browser', 'force a visible Chrome window when launching (visible is the default)')
  .option('--no-interactive-login', 'fail immediately when blocked by a login/verification page instead of opening a visible login window')
  .option('--login-timeout <seconds>', 'how long to wait for the manual login window', '300')
  .option('--edge-path <path>', 'Google Chrome executable path used by launch/auto')
  .option('--chrome-path <path>', 'legacy alias for the browser executable path')
  .option('--user-data-dir <dir>', 'browser profile directory used by --browser launch/auto fallback')
  .option('--reference-price <number>', 'reference second-hand average price')
  .option('--scroll <count>', 'auto: random 2–5 downward scrolls; integer: maximum count; 0 disables scrolling. Stop at bottom and scroll up a little.', 'auto')
  .option('--delay-min <ms>', 'minimum random pause before search and around pagination', '12000')
  .option('--delay-max <ms>', 'maximum random pause before search and around pagination', '25000')
  .option('--no-stop-on-verify', 'continue even if a login or verification page is detected')
  .option('--no-fail-on-blocked', 'export partial results instead of returning an error when blocked')
  .option('--out <dir>', 'output directory', 'data')
  .option('--format <formats>', 'jsonl,md', 'jsonl,md')
  .option('--open-search', 'reuse a site page, fill --keyword and click search before extraction')
  .option('--start-url <url>', 'reuse this search entry (e.g. shop page), fill keyword and submit its search form')
  .option('--login-popup <mode>', 'ignore/quick-enter/close. quick-enter tries the login iframe button, then falls back to close.', 'ignore')
  .action((options) => {
    collectCommand(options).catch((error) => {
      console.error(`Error: ${error.message}`);
      process.exitCode = error.exitCode || 1;
    });
  });

function attachItemActionOptions(cmd) {
  return cmd
    .option('--browser <mode>', 'cdp/launch/auto. Default cdp keeps product tabs alive.', 'cdp')
    .option('--debug-browser', 'force a visible Chrome window when launching (visible is the default)')
    .option('--no-interactive-login', 'fail immediately when blocked by a login/verification page instead of opening a visible login window')
    .option('--login-timeout <seconds>', 'how long to wait for the manual login window', '300')
    .option('--edge-path <path>', 'Google Chrome executable path used by launch/auto')
    .option('--chrome-path <path>', 'legacy alias for the browser executable path')
    .option('--user-data-dir <dir>', 'browser profile directory used by --browser launch/auto fallback');
}

program
  .command('cart')
  .description('Add a Taobao item to the cart: opens the item page, selects SKUs, sets quantity, clicks add-to-cart.')
  .requiredOption('--item <id-or-url>', 'taobao item id or item.htm URL')
  .option('--sku <values...>', 'SKU option texts, one per page dimension, in order')
  .option('--count <number>', 'quantity', '1')
  .option('--cdp <url>', 'Chrome DevTools endpoint', 'http://127.0.0.1:9222');
attachItemActionOptions(program.commands[program.commands.length - 1]);
program.commands[program.commands.length - 1].action((options) => {
  itemActionCommand('cart', options).catch((error) => {
    console.error(`Error: ${error.message.slice(0, 300)}`);
    process.exitCode = error.exitCode || 1;
  });
});

program
  .command('fav')
  .description('Favorite (collect) a Taobao item.')
  .requiredOption('--item <id-or-url>', 'taobao item id or item.htm URL')
  .option('--cdp <url>', 'Chrome DevTools endpoint', 'http://127.0.0.1:9222');
attachItemActionOptions(program.commands[program.commands.length - 1]);
program.commands[program.commands.length - 1].action((options) => {
  itemActionCommand('fav', options).catch((error) => {
    console.error(`Error: ${error.message.slice(0, 300)}`);
    process.exitCode = error.exitCode || 1;
  });
});

program.command('product')
  .description('Read a product using its existing tab or local cache; --fresh refreshes the original tab.')
  .requiredOption('--item <id-or-url>', 'product ID (Taobao) or supported detail URL')
  .option('--fresh', 'require fresh data; reload existing tab or reopen if closed')
  .option('--cdp <url>', 'Chrome DevTools endpoint', 'http://127.0.0.1:9222')
  .option('--out <dir>', 'local product mapping and snapshot directory', 'data')
  .option('--delay-min <ms>', 'minimum pause before opening or refreshing', '12000')
  .option('--delay-max <ms>', 'maximum pause before opening or refreshing', '25000')
  .action(options => inspectProduct(options, { log: logEvent })
    .then(result => console.log(JSON.stringify(result, null, 2)))
    .catch(error => { console.error(error.message); process.exitCode = error.exitCode || 1; }));

program.command('sku-images')
  .description('Select exact SKU options and create a product image collage without cart or checkout actions.')
  .requiredOption('--item <id-or-url>', 'Taobao/Tmall product ID or URL')
  .option('--sku <values...>', 'exact option text per multi-option SKU group')
  .option('--fresh', 'refresh existing product tab or explicitly reopen a closed tab')
  .option('--max-images <count>', 'maximum collage images (up to 12)', '8')
  .option('--cdp <url>', 'direct Chrome endpoint', 'http://127.0.0.1:9222')
  .option('--out <dir>', 'cache and collage directory', 'data')
  .action(options => selectSkuAndCollage(options).then(({ imageBase64, ...metadata }) => console.log(JSON.stringify(metadata, null, 2)))
    .catch(error => { console.error(error.message); process.exitCode = error.exitCode || 1; }));

program.parseAsync(process.argv);
