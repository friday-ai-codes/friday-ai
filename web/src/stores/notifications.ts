/**
 * 消息中心 store（站内信通知 + 系统公告）。
 *
 * 统一维护两类消息：
 * - 站内信通知 `notifications`（反馈回复/状态变更，按收件人落库）；
 * - 系统公告 `announcements`（管理员广播，受众判定 + 按用户已读）。
 *
 * 二者通过同一个 `ws/notifications/` WebSocket 实时接收（鉴权由 HTTP-only cookie JWT 在
 * 握手时自动携带，见后端 JWTCookieAuthMiddleware）。WS 断线指数退避重连，REST 作为
 * 首屏/兜底拉取。铃铛与消息中心消费 `feed`（两类合并、按时间倒序），`totalUnread` 为合计未读。
 */

import type { UserAnnouncement } from '~/types/announcement'
import type { AppNotification } from '~/types/notification'
import { defineStore } from 'pinia'
import { announcementsApi } from '~/api/announcements'
import { notificationsApi } from '~/api/notifications'

export type NotificationWsStatus = 'connecting' | 'connected' | 'reconnecting' | 'disconnected'

/** 铃铛/消息中心合并展示的统一条目。 */
export interface FeedItem {
  id: string
  kind: 'notification' | 'announcement'
  type: string
  title: string
  body: string
  link: string
  is_read: boolean
  created_at: string
}

const MAX_RETRIES = 10

