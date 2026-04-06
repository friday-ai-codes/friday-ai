import {
 getPushPublicKey,
 removePushSubscription,
 savePushSubscription,
} from '~/api/chat'
const webPushReady = ref(false)
let serviceWorkerRegistrationPromise: Promise<ServiceWorkerRegistration> | null = null
function isWebPushSupported: boolean {
 return typeof window !== 'undefined'
 && 'Notification' in window
 && 'serviceWorker' in navigator
 && 'PushManager' in window
}
function urlBase64ToArrayBuffer(base64String: string): ArrayBuffer {
 const padding = '='.repeat((4 - base64String.length % 4) % 4)
 const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
 const rawData = window.atob(base64)
 return Uint8Array.from([...rawData].map(char => char.charCodeAt(0))).buffer
}
async function ensureServiceWorker: Promise<ServiceWorkerRegistration> {
 if (serviceWorkerRegistrationPromise)
 return serviceWorkerRegistrationPromise
 serviceWorkerRegistrationPromise = navigator.serviceWorker.register('/sw.js')
 return serviceWorkerRegistrationPromise
}
function getSubscriptionKeys(subscription: PushSubscription): { p256dh: string, auth: string } {
 const p256dh = subscription.getKey('p256dh')
 const auth = subscription.getKey('auth')
 if (!p256dh || !auth)
 throw new Error('Push subscription keys 缺失')
 return {
 p256dh: btoa(String.fromCharCode(...new Uint8Array(p256dh))),
 auth: btoa(String.fromCharCode(...new Uint8Array(auth))),
 }
}
async function syncSubscription(subscription: PushSubscription): Promise<void> {
 const keys = getSubscriptionKeys(subscription)
 await savePushSubscription({
 endpoint: subscription.endpoint,
 keys,
 user_agent: navigator.userAgent,
 })
 webPushReady.value = true
}
async function enableWebPush: Promise<boolean> {
 if (!isWebPushSupported || Notification.permission !== 'granted') {
 webPushReady.value = false
 return false
 }
 try {
 const registration = await ensureServiceWorker
 const { public_key } = await getPushPublicKey
 let subscription = await registration.pushManager.getSubscription
 if (!subscription) {
 subscription = await registration.pushManager.subscribe({
 userVisibleOnly: true,
 applicationServerKey: urlBase64ToArrayBuffer(public_key),
 })
 }
 await syncSubscription(subscription)
 return true
 }
 catch {
 webPushReady.value = false
 return false
 }
}
async function requestAndEnableWebPush: Promise<boolean> {
 if (!isWebPushSupported) {
 webPushReady.value = false
 return false
 }
 if (Notification.permission === 'default') {
 const permission = await Notification.requestPermission
 if (permission !== 'granted') {
 webPushReady.value = false
 return false
 }
 }
 return enableWebPush
}
async function disableWebPush: Promise<void> {
 if (!isWebPushSupported)
 return
 const registration = await ensureServiceWorker
 const subscription = await registration.pushManager.getSubscription
 if (!subscription)
 return
 await removePushSubscription(subscription.endpoint).catch( => {})
 await subscription.unsubscribe.catch( => {})
 webPushReady.value = false
}
export function useWebPush {
 return {
 webPushReady,
 isWebPushSupported,
 requestAndEnableWebPush,
 enableWebPush,
 disableWebPush,
 }
}
