// service-worker.js — cachea la app y el último JSON conocido para poder
// abrir la página sin conexión (mostrando el último dato descargado).
// Estrategia: shell (html/css/js/iconos) cache-first; datos (JSON)
// network-first con fallback a caché si no hay red.

const CACHE = "regimen-tilt-v1";
const SHELL = [
  "./",
  "./index.html",
  "./manifest.json",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
];

self.addEventListener("install", (ev) => {
  ev.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (ev) => {
  ev.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (ev) => {
  const url = new URL(ev.request.url);
  const isData = url.pathname.endsWith("sistema_regimen_tilt.json");

  if (isData) {
    // datos: intenta red primero (para que se vea el dato más nuevo),
    // si falla (sin conexión) usa el último guardado en caché.
    ev.respondWith(
      fetch(ev.request)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(ev.request, copy));
          return res;
        })
        .catch(() => caches.match(ev.request))
    );
    return;
  }

  // shell: caché primero, red de respaldo
  ev.respondWith(
    caches.match(ev.request).then((cached) => cached || fetch(ev.request))
  );
});
