/* Network Magic — servis çalışanı (service worker)
   Amaç: telefonda "uygulama" olarak kurulabilmek ve bağlantı koptuğunda boş ekran yerine
   son açılan arayüzü göstermek. API yanıtları önbelleğe alınmaz: veriler her zaman canlıdır. */
"use strict";

const CACHE = "network-magic-shell-v2";
const SHELL = ["/", "/manifest.webmanifest", "/static/img/favicon.svg", "/static/img/icon-192.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  // Canlı veri, dosya indirme ve misafir sayfaları asla önbellekten gelmez
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/share/") || url.pathname.startsWith("/guest/")) return;

  // Ağ öncelikli: güncel sürüm her zaman ağdan; ağ yoksa son kopya
  event.respondWith(
    fetch(req)
      .then((res) => {
        if (res.ok && (url.pathname === "/" || url.pathname.startsWith("/static/"))) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return res;
      })
      .catch(() => caches.match(req).then((hit) => hit || (req.mode === "navigate" ? caches.match("/") : undefined)))
  );
});
