/**
 * 系统健康状态 composable
 *
 * 职责：
 * - 轮询 /api/system/health/（默认 30s），页面隐藏（document.hidden）时暂停
 * - 将后端返回的 Redis / 飞书 / Qdrant / 数据库 状态与前端的 WebSocket 状态融合
 * - 计算整体徽标颜色：
 * - connected + all healthy → emerald（已连接）
 * - 任一 unhealthy / WS disconnected → red（异常）
 * - 任一 not_configured 或 WS connecting → amber（部分可用/连接中）
 * - 全局单例：多个组件复用同一轮询任务
 */
import type {
 OverallHealthStatus,
 ServiceHealth,
 SystemHealth,
} from '~/api/system'
import type { MonitorStatus } from '~/composables/useRunnerMonitor'
import { getSystemHealth } from '~/api/system'
import { useRunnerMonitor } from '~/composables/useRunnerMonitor'
const POLL_INTERVAL_MS = 30_000
type Pill = 'healthy' | 'degraded' | 'unhealthy' | 'loading'
interface AggregatedService extends ServiceHealth {
 /** 仅用于展示的图标/颜色分组 */
 tone: 'ok' | 'warn' | 'error' | 'muted'
}
const servicesRef = ref<ServiceHealth>
const overallRef = ref<OverallHealthStatus | null>(null)
const checkedAt = ref<string | null>(null)
const loading = ref(false)
const lastError = ref<string | null>(null)
let timer: ReturnType<typeof setInterval> | null = null
let inFlight: Promise<void> | null = null
let started = false
async function fetchOnce: Promise<void> {
 if (inFlight)
 return inFlight
 loading.value = true
 inFlight = (async => {
 try {
 const data: SystemHealth = await getSystemHealth
 servicesRef.value = data.services
 overallRef.value = data.overall
 checkedAt.value = data.checked_at
 lastError.value = null
 }
 catch (e) {
 lastError.value = e instanceof Error ? e.message: String(e)
 }
 finally {
 loading.value = false
 inFlight = null
 }
 })
 return inFlight
}
function startPolling {
 if (timer)
 return
 timer = setInterval( => {
 if (document.hidden)
 return
 fetchOnce
 }, POLL_INTERVAL_MS)
}
function stopPolling {
 if (timer) {
 clearInterval(timer)
 timer = null
 }
}
function toneOf(status: ServiceHealth['status']): AggregatedService['tone'] {
 switch (status) {
 case 'healthy':
 return 'ok'
 case 'unhealthy':
 return 'error'
 case 'not_configured':
 return 'muted'
 default:
 return 'warn'
 }
}
export function useSystemHealth {
 const { status: wsStatus } = useRunnerMonitor
 // 首次使用时初始化：立即请求一次 + 启动轮询 + 注册可见性监听
 if (!started) {
 started = true
 fetchOnce
 startPolling
 document.addEventListener('visibilitychange', => {
 if (!document.hidden)
 fetchOnce
 })
 }
 /** WebSocket 作为"服务"之一加入展示列表 */
 const websocketService = computed<AggregatedService>( => {
 const s: MonitorStatus = wsStatus.value
 const healthStatus: ServiceHealth['status']
 = s === 'connected' ? 'healthy': 'unhealthy'
 const messageMap: Record<MonitorStatus, string> = {
 connected: '实时通道已建立',
 connecting: '正在建立连接',
 reconnecting: '正在重连',
 disconnected: '连接已断开',
 }
 return {
 name: 'websocket',
 label: '实时通道',
 status: healthStatus,
 message: messageMap[s],
 tone:
 s === 'connected'
 ? 'ok': s === 'disconnected'
 ? 'error': 'warn',
 }
 })
 const aggregatedServices = computed<AggregatedService>( => {
 const backend: AggregatedService = servicesRef.value.map(svc => ({
 ...svc,
 tone: toneOf(svc.status),
 }))
 return [websocketService.value, ...backend]
 })
 /** 汇总状态：用于顶栏单胶囊颜色与文案 */
 const pill = computed<Pill>( => {
 if (overallRef.value === null && loading.value)
 return 'loading'
 const services = aggregatedServices.value
 if (services.some(s => s.tone === 'error'))
 return 'unhealthy'
 if (services.some(s => s.tone === 'warn' || s.tone === 'muted'))
 return 'degraded'
 return 'healthy'
 })
 const pillLabel = computed( => {
 switch (pill.value) {
 case 'healthy':
 return '已连接'
 case 'degraded':
 return '部分可用'
 case 'unhealthy':
 return '连接异常'
 case 'loading':
 default:
 return '检测中...'
 }
 })
 return {
 services: aggregatedServices,
 overall: readonly(overallRef),
 checkedAt: readonly(checkedAt),
 loading: readonly(loading),
 lastError: readonly(lastError),
 pill,
 pillLabel,
 refresh: fetchOnce,
 stop: stopPolling,
 }
}
export type UseSystemHealthReturn = ReturnType<typeof useSystemHealth>
