/* Push notifications. Kept deliberately small: a service worker that does more than it must
   is a service worker that ships stale code to every visitor. */

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    data = { body: event.data ? event.data.text() : "" };
  }

  event.waitUntil(
    self.registration.showNotification(data.title || "Encar Europe", {
      body: data.body || "",
      icon: "/icons/icon-192.png",
      badge: "/icons/icon-192.png",
      data: { url: data.url || "/" },
      tag: data.tag || "encareurope",
      // An outage alert has to survive being ignored: it stays on screen until it is
      // touched, it re-alerts when a reminder arrives under the same tag, and it buzzes.
      // Everything else keeps the quiet default.
      requireInteraction: Boolean(data.require_interaction),
      renotify: Boolean(data.renotify),
      vibrate: data.vibrate || undefined,
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL(
    (event.notification.data && event.notification.data.url) || "/",
    self.location.origin
  ).href;

  event.waitUntil(
    self.clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((list) => {
        // Reuse a tab that is already open rather than piling up windows.
        const open = list.find((client) => client.url.startsWith(self.location.origin));
        if (open) return open.focus().then(() => open.navigate(target));
        return self.clients.openWindow(target);
      })
  );
});
