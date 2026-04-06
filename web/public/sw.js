globalThis.addEventListener('install', (event) => {
 event.waitUntil(globalThis.skipWaiting)
})
globalThis.addEventListener('activate', (event) => {
 event.waitUntil(globalThis.clients.claim)
})
async function shouldSuppressNotification {
 const clients = await globalThis.clients.matchAll({
 type: 'window',
 includeUncontrolled: true,
 })
 return clients.some(client => client.focused)
}
globalThis.addEventListener('push', (event) => {
 let payload = {}
 try {
 payload = event.data ? event.data.json: {}
 }
 catch {
 payload = {
 title: 'Friday AI',
 body: event.data ? event.data.text: '',
 }
 }
 event.waitUntil((async => {
 if (await shouldSuppressNotification)
 return
 await globalThis.registration.showNotification(payload.title || 'Friday AI', {
 body: payload.body || '',
 icon: payload.icon || '/vite.svg',
 tag: payload.tag || 'friday-chat',
 data: payload,
 })
 }))
})
globalThis.addEventListener('notificationclick', (event) => {
 event.notification.close
 event.waitUntil((async => {
 const targetUrl = new URL(event.notification.data?.url || '/', globalThis.location.origin).toString
 const clients = await globalThis.clients.matchAll({
 type: 'window',
 includeUncontrolled: true,
 })
 for (const client of clients) {
 if ('navigate' in client)
 await client.navigate(targetUrl)
 if ('focus' in client)
 return client.focus
 }
 return globalThis.clients.openWindow(targetUrl)
 }))
})
