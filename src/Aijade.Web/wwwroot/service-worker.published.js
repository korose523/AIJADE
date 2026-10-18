// Published: cache the app shell (the generated asset manifest) for offline start; the API is never cached.
self.importScripts('./service-worker-assets.js');
const cacheName = `aijade-${self.assetsManifest.version}`;
const include = [/\.dll$/, /\.pdb$/, /\.wasm/, /\.html/, /\.js$/, /\.json$/, /\.css$/, /\.woff2?$/, /\.png$/, /\.ico$/, /\.webmanifest$/];
self.addEventListener('install', e => e.waitUntil((async () => {
  const assets = self.assetsManifest.assets.filter(a => include.some(p => p.test(a.url)))
    .map(a => new Request(a.url, { integrity: a.hash, cache: 'no-cache' }));
  await (await caches.open(cacheName)).addAll(assets);
})()));
self.addEventListener('activate', e => e.waitUntil((async () => {
  for (const key of await caches.keys()) if (key.startsWith('aijade-') && key !== cacheName) await caches.delete(key);
})()));
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET' || new URL(e.request.url).pathname.startsWith('/api/')) return;
  e.respondWith((async () => {
    const isNavigation = e.request.mode === 'navigate';
    const cached = await (await caches.open(cacheName)).match(isNavigation ? 'index.html' : e.request);
    return cached || fetch(e.request);
  })());
});
