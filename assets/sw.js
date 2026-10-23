/* Service worker (served at /sw.js): lets the dashboard install as an app and open offline with the
   last numbers it saw. Assets carry ?v=<mtime>, so they come from the cache first; the page and
   data.json come from the network, and from the cache only when offline. API calls, sign-in and the
   public kit pages are never cached. Signing out clears the cache (Clear-Site-Data on /logout). */
const CACHE = 'sj-1';

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});

async function fromCacheFirst(req) {
  const cache = await caches.open(CACHE);
  const hit = await cache.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok) {
    // keep one version of each file: drop the copies with an older ?v=
    const path = new URL(req.url).pathname;
    (await cache.keys()).filter((k) => new URL(k.url).pathname === path).forEach((k) => cache.delete(k));
    cache.put(req, res.clone());
  }
  return res;
}

async function fromNetworkFirst(req) {
  try {
    const res = await fetch(req);
    if (res.ok && !res.redirected) {
      const copy = res.clone();
      caches.open(CACHE).then((c) => c.put(req, copy));
    }
    return res;
  } catch (err) {
    const hit = await caches.match(req);
    if (hit) return hit;
    throw err;
  }
}

self.addEventListener('fetch', (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== self.location.origin) return;
  const p = url.pathname;
  if (p.startsWith('/assets/')) e.respondWith(fromCacheFirst(req));
  else if (p === '/' || p === '/data/data.json') e.respondWith(fromNetworkFirst(req));
});
