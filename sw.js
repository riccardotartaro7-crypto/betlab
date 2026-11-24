// Fa funzionare l'app anche offline: interfaccia dalla cache, dati sempre freschi se c'è rete.
const C = "betlab-v1";
const SHELL = ["./", "index.html", "manifest.json", "icon-192.png", "icon-512.png"];
self.addEventListener("install", e => { e.waitUntil(caches.open(C).then(c => c.addAll(SHELL))); self.skipWaiting(); });
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== C).map(k => caches.delete(k)))));
  self.clients.claim();
});
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;
  // dati e pagina: prima la rete, se manca uso l'ultima copia
  if (url.pathname.endsWith("data.json") || e.request.mode === "navigate") {
    e.respondWith(fetch(e.request).then(r => {
      const copy = r.clone(); caches.open(C).then(c => c.put(url.pathname.endsWith("data.json") ? "data.json" : e.request, copy));
      return r;
    }).catch(() => caches.match(url.pathname.endsWith("data.json") ? "data.json" : e.request)));
    return;
  }
  e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
});
