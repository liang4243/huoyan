const os = require('os');
const path = require('path');
const fs = require('fs-extra');
const { execFile } = require('node:child_process');
const { promisify } = require('node:util');
const execFileAsync = promisify(execFile);
const { chromium } = require('playwright');
const { randomInteger, waitRandom } = require('./pacing');

const DEFAULT_PROFILE_DIR = path.join(
  process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local'),
  'HuoYan',
  'ChromeCdpProfile'
);

async function connectToChrome(cdpEndpoint) {
  const browser = await chromium.connectOverCDP(cdpEndpoint);
  try {
    const session = await browser.newBrowserCDPSession();
    try {
      const version = await session.send('Browser.getVersion');
      if (!/^Chrome\//.test(version.product)) {
        throw new Error(`Expected Google Chrome but connected to ${version.product}. Use npm run chrome:cdp and port 9222.`);
      }
      if (!await verifyDirectMode(session)) {
        throw new Error('HuoYan refuses this Chrome session because direct mode is not enabled. Restart it with npm run chrome:cdp.');
      }
    } finally { await session.detach(); }
    return browser;
  } catch (error) {
    await browser.close();
    throw error;
  }
}

async function verifyDirectMode(session) {
  try {
    const { arguments: args } = await session.send('Browser.getBrowserCommandLine');
    return args.includes('--no-proxy-server');
  } catch {
    // Chrome exposes that command only with --enable-automation, which displays
    // an infobar. Read the actual CDP browser process instead; do not alter DOM features.
    if (process.platform !== 'win32') throw new Error('Cannot verify Chrome direct mode on this operating system.');
    const { processInfo } = await session.send('SystemInfo.getProcessInfo');
    const pid = processInfo.find(item => item.type === 'browser')?.id;
    if (!Number.isSafeInteger(pid) || pid <= 0) throw new Error('Cannot identify the Chrome browser process.');
    const { stdout } = await execFileAsync('powershell.exe', ['-NoProfile', '-Command',
      `$OutputEncoding=[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); Get-CimInstance Win32_Process -Filter 'ProcessId=${pid}' | Select-Object Name,CommandLine | ConvertTo-Json -Compress`
    ], { windowsHide: true, timeout: 10000, encoding: 'utf8' });
    const browserProcess = JSON.parse(stdout.replace(/^\uFEFF/, ''));
    if (browserProcess.Name?.toLowerCase() !== 'chrome.exe' || !browserProcess.CommandLine) throw new Error('Cannot verify the Chrome browser process.');
    return /(?:^|\s)--no-proxy-server(?:\s|$)/.test(browserProcess.CommandLine);
  }
}

function getDefaultChromePath() {
  if (process.platform !== 'win32') return undefined;
  return [
    'C:/Program Files/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
    path.join(process.env.LOCALAPPDATA || '', 'Google/Chrome/Application/chrome.exe')
  ].find(candidate => fs.existsSync(candidate));
}

function createBrowserFromPersistentContext(context) {
  return {
    contexts() {
      return [context];
    },
    async newContext() {
      return context;
    },
    async close() {
      await context.close();
    }
  };
}

async function launchChrome(options = {}) {
  const headless = options.debugBrowser ? false : options.headless === true;
  const executablePath = options.chromePath || options.edgePath || getDefaultChromePath();
  // Use the same persistent profile as the visible CDP window. If it is already
  // open, connect through CDP instead of creating a different environment.
  const userDataDir = options.userDataDir
    ? path.resolve(options.userDataDir)
    : DEFAULT_PROFILE_DIR;

  await fs.ensureDir(userDataDir);

  const context = await chromium.launchPersistentContext(userDataDir, {
    headless,
    executablePath,
    channel: executablePath ? undefined : 'chrome',
    // Adapter-level overrides (e.g. Pinduoduo needs a mobile UA and viewport)
    // win over the headless defaults.
    userAgent: options.userAgent,
    viewport: options.viewport || (headless ? { width: 1365, height: 900 } : null),
    isMobile: options.isMobile,
    hasTouch: options.hasTouch,
    ignoreDefaultArgs: ['--enable-automation'],
    args: [
      '--no-proxy-server',
      '--no-first-run',
      '--no-default-browser-check'
    ]
  });

  return {
    browser: createBrowserFromPersistentContext(context),
    source: 'launch',
    headless,
    executablePath: executablePath || 'google-chrome',
    userDataDir
  };
}

