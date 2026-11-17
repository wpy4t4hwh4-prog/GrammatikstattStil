/* Research Hub Service Worker.
   Strategie: /api/* = network-first (Live-Daten frisch, Cache als Offline-Fallback nur bei GET);
   statische Assets = cache-first mit Runtime-Caching. Version bei Aenderungen erhoehen. */
const CACHE = 'research-hub-v1';
const PRECACHE = [
  './', 'index.html', 'manifest.webmanifest',
  'data/project.json', 'data/sample-data.js', 'data/templates.json',
  'icons/icon-192.png', 'icons/icon-512.png', 'icons/icon-180.png'
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
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
    e.respondWith(
      fetch(e.request).then(res => {
        if (e.request.method === 'GET' && res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then(c => c.put(e.request, copy));
        }
        return res;
      }).catch(() =>
        caches.match(e.request).then(cached => cached || new Response(
          JSON.stringify({ live: false, grund: 'offline (Service Worker)' }),
          { status: 200, headers: { 'Content-Type': 'application/json; charset=utf-8' } }
        ))
      )
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
