// Serves app/dist the way GitHub Pages does: under /solid-mask/, as static files, with no
// cross-origin isolation headers. Until app/dist exists every app path is a 404, so each
// privacy test fails at its first step instead of passing on an empty page.
import { readFile } from 'node:fs/promises';
import { createServer, type ServerResponse } from 'node:http';
import { extname, join, normalize } from 'node:path';
import { APP_DIST, BASE_PATH, PORT } from './env.ts';

const TYPES: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json',
  '.webmanifest': 'application/manifest+json',
  '.wasm': 'application/wasm',
  '.onnx': 'application/octet-stream',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.txt': 'text/plain; charset=utf-8',
};

function notFound(res: ServerResponse): void {
  res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' }).end('Not found');
}

createServer(async (req, res) => {
  const url = new URL(req.url ?? '/', 'http://localhost');
  // Playwright polls this to know the server is up, whether or not there is an app to serve.
  if (url.pathname === '/__health') return void res.writeHead(200).end('ok');
  if (url.pathname === BASE_PATH.slice(0, -1)) return void res.writeHead(301, { Location: BASE_PATH }).end();
  if ((req.method !== 'GET' && req.method !== 'HEAD') || !url.pathname.startsWith(BASE_PATH)) return notFound(res);

  let path: string;
  try {
    path = decodeURIComponent(url.pathname.slice(BASE_PATH.length));
  } catch {
    return notFound(res);
  }
  if (path === '' || path.endsWith('/')) path += 'index.html';
  const file = normalize(join(APP_DIST, path));
  if (!file.startsWith(APP_DIST)) return notFound(res);

  try {
    const body = await readFile(file);
    res.writeHead(200, {
      'Content-Type': TYPES[extname(file)] ?? 'application/octet-stream',
      'Cache-Control': 'no-store',
      'X-Content-Type-Options': 'nosniff',
    });
    res.end(req.method === 'HEAD' ? undefined : body);
  } catch {
    notFound(res);
  }
}).listen(PORT, '127.0.0.1');
