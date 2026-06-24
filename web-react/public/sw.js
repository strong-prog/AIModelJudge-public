// AIModelJudge — простой Service Worker для offline-кэширования static
const CACHE = "amj-v1";
const ASSETS = [
  "/app/",
  "/app/manifest.json",
  "/app/icon-192.png",
  "/app/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  // Не кэшируем API-запросы и SSE-стримы
  const url = new URL(event.request.url);
  if (url.pathname.startsWith("/chat") || url.pathname.startsWith("/model") ||
      url.pathname.startsWith("/health") || url.pathname.startsWith("/api")) {
    return;
  }
  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
  );
});

// Push-уведомления о Cron
self.addEventListener("push", (event) => {
  const data = event.data ? event.data.json() : {};
  const title = data.title || "AIModelJudge Cron";
  const options = {
    body: data.body || "Cron-задача завершена",
    icon: "/app/icon-192.png",
    tag: data.job_id || "cron",
    data: { url: data.url || "/app" },
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(
    clients.matchAll({ type: "window" }).then((clients) => {
      for (const client of clients) {
        if (client.url.includes("/app") && "focus" in client) {
          return client.focus();
        }
      }
      if (clients.openWindow) return clients.openWindow("/app");
    })
  );
});
