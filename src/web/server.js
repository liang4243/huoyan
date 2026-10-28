#!/usr/bin/env node
const http = require('http');
const path = require('path');
const fs = require('fs-extra');
const { getBatchItems, getReport, listBatches } = require('./outputStore');

const publicDir = path.join(__dirname, 'public');

function parseArgs(argv) {
  const args = {
    port: 8787,
    host: '127.0.0.1',
    outDir: path.resolve(process.cwd(), 'data')
  };

  for (let index = 2; index < argv.length; index += 1) {
    const value = argv[index];
    const next = argv[index + 1];
    if (value === '--port' && next) {
      args.port = Number.parseInt(next, 10) || args.port;
      index += 1;
    } else if (value === '--host' && next) {
      args.host = next;
      index += 1;
    } else if (value === '--out' && next) {
      args.outDir = path.resolve(process.cwd(), next);
      index += 1;
    }
  }

  return args;
}

function sendJson(response, statusCode, value) {
  const body = JSON.stringify(value);
  response.writeHead(statusCode, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store'
  });
  response.end(body);
}

function sendText(response, statusCode, text, contentType = 'text/plain; charset=utf-8') {
  response.writeHead(statusCode, {
    'content-type': contentType,
    'cache-control': 'no-store'
  });
  response.end(text);
}

function getStaticContentType(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === '.html') return 'text/html; charset=utf-8';
  if (ext === '.css') return 'text/css; charset=utf-8';
  if (ext === '.js') return 'application/javascript; charset=utf-8';
  if (ext === '.svg') return 'image/svg+xml';
  return 'application/octet-stream';
}

async function serveStatic(requestUrl, response) {
  const pathname = decodeURIComponent(requestUrl.pathname);
  const relativePath = pathname === '/' ? 'index.html' : pathname.replace(/^\/+/, '');
  const filePath = path.resolve(publicDir, relativePath);
  const publicRoot = path.resolve(publicDir);

  if (!filePath.startsWith(`${publicRoot}${path.sep}`) && filePath !== publicRoot) {
    sendText(response, 403, 'Forbidden');
    return;
  }

  if (!(await fs.pathExists(filePath)) || (await fs.stat(filePath)).isDirectory()) {
    sendText(response, 404, 'Not found');
    return;
  }

  const content = await fs.readFile(filePath);
  response.writeHead(200, {
    'content-type': getStaticContentType(filePath),
    'cache-control': 'no-store'
  });
  response.end(content);
}

async function handleApi(requestUrl, response, outDir) {
  if (requestUrl.pathname === '/api/batches') {
    sendJson(response, 200, {
      ok: true,
      outDir,
      batches: await listBatches(outDir)
    });
    return;
  }

  if (requestUrl.pathname === '/api/items') {
    const file = requestUrl.searchParams.get('file');
    if (!file) {
      sendJson(response, 400, { ok: false, error: 'Missing file parameter.' });
      return;
    }
    const result = await getBatchItems(outDir, file);
    sendJson(response, 200, { ok: true, ...result });
    return;
  }

  if (requestUrl.pathname === '/api/report') {
    const file = requestUrl.searchParams.get('file');
    if (!file) {
      sendJson(response, 400, { ok: false, error: 'Missing file parameter.' });
      return;
    }
    sendText(response, 200, await getReport(outDir, file), 'text/markdown; charset=utf-8');
    return;
  }

  sendJson(response, 404, { ok: false, error: 'Unknown API route.' });
}

function createServer(options) {
  return http.createServer(async (request, response) => {
    try {
      const requestUrl = new URL(request.url, `http://${request.headers.host || options.host}`);
      if (requestUrl.pathname.startsWith('/api/')) {
        await handleApi(requestUrl, response, options.outDir);
      } else {
        await serveStatic(requestUrl, response);
      }
    } catch (error) {
      sendJson(response, 500, {
        ok: false,
        error: error.message || String(error)
      });
    }
  });
}

if (require.main === module) {
  const options = parseArgs(process.argv);
  const server = createServer(options);
  server.listen(options.port, options.host, () => {
    console.log(`HuoYan web dashboard: http://${options.host}:${options.port}`);
    console.log(`Output directory: ${options.outDir}`);
  });
}

module.exports = {
  createServer,
  parseArgs
};
