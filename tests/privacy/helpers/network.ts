// Records every request a browser context makes, and plants a probe in each page that logs what
// request events cannot show: sockets, WebRTC and WebTransport channels, and loads that the page's
// Content Security Policy blocked before they reached the network.
import type { BrowserContext, Page } from '@playwright/test';

export type SeenRequest = { url: string; method: string; type: string };

export function recordRequests(context: BrowserContext) {
  const seen: SeenRequest[] = [];
  context.on('request', (r) => seen.push({ url: r.url(), method: r.method(), type: r.resourceType() }));
  return {
    all: (): SeenRequest[] => [...seen],
    /** A point in the record; `since(mark)` returns what came after it. */
    mark: (): number => seen.length,
    since: (mark: number): SeenRequest[] => seen.slice(mark),
  };
}

/** Requests that reach the network: everything except in-memory blob:, data: and about: URLs. */
export const onNetwork = (r: SeenRequest): boolean => !/^(about|blob|data):/i.test(r.url);

export type ProbeEntry = { kind: string; detail: string };

// Runs in the page before any of its own scripts. It must not refer to anything outside itself.
function probe(): void {
  const log: { kind: string; detail: string }[] = [];
  Object.defineProperty(window, '__solidMaskProbe', { value: log });
  const scope = window as unknown as Record<string, unknown>;
  for (const name of ['WebSocket', 'WebTransport', 'EventSource', 'RTCPeerConnection', 'webkitRTCPeerConnection']) {
    const original = scope[name];
    if (typeof original !== 'function') continue;
    scope[name] = new Proxy(original, {
      construct(target, args, newTarget) {
        log.push({ kind: name, detail: String(args[0] ?? '') });
        return Reflect.construct(target, args, newTarget);
      },
    });
  }
  document.addEventListener('securitypolicyviolation', (e) =>
    log.push({ kind: 'blocked by the Content Security Policy', detail: `${e.effectiveDirective} ${e.blockedURI}` }),
  );
}

export async function installProbe(context: BrowserContext): Promise<void> {
  await context.addInitScript(probe);
}

export async function probeLog(page: Page): Promise<ProbeEntry[]> {
  return page.evaluate(() => (window as unknown as { __solidMaskProbe?: { kind: string; detail: string }[] }).__solidMaskProbe ?? []);
}
