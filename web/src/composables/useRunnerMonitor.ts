/**
 * WebSocket 实时监控 composable
 * 管理与后端 MonitorConsumer 的 WS 连接生命周期：连接、JWT 认证握手、指数退避重连、断开
 */
import { getAccessToken, refreshToken } from '~/api/client'
export type MonitorStatus = 'connecting' | 'connected' | 'reconnecting' | 'disconnected'
export interface MonitorLog {
 id: number
 event: string
 runner_id: string
 data: Record<string, unknown>
 timestamp: Date
}
const MAX_LOGS = 500
const MAX_RETRIES = 10
// 全局单例状态（composable 外部定义，多次调用共享）
const status = ref<MonitorStatus>('disconnected')
const logs = ref<MonitorLog>
let ws: WebSocket | null = null
let retryCount = 0
let retryTimer: ReturnType<typeof setTimeout> | null = null
let logIdCounter = 0
export function useRunnerMonitor {
 const runnersStore = useRunnersStore
 function getWsUrl: string {
 const proto = location.protocol === 'https:' ? 'wss:': 'ws:'
 return `${proto}//${location.host}/ws/v1/runners/monitor/`
 }
 function connect {
 if (ws && ws.readyState <= WebSocket.OPEN) return
 status.value = retryCount > 0 ? 'reconnecting': 'connecting'
 ws = new WebSocket(getWsUrl)
 ws.onopen = => {
 const token = getAccessToken
 if (token) ws!.send(JSON.stringify({ type: 'auth', token }))
 }
 ws.onmessage = (e: MessageEvent) => {
 const msg = JSON.parse(e.data)
 if (msg.type === 'auth') {
 if (msg.status === 'ok') {
 status.value = 'connected'
 retryCount = 0
 }
 return
 }
 handleEvent(msg)
 }
 ws.onclose = (e: CloseEvent) => {
 ws = null
 if (e.code === 4003) {
 handleAuthFailure
 return
 }
 status.value = 'disconnected'
 scheduleReconnect
 }
 ws.onerror = => {
 // onclose 会触发，此处不做额外处理
 }
 }
 function handleEvent(msg: { event: string, runner_id: string, data: Record<string, unknown> }) {
 addLog(msg)
 if (msg.event === 'runner.status_changed') {
 runnersStore.patchRunner(msg.runner_id, msg.data)
 }
 else if (msg.event === 'task.status_changed') {
 runnersStore.patchRunnerTask(msg.runner_id, msg.data)
 }
 }
 function addLog(msg: { event: string, runner_id: string, data: Record<string, unknown> }) {
 logs.value.push({
 id: ++logIdCounter,
 event: msg.event,
 runner_id: msg.runner_id,
 data: msg.data,
 timestamp: new Date,
 })
 if (logs.value.length > MAX_LOGS) {
 logs.value.splice(0, logs.value.length - MAX_LOGS)
 }
 }
 function scheduleReconnect {
 if (retryCount >= MAX_RETRIES) return
 const delay = Math.min(1000 * 2 ** retryCount, 30000)
 retryCount++
 status.value = 'reconnecting'
 retryTimer = setTimeout(connect, delay)
 }
 async function handleAuthFailure {
 try {
 await refreshToken
 connect
 }
 catch {
 status.value = 'disconnected'
 }
 }
 function disconnect {
 if (retryTimer) clearTimeout(retryTimer)
 retryTimer = null
 retryCount = 0
 ws?.close
 ws = null
 status.value = 'disconnected'
 }
 // 页面可见性监听：切回页面时自动重连
 const visibility = useDocumentVisibility
 watch(visibility, (val) => {
 if (val === 'visible' && status.value !== 'connected') {
 connect
 }
 })
 return {
 status: readonly(status),
 logs: readonly(logs),
 connect,
 disconnect,
 }
}