async function acquireBrowser(options = {}) {
  const provider = options.provider || process.env.HUOYAN_BROWSER_PROVIDER || 'chrome';
  if (provider !== 'chrome') throw new Error('HuoYan now uses Chrome. Remove the old browser provider override.');
  const browserMode = options.browserMode || options.browser || 'launch';
  const cdpEndpoint = options.cdp || 'http://127.0.0.1:9222';

  if (!['cdp', 'launch', 'auto'].includes(browserMode)) {
    throw new Error(`Invalid browser mode: ${browserMode}. Use cdp, launch, or auto.`);
  }

  if (browserMode === 'launch') {
    return launchChrome(options);
  }

  try {
    const browser = await connectToChrome(cdpEndpoint);
    return {
      browser,
      source: 'cdp',
      direct: true,
      cdpEndpoint
    };
  } catch (error) {
    if (browserMode !== 'auto') {
      error.message = `Failed to connect to Chrome CDP at ${cdpEndpoint}. Run npm run chrome:cdp, or use --browser launch/auto. Original error: ${error.message}`;
      throw error;
    }

    return launchChrome(options);
  }
}

async function getOpenPages(browser) {
  const pages = [];
  for (const context of browser.contexts()) {
    pages.push(...context.pages());
  }
  return pages;
}

async function waitForPageReady(page) {
  try {
    await page.waitForLoadState('domcontentloaded', { timeout: 5000 });
  } catch {
    // The user may already be on a long-lived hydrated page. Continue with the current DOM.
  }
}

async function scrollPage(page, count = 'auto') {
  const scrollCount = count === 'auto' ? randomInteger(2, 5) : Math.max(0, Number.parseInt(count, 10) || 0);
  const steps = [];
  const state = () => page.evaluate(() => {
    const root = document.scrollingElement || document.documentElement;
    return { top: root.scrollTop, height: Math.max(root.scrollHeight, document.documentElement.scrollHeight), viewport: window.innerHeight };
  });
  const atBottom = value => value.top >= Math.max(0, value.height - value.viewport) - 2;
  const move = async (direction, screenPercent, current) => {
    const target = Math.max(0, Math.min(current.height - current.viewport,
      current.top + (direction === 'down' ? 1 : -1) * current.viewport * screenPercent / 100));
    if (Math.abs(target - current.top) < 2) return false;
    await page.evaluate(top => window.scrollTo({ top, behavior: 'smooth' }), target);
    try {
      await page.waitForFunction(top => Math.abs((document.scrollingElement || document.documentElement).scrollTop - top) <= 2,
        target, { timeout: 2000 });
    } catch { /* A layout change may shift the target. Inspect the actual position below. */ }
    const waitMs = await waitRandom(page, 350, 800);
    const after = await state();
    steps.push({ direction, screenPercent, waitMs, from: current.top, to: after.top });
    return Math.abs(after.top - current.top) >= 2;
  };
  let current = await state();
  let reachedBottom = atBottom(current);
  for (let index = 0; index < scrollCount; index += 1) {
    if (reachedBottom) break;
    const screenPercent = randomInteger(50, 250);
    const moved = await move('down', screenPercent, current);
    current = await state();
    reachedBottom = atBottom(current);
    if (!moved) break;
  }
  if (scrollCount > 0 && reachedBottom && current.top > 2) {
    await move('up', randomInteger(20, 50), current);
  }
  return { plannedCount: scrollCount, count: steps.filter(step => step.direction === 'down').length, reachedBottom, steps };
}

module.exports = {
  verifyDirectMode,
  acquireBrowser,
  connectToChrome,
  getDefaultChromePath,
  connectToEdge: connectToChrome,
  getDefaultEdgePath: getDefaultChromePath,
  getOpenPages,
  launchChrome,
  launchEdge: launchChrome,
  scrollPage,
  waitForPageReady
};
