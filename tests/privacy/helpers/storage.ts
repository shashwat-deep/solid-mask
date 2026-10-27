// Lists everything the app's origin holds in the browser's storage and reports anything that is
// not one of the app's own files. A service worker may cache the app itself for offline use; it
// may not cache anything else.
import { createHash } from 'node:crypto';
import { readdir, readFile } from 'node:fs/promises';
import { join, relative, sep } from 'node:path';
import type { BrowserContext, Page } from '@playwright/test';
import { APP_DIST, APP_URL } from '../../env.ts';

type CacheEntry = { cache: string; url: string; sha256: string };

type StorageReport = {
  localStorage: string[];
  sessionStorage: string[];
  indexedDB: string[];
  cacheEntries: CacheEntry[];
  opfs: string[];
  documentCookie: string;
  /** Storage this browser does not offer, or refused to list, with the reason. */
  unavailable: string[];
};

function readStorage(page: Page): Promise<StorageReport> {
  return page.evaluate(async () => {
    const hex = (buffer: ArrayBuffer): string => [...new Uint8Array(buffer)].map((b) => b.toString(16).padStart(2, '0')).join('');
    const report = {
      localStorage: [] as string[],
      sessionStorage: [] as string[],
      indexedDB: [] as string[],
      cacheEntries: [] as { cache: string; url: string; sha256: string }[],
      opfs: [] as string[],
      documentCookie: document.cookie,
      unavailable: [] as string[],
    };
    for (let i = 0; i < localStorage.length; i++) report.localStorage.push(localStorage.key(i) ?? '');
    for (let i = 0; i < sessionStorage.length; i++) report.sessionStorage.push(sessionStorage.key(i) ?? '');
    try {
      report.indexedDB = (await indexedDB.databases()).map((d) => d.name ?? '(no name)');
    } catch (e) {
      report.unavailable.push(`IndexedDB: ${e}`);
    }
    try {
      for (const name of await caches.keys()) {
        const cache = await caches.open(name);
        for (const request of await cache.keys()) {
          const response = await cache.match(request);
          const body = response ? await response.arrayBuffer() : new ArrayBuffer(0);
          report.cacheEntries.push({ cache: name, url: request.url, sha256: hex(await crypto.subtle.digest('SHA-256', body)) });
        }
      }
    } catch (e) {
      report.unavailable.push(`Cache API: ${e}`);
    }
    try {
      const root = await navigator.storage.getDirectory();
      for await (const name of root.keys()) report.opfs.push(name);
    } catch (e) {
      report.unavailable.push(`origin private file system: ${e}`);
    }
    return report;
  });
}

/** The URL of every file in app/dist, mapped to its SHA-256. */
async function appFiles(): Promise<Map<string, string>> {
  const files = new Map<string, string>();
  const walk = async (dir: string): Promise<void> => {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) {
        await walk(path);
        continue;
      }
      const url = new URL(relative(APP_DIST, path).split(sep).join('/'), APP_URL).href;
      const hash = createHash('sha256').update(await readFile(path)).digest('hex');
      files.set(url, hash);
      if (url === `${APP_URL}index.html`) files.set(APP_URL, hash);
    }
  };
  await walk(APP_DIST).catch(() => undefined);
  return files;
}

/** One line per thing found in storage that is not the app's own; `unavailable` says what could not be checked. */
export async function storageProblems(page: Page, context: BrowserContext): Promise<{ problems: string[]; unavailable: string[] }> {
  const report = await readStorage(page);
  const own = await appFiles();
  const problems = [
    ...report.localStorage.map((key) => `localStorage key ${JSON.stringify(key)}`),
    ...report.sessionStorage.map((key) => `sessionStorage key ${JSON.stringify(key)}`),
    ...report.indexedDB.map((name) => `IndexedDB database ${JSON.stringify(name)}`),
    ...report.opfs.map((name) => `${JSON.stringify(name)} in the origin private file system`),
    ...report.cacheEntries
      .filter((e) => own.get(e.url) !== e.sha256)
      .map((e) => `Cache API entry ${e.url} (cache ${JSON.stringify(e.cache)}) is not one of the app's own files`),
    ...(await context.cookies()).map((c) => `cookie ${JSON.stringify(c.name)} for ${c.domain}`),
  ];
  if (report.documentCookie !== '') problems.push(`document.cookie is ${JSON.stringify(report.documentCookie)}`);
  return { problems, unavailable: report.unavailable };
}
