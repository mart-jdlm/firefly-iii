/* Cairn service worker: the app shell works offline, and the last figures are kept to be shown
   (with a banner) when the server cannot be reached. Set CACHE_API to false to keep no figures
   on the device. The assistant (/chat) and every write are never touched. */
const SHELL = 'cairn-shell-v3', DATA = 'cairn-data-v1', CACHE_API = true;
const MODULES = ['api', 'assets', 'budget', 'chat', 'consts', 'dom', 'edit', 'format', 'future', 'invest', 'logic', 'main', 'overview', 'recurring', 'state', 'transactions'];
const PRECACHE = ['/', '/app.css', ...MODULES.map(m => `/js/${m}.js`), '/chart.js', '/logo.svg', '/favicon.svg', '/manifest.webmanifest', '/icon-192.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(SHELL).then(c => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== SHELL && k !== DATA).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

const dataKey = url => { const u = new URL(url); u.searchParams.delete('refresh'); return u.pathname + u.search; };

async function networkFirst(request) {
  const key = dataKey(request.url);
  try {
    const response = await fetch(request);
    if (response.ok) (await caches.open(DATA)).put(key, response.clone());
    return response;
  } catch (err) {
    const hit = await (await caches.open(DATA)).match(key);
    if (!hit) throw err;
    const headers = new Headers(hit.headers);
    headers.set('X-From-Cache', '1');
    return new Response(await hit.blob(), { status: 200, headers });
  }
}

// The app's own code (page, styles, modules) is fetched from the network first, so a deploy never
// mixes old and new modules; the cached copy is only the offline fallback.
async function appNetworkFirst(request) {
  const cache = await caches.open(SHELL);
  try {
    const response = await fetch(request);
    if (response.ok) cache.put(request, response.clone());
    return response;
  } catch (err) {
    const hit = await cache.match(request, { ignoreSearch: true });
    if (!hit) throw err;
    return hit;
  }
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(SHELL);
  const hit = await cache.match(request, { ignoreSearch: true });
  const update = fetch(request).then(r => { if (r.ok) cache.put(request, r.clone()); return r; });
  if (hit) { update.catch(() => {}); return hit; }
  return update;
}

self.addEventListener('fetch', e => {
  const r = e.request, u = new URL(r.url);
  if (r.method !== 'GET' || u.origin !== self.location.origin || u.pathname.startsWith('/chat') || u.pathname === '/healthz') return;
  if (u.pathname.startsWith('/api/')) { if (CACHE_API) e.respondWith(networkFirst(r)); return; }
  if (u.pathname === '/' || u.pathname === '/app.css' || u.pathname.startsWith('/js/')) { e.respondWith(appNetworkFirst(r)); return; }
  e.respondWith(staleWhileRevalidate(r));
});
