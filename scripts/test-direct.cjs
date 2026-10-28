const assert = require('node:assert/strict');
const http = require('node:http');
const net = require('node:net');
const { chromium } = require('playwright');
const { connectToEdge, getDefaultEdgePath, launchEdge, verifyDirectMode } = require('../src/core/browser');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
async function listen(server) {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  return server.address().port;
}
(async () => {
  const server = http.createServer((req, res) => res.end('direct-ok'));
  const webPort = await listen(server);
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'huoyan-direct-'));
  try {
    const launched = await launchEdge({ userDataDir: temp });
    try {
      assert.equal(launched.headless, false);
      const context = launched.browser.contexts()[0];
      const session = await context.browser().newBrowserCDPSession();
      await assert.rejects(session.send('Browser.getBrowserCommandLine'), /enable-automation/);
      assert.equal(await verifyDirectMode(session), true);
      await session.detach();
    } finally { await launched.browser.close(); }
    for (const direct of [false, true]) {
      const reserve = net.createServer();
      const port = await listen(reserve);
      await new Promise(resolve => reserve.close(resolve));
      const browser = await chromium.launch({ executablePath: getDefaultEdgePath(), headless: true,
        ignoreDefaultArgs: ['--enable-automation'],
        args: [`--remote-debugging-port=${port}`, '--proxy-server=http://127.0.0.1:9',
          '--host-resolver-rules=MAP direct.test 127.0.0.1', ...(direct ? ['--no-proxy-server'] : [])] });
      try {
        const context = await browser.newContext();
        const page = await context.newPage();
        if (!direct) {
          await assert.rejects(connectToEdge(`http://127.0.0.1:${port}`), /direct mode is not enabled/);
          await assert.rejects(page.goto(`http://direct.test:${webPort}/`, { timeout: 5000 }), /ERR_PROXY_CONNECTION_FAILED/);
          assert(!page.isClosed());
        } else {
          const attached = await connectToEdge(`http://127.0.0.1:${port}`);
          await attached.close();
          await page.goto(`http://direct.test:${webPort}/`);
          assert.equal(await page.locator('body').innerText(), 'direct-ok');
        }
      } finally { await browser.close(); }
    }
    console.log('PASS visible default with native automation behavior, launch direct flag, CDP rejects proxy session without closing tabs, direct flag bypasses explicit broken HTTP proxy');
  } finally {
    await new Promise(resolve => server.close(resolve));
    fs.rmSync(temp, { recursive: true, force: true });
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
