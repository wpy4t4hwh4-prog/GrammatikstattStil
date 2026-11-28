/* Research Hub Service Worker.
   Strategie: /api/* = network-only und NIEMALS cachen (Session-/Passwort-Modus: API-Antworten
   duerfen nicht im SW-Cache landen); /data/* = nur cachen ohne Token;
   statische Assets = cache-first mit Runtime-Caching. Version bei Aenderungen erhoehen. */
const CACHE = 'research-hub-v33'; // v33: SW-Update-Fix — SKIP_WAITING per Message + Navigationen mit cache:'no-store' (Pages-CDN max-age=600 umgehen)
// Token aktiv (URL ?token= oder sessionStorage) -> echte Daten (/data/*) nie cachen
const HAS_TOKEN = new URLSearchParams(location.search).has('token') || !!sessionStorage.getItem('hubToken');
const PRECACHE = [
  './', 'index.html', 'manifest.webmanifest',
  'data/project.json', 'data/sample-data.js', 'data/templates.json',
  'icons/icon-192.png', 'icons/icon-512.png', 'icons/icon-180.png', 'icons/icon-512-maskable.png'
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c =>
      // pro Item cachen: ein 403 (z. B. data/* mit Token) darf die Installation nicht killen
      Promise.all(PRECACHE.map(u => c.add(u).catch(() => {})))
    ).then(() => self.skipWaiting())
  );
});

// v33: Seite signalisiert SKIP_WAITING -> neuer SW sofort aktiv (sonst wartet er, bis alle Tabs zu sind)
self.addEventListener('message', e => {
  if (e.data && e.data.type === 'SKIP_WAITING') self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;

  if (url.pathname.startsWith('/api/')) {
    if (url.searchParams.has('token')) return; // Token-URLs nie cachen (Cache-Key waere token-abhaengig)
    // v31: API-Antworten NIEMALS cachen (Session-Cookie-Modus) — network-only, offline = 503
    e.respondWith(
      fetch(e.request).catch(() => new Response(
        JSON.stringify({ live: false, fehler: 'offline (Service Worker)', grund: 'offline (Service Worker)' }),
        { status: 503, headers: { 'Content-Type': 'application/json; charset=utf-8' } }
      ))
    );
    return;
  }

  if (url.pathname.startsWith('/data/')) {
    if (url.searchParams.has('token')) return; // Token-URLs nie cachen
    if (HAS_TOKEN) return; // mit Token: /data/* (echte Daten) nie cachen
    e.respondWith(
      fetch(e.request).then(res => {
        if (e.request.method === 'GET' && res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then(c => c.put(e.request, copy));
        }
        return res;
      }).catch(() => caches.match(e.request).then(cached => cached || new Response(
        JSON.stringify({ live: false, grund: 'offline (Service Worker)' }),
        { status: 200, headers: { 'Content-Type': 'application/json; charset=utf-8' } }
      )))
    );
    return;
  }

  // App-Shell: Navigationen network-first mit cache:'no-store' (HTTP-Cache/CDN umgehen, sonst
  // max-age=600 auf GitHub Pages -> alte Shell bis zu 10 min), Offline-Fallback auf gecachte index.html
  if (e.request.mode === 'navigate') {
    e.respondWith(
      fetch(e.request, { cache: 'no-store' }).then(res => {
        if (res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put('index.html', copy)); }
        return res;
      }).catch(() => caches.match('index.html').then(c => c || caches.match('./')))
    );
    return;
  }

  e.respondWith(
    caches.match(e.request).then(cached => cached || fetch(e.request).then(res => {
      if (res.ok && e.request.method === 'GET') {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, copy));
      }
      return res;
    }).catch(() => caches.match('index.html')))
  );
});