export const useNotificationsStore = defineStore('notifications', () => {
  // 站内信
  const notifications = ref<AppNotification[]>([])
  const unreadCount = ref(0)
  // 系统公告
  const announcements = ref<UserAnnouncement[]>([])
  const unreadAnnouncements = ref(0)
  // 待弹窗公告队列（popup 模式 + 未读，登录后/实时推送时填充）
  const popupQueue = ref<UserAnnouncement[]>([])

  const loading = ref(false)
  const wsStatus = ref<NotificationWsStatus>('disconnected')

  let ws: WebSocket | null = null
  let retryCount = 0
  let retryTimer: ReturnType<typeof setTimeout> | null = null

  // ============================================================ 合并视图

  const totalUnread = computed(() => unreadCount.value + unreadAnnouncements.value)

  const feed = computed<FeedItem[]>(() => {
    const a: FeedItem[] = notifications.value.map(n => ({
      id: n.id,
      kind: 'notification',
      type: n.type,
      title: n.title,
      body: n.body,
      link: n.link,
      is_read: n.is_read,
      created_at: n.created_at,
    }))
    const b: FeedItem[] = announcements.value.map(n => ({
      id: n.id,
      kind: 'announcement',
      type: 'system',
      title: n.title,
      body: n.body,
      link: n.link,
      is_read: n.is_read,
      created_at: n.created_at,
    }))
    return [...a, ...b].sort((x, y) => (y.created_at || '').localeCompare(x.created_at || ''))
  })

  // ============================================================ 合并拉取

  /** 铃铛/消息中心打开时一次性拉取两类消息。 */
  async function fetchFeed(unread = false) {
    loading.value = true
    try {
      await Promise.allSettled([
        fetchNotifications(unread),
        fetchAnnouncements(unread),
      ])
    }
    finally {
      loading.value = false
    }
  }

  // ============================================================ 站内信

  async function fetchNotifications(unread = false) {
    const resp = await notificationsApi.list({ unread, limit: 50 })
    notifications.value = resp.items
    unreadCount.value = resp.unread
  }

  async function fetchUnreadCount() {
    unreadCount.value = await notificationsApi.unreadCount()
  }

  async function markRead(id: string) {
    const updated = await notificationsApi.markRead(id)
    const idx = notifications.value.findIndex(n => n.id === id)
    if (idx !== -1)
      notifications.value[idx] = updated
    await fetchUnreadCount()
  }

  async function markAllRead() {
    await notificationsApi.markAllRead()
    const now = new Date().toISOString()
    notifications.value = notifications.value.map(n =>
      n.is_read ? n : { ...n, is_read: true, read_at: now },
    )
    unreadCount.value = 0
  }

  function prependNotification(notification: AppNotification) {
    if (notifications.value.some(n => n.id === notification.id))
      return
    notifications.value.unshift(notification)
    if (notifications.value.length > 100)
      notifications.value.splice(100)
  }

  // ============================================================ 系统公告

  async function fetchAnnouncements(unreadOnly = false) {
    const resp = await announcementsApi.list(unreadOnly)
    announcements.value = resp.items
    unreadAnnouncements.value = resp.unread
  }

  async function fetchAnnouncementUnreadCount() {
    unreadAnnouncements.value = await announcementsApi.unreadCount()
  }

  /** 拉取需要弹窗的公告，填入弹窗队列（登录后调用）。 */
  async function fetchPopupAnnouncements() {
    const items = await announcementsApi.popup()
    for (const it of items) enqueuePopup(it)
  }

  function enqueuePopup(item: UserAnnouncement) {
    if (item.is_read)
      return
    if (popupQueue.value.some(p => p.id === item.id))
      return
    popupQueue.value.push(item)
  }

  function dismissPopup(id: string) {
    popupQueue.value = popupQueue.value.filter(p => p.id !== id)
  }

  async function markAnnouncementRead(id: string) {
    await announcementsApi.markRead(id).catch(() => {})
    const idx = announcements.value.findIndex(n => n.id === id)
    if (idx !== -1 && !announcements.value[idx].is_read) {
      announcements.value[idx] = {
        ...announcements.value[idx],
        is_read: true,
        read_at: new Date().toISOString(),
      }
      unreadAnnouncements.value = Math.max(0, unreadAnnouncements.value - 1)
    }
    dismissPopup(id)
  }

  async function markAllAnnouncementsRead() {
    const unread = announcements.value.filter(n => !n.is_read)
    await Promise.allSettled(unread.map(n => announcementsApi.markRead(n.id)))
    const now = new Date().toISOString()
    announcements.value = announcements.value.map(n =>
      n.is_read ? n : { ...n, is_read: true, read_at: now },
    )
    unreadAnnouncements.value = 0
  }

  function prependAnnouncement(item: UserAnnouncement) {
    if (announcements.value.some(n => n.id === item.id))
      return
    announcements.value.unshift(item)
    if (!item.is_read)
      unreadAnnouncements.value += 1
    if (announcements.value.length > 100)
      announcements.value.splice(100)
  }

  // ============================================================ WebSocket

  function getWsUrl(): string {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${location.host}/ws/notifications/`
  }

  function handleMessage(raw: string) {
    let msg: any
    try {
      msg = JSON.parse(raw)
    }
    catch {
      return
    }
    if (msg.type === 'unread_count') {
      if (typeof msg.unread_count === 'number')
        unreadCount.value = msg.unread_count
    }
    else if (msg.type === 'notification' && msg.notification) {
      prependNotification(msg.notification as AppNotification)
      if (typeof msg.unread_count === 'number')
        unreadCount.value = msg.unread_count
      else
        unreadCount.value += 1
    }
    else if (msg.type === 'announcement' && msg.announcement) {
      const item = msg.announcement as UserAnnouncement
      prependAnnouncement(item)
      // popup 模式且未读：实时弹窗
      if (item.notify_mode === 'popup')
        enqueuePopup(item)
    }
  }

  function connect() {
    if (ws && ws.readyState <= WebSocket.OPEN)
      return
    wsStatus.value = retryCount > 0 ? 'reconnecting' : 'connecting'
    ws = new WebSocket(getWsUrl())

    ws.onopen = () => {
      wsStatus.value = 'connected'
      retryCount = 0
    }
    ws.onmessage = (e: MessageEvent) => handleMessage(e.data)
    ws.onclose = (e: CloseEvent) => {
      ws = null
      wsStatus.value = 'disconnected'
      // 4401 = 未认证，不重连（等用户登录后由 init 再次触发）
      if (e.code === 4401)
        return
      scheduleReconnect()
    }
    ws.onerror = () => {
      // onclose 会处理重连
    }
  }

  function scheduleReconnect() {
    if (retryCount >= MAX_RETRIES)
      return
    const delay = Math.min(1000 * 2 ** retryCount, 30000)
    retryCount++
    wsStatus.value = 'reconnecting'
    retryTimer = setTimeout(connect, delay)
  }

  function disconnect() {
    if (retryTimer)
      clearTimeout(retryTimer)
    retryTimer = null
    retryCount = 0
    ws?.close()
    ws = null
    wsStatus.value = 'disconnected'
  }

  /** 登录后初始化：拉取未读数 + 弹窗公告 + 建立 WS。 */
  async function init() {
    await Promise.allSettled([
      fetchUnreadCount(),
      fetchAnnouncementUnreadCount(),
      fetchPopupAnnouncements(),
    ])
    connect()
  }

  /** 登出时清理：断开 WS + 清空本地状态。 */
  function reset() {
    disconnect()
    notifications.value = []
    announcements.value = []
    popupQueue.value = []
    unreadCount.value = 0
    unreadAnnouncements.value = 0
  }

  return {
    // state
    notifications,
    unreadCount,
    announcements,
    unreadAnnouncements,
    popupQueue,
    loading,
    wsStatus,
    // computed
    totalUnread,
    feed,
    // combined
    fetchFeed,
    // notifications
    fetchNotifications,
    fetchUnreadCount,
    markRead,
    markAllRead,
    // announcements
    fetchAnnouncements,
    fetchAnnouncementUnreadCount,
    fetchPopupAnnouncements,
    markAnnouncementRead,
    markAllAnnouncementsRead,
    dismissPopup,
    // lifecycle
    connect,
    disconnect,
    init,
    reset,
  }
})
