// Yatra service worker: shows push notifications (plan ready, approval, booking, flight
// departing / landed) even when the app isn't open, and opens the right page when tapped.
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()))

self.addEventListener('push', (event) => {
  let data = {}
  try { data = event.data ? event.data.json() : {} } catch { data = { title: 'Yatra', body: event.data ? event.data.text() : '' } }
  event.waitUntil(self.registration.showNotification(data.title || 'Yatra', {
    body: data.body || '',
    icon: '/icon.svg',
    badge: '/icon.svg',
    tag: data.tag || 'yatra',
    renotify: true,
    data: { url: data.url || '/' },
  }))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const target = new URL(event.notification.data?.url || '/', self.location.origin).href
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    for (const client of windows) {
      if (new URL(client.url).origin === self.location.origin) { await client.focus(); return client.navigate(target) }
    }
    return self.clients.openWindow(target)
  })())
})
