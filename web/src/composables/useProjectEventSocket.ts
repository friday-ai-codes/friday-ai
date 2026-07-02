/**
 * useProjectEventSocket — 订阅单个项目的实时事件（ws/projects/{projectId}/）。
 *
 * 复用后端 ProjectConsumer + apush_project_event 的 project_event 广播（鉴权由 HTTP-only
 * cookie JWT 握手自动携带）。断线指数退避重连；组件卸载自动断开。调用方通过 onEvent
 * 回调按 event 类型消费（如 feature_list_draft 进度推送）。
 */
import { onScopeDispose, ref } from 'vue'

export interface ProjectEvent {
  type: 'project_event'
  event: string
  project_id: string
  data: any
}

export type ProjectEventHandler = (evt: ProjectEvent) => void

const MAX_RETRIES = 10

export function useProjectEventSocket(
  projectId: string,
  onEvent: ProjectEventHandler,
) {
  const connected = ref(false)
  let ws: WebSocket | null = null
  let retryCount = 0
  let retryTimer: ReturnType<typeof setTimeout> | null = null
  let closedByUs = false

  function getWsUrl(): string {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${location.host}/ws/projects/${projectId}/`
  }

  function handleMessage(raw: string) {
    let msg: any
    try {
      msg = JSON.parse(raw)
    }
    catch {
      return
    }
    if (msg && msg.type === 'project_event')
      onEvent(msg as ProjectEvent)
  }

  function connect() {
    if (ws && ws.readyState <= WebSocket.OPEN)
      return
    closedByUs = false
    ws = new WebSocket(getWsUrl())
    ws.onopen = () => {
      connected.value = true
      retryCount = 0
    }
    ws.onmessage = (e: MessageEvent) => handleMessage(e.data)
    ws.onclose = (e: CloseEvent) => {
      ws = null
      connected.value = false
      // 4401 未认证 / 主动关闭 → 不重连。
      if (closedByUs || e.code === 4401)
        return
      scheduleReconnect()
    }
    ws.onerror = () => {}
  }

  function scheduleReconnect() {
    if (retryCount >= MAX_RETRIES)
      return
    const delay = Math.min(1000 * 2 ** retryCount, 30000)
    retryCount++
    retryTimer = setTimeout(connect, delay)
  }

  function disconnect() {
    closedByUs = true
    if (retryTimer)
      clearTimeout(retryTimer)
    retryTimer = null
    retryCount = 0
    ws?.close()
    ws = null
    connected.value = false
  }

  onScopeDispose(disconnect)

  // 创建即连接：调用方（如 FeatureListEditModal）依赖实时进度推送，
  // 若等调用方手动 connect 容易遗漏（曾导致解析进度永远卡在 5%）。
  connect()

  return { connected, connect, disconnect }
}
