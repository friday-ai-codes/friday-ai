/**
 * Provider 凭证管理 Pinia Store（Phase / ）
 *
 * 缓存策略（CONTEXT ~ ）：
 * - 双层：内存 reactive（Pinia ref）+ sessionStorage 热补水
 * - 30 秒 TTL：fetchCredentials 内检查 lastFetchedAt,同上下文命中则返回缓存
 * - mount 时（首次 useProviderCredentialStore 调用）自动 hydrate；
 * 每次 mutation action 成功后同步调 persist（双写模式,避免 watch deep 性能开销）
 *
 * W5 sessionStorage 选型（非 localStorage）理由:
 * 1. 满足 秒级展开诉求(hard refresh / 路由跳转保留状态)
 * 2. 关 tab / 新 tab 自动清空 → 30s TTL 首次拉取,符合凭证列表"按需加载"隐私姿态
 * 3. 凭证 ID / last4 / 健康状态不跨 tab 共享(不同 tab 可能不同 project 上下文)
 * 4. XSS 暴露面小于 localStorage(脚本需 session 内存活)
 */
import type {
 AvailableModel,
 ProviderCredentialCreatePayload,
 ProviderCredentialDto,
 ProviderCredentialUpdatePayload,
 ProviderScope,
 ProviderTypeMetaDto,
 TestConnectionResponse,
} from '~/types/providerCredential'
import { providerCredentialsApi } from '~/api/providerCredentials'
const STORAGE_KEY = 'providerCredentialCache'
const TTL_MS = 30_000
interface PersistedSnapshot {
 credentials: ProviderCredentialDto
 providerTypes: ProviderTypeMetaDto
 lastFetchedAt: number
 currentProjectId: string | null
}
export const useProviderCredentialStore = defineStore('providerCredential', => {
 // ============================================================================
 // State
 // ============================================================================
 const credentials = ref<ProviderCredentialDto>
 const providerTypes = ref<ProviderTypeMetaDto>
 const loading = ref(false)
 const lastError = ref<string | null>(null)
 const currentProjectId = ref<string | null>(null)
 const lastFetchedAt = ref<number>(0)
 // ============================================================================
 // Getters
 // ============================================================================
 const getCredentialById = computed( => {
 return (id: string): ProviderCredentialDto | null =>
 credentials.value.find(c => c.id === id) ?? null
 })
 const getCredentialsByScope = computed( => {
 return (scope: ProviderScope): ProviderCredentialDto =>
 credentials.value.filter(c => c.scope === scope)
 })
 const activeCredentials = computed<ProviderCredentialDto>( =>
 credentials.value.filter(c => c.is_active),
 )
 // ============================================================================
 // Persistence helpers（ 双写）
 // ============================================================================
 /** 写回 sessionStorage；SSR / 配额超限 / 权限受限时静默降级。 */
 function persist: void {
 // Pitfall 6：非浏览器环境保护（虽目前纯 SPA,防御性加码）
 if (typeof window === 'undefined' || typeof sessionStorage === 'undefined')
 return
 try {
 const snapshot: PersistedSnapshot = {
 credentials: credentials.value,
 providerTypes: providerTypes.value,
 lastFetchedAt: lastFetchedAt.value,
 currentProjectId: currentProjectId.value,
 }
 sessionStorage.setItem(STORAGE_KEY, JSON.stringify(snapshot))
 }
 catch {
 // 配额超限 / 权限受限：静默降级,不影响内存 store
 }
 }
 /** 从 sessionStorage 热补水；遇解析错 / shape 不匹配 → 清脏缓存 + 保持空。 */
 function hydrate: void {
 if (typeof window === 'undefined' || typeof sessionStorage === 'undefined')
 return
 const raw = sessionStorage.getItem(STORAGE_KEY)
 if (!raw)
 return
 try {
 const parsed = JSON.parse(raw) as Partial<PersistedSnapshot>
 // Pitfall 4：shape 校验,防脏缓存污染内存
 if (!parsed || !Array.isArray(parsed.credentials) || !Array.isArray(parsed.providerTypes))
 return
 credentials.value = parsed.credentials as ProviderCredentialDto
 providerTypes.value = parsed.providerTypes as ProviderTypeMetaDto
 lastFetchedAt.value = typeof parsed.lastFetchedAt === 'number' ? parsed.lastFetchedAt: 0
 currentProjectId.value = parsed.currentProjectId ?? null
 }
 catch {
 // JSON 解析失败：清掉脏缓存
 try {
 sessionStorage.removeItem(STORAGE_KEY)
 }
 catch {
 // noop
 }
 }
 }
 // ============================================================================
 // Actions
 // ============================================================================
 /**：按 scope / projectId 拉取凭证列表,同上下文 30s TTL 内命中缓存。 */
 async function fetchCredentials(params: {
 scope?: ProviderScope
 projectId?: string
 includeInactive?: boolean
 force?: boolean
 } = {}): Promise<ProviderCredentialDto> {
 const now = Date.now
 const sameContext = currentProjectId.value === (params.projectId ?? null)
 if (
 !params.force
 && sameContext
 && now - lastFetchedAt.value < TTL_MS
 && credentials.value.length > 0
 ) {
 return credentials.value
 }
 loading.value = true
 lastError.value = null
 try {
 const list = await providerCredentialsApi.list({
 scope: params.scope,
 projectId: params.projectId,
 includeInactive: params.includeInactive,
 })
 credentials.value = list
 lastFetchedAt.value = now
 currentProjectId.value = params.projectId ?? null
 persist
 return list
 }
 catch (e) {
 lastError.value = e instanceof Error ? e.message: '加载凭证失败'
 throw e
 }
 finally {
 loading.value = false
 }
 }
 /**：拉取 5 Provider 元信息 + credential_schema JSON Schema（动态表单数据源）。 */
 async function fetchProviderTypes(force = false): Promise<ProviderTypeMetaDto> {
 if (!force && providerTypes.value.length > 0)
 return providerTypes.value
 try {
 const list = await providerCredentialsApi.listProviderTypes
 providerTypes.value = list
 persist
 return list
 }
 catch (e) {
 lastError.value = e instanceof Error ? e.message: '加载 Provider 类型失败'
 throw e
 }
 }
 /** 创建凭证 + 新项插入列表头部 + 持久化。 */
 async function createCredential(
 payload: ProviderCredentialCreatePayload,
 ): Promise<ProviderCredentialDto> {
 loading.value = true
 lastError.value = null
 try {
 const created = await providerCredentialsApi.create(payload)
 credentials.value = [created, ...credentials.value]
 persist
 return created
 }
 catch (e) {
 lastError.value = e instanceof Error ? e.message: '保存凭证失败'
 throw e
 }
 finally {
 loading.value = false
 }
 }
 async function updateCredential(
 id: string,
 payload: ProviderCredentialUpdatePayload,
 ): Promise<ProviderCredentialDto> {
 loading.value = true
 lastError.value = null
 try {
 const updated = await providerCredentialsApi.update(id, payload)
 credentials.value = credentials.value.map(c => (c.id === id ? updated: c))
 persist
 return updated
 }
 catch (e) {
 lastError.value = e instanceof Error ? e.message: '更新凭证失败'
 throw e
 }
 finally {
 loading.value = false
 }
 }
 async function deleteCredential(id: string): Promise<void> {
 loading.value = true
 lastError.value = null
 try {
 await providerCredentialsApi.remove(id)
 credentials.value = credentials.value.filter(c => c.id !== id)
 persist
 }
 catch (e) {
 lastError.value = e instanceof Error ? e.message: '删除凭证失败'
 throw e
 }
 finally {
 loading.value = false
 }
 }
 /** 切换启用态（乐观更新 + API 失败回滚）。 */
 async function toggleActive(id: string): Promise<boolean> {
 const original = credentials.value.find(c => c.id === id)
 if (!original)
 throw new Error(`凭证 ${id} 不存在`)
 const optimistic = !original.is_active
 credentials.value = credentials.value.map(c =>
 c.id === id ? { ...c, is_active: optimistic }: c,
 )
 try {
 const resp = await providerCredentialsApi.toggleActive(id)
 // 与后端结果对齐（防双点击 / 竞态）
 credentials.value = credentials.value.map(c =>
 c.id === id ? { ...c, is_active: resp.is_active }: c,
 )
 persist
 return resp.is_active
 }
 catch (e) {
 // 失败回滚
 credentials.value = credentials.value.map(c =>
 c.id === id ? { ...c, is_active: original.is_active }: c,
 )
 lastError.value = e instanceof Error ? e.message: '切换状态失败'
 throw e
 }
 }
 /** 测试连接成功后同步 credential 的 last_health_check_* 字段。 */
 async function testConnection(id: string): Promise<TestConnectionResponse> {
 try {
 const resp = await providerCredentialsApi.testConnection(id)
 credentials.value = credentials.value.map(c =>
 c.id === id
 ? {
 ...c,
 last_health_check_at: resp.last_health_check_at,
 last_health_check_status: resp.status,
 last_health_check_error: resp.error ?? '',
 }: c,
 )
 persist
 return resp
 }
 catch (e) {
 lastError.value = e instanceof Error ? e.message: '连接测试失败'
 throw e
 }
 }
 /**：强制刷新 available_models 并写回 credential。 */
 async function refreshModels(id: string): Promise<AvailableModel> {
 try {
 const resp = await providerCredentialsApi.refreshModels(id)
 credentials.value = credentials.value.map(c =>
 c.id === id ? { ...c, available_models: resp.available_models }: c,
 )
 persist
 return resp.available_models
 }
 catch (e) {
 lastError.value = e instanceof Error ? e.message: '刷新模型清单失败'
 throw e
 }
 }
 /** 核心路径：cache hit 直接返回；miss 触发 refreshModels。 */
 async function getModelsForCredential(id: string): Promise<AvailableModel> {
 const cred = credentials.value.find(c => c.id === id)
 if (cred && cred.available_models.length > 0)
 return cred.available_models
 return refreshModels(id)
 }
 // ============================================================================
 // Mount hydration
 //
 // pinia 保证 store 单例,setup 函数仅在首次 useProviderCredentialStore 时执行,
 // 即"mount"时 hydrate 一次。hard refresh 后首次 import 立即恢复状态,零闪烁。
 // ============================================================================
 hydrate
 return {
 // state
 credentials,
 providerTypes,
 loading,
 lastError,
 currentProjectId,
 lastFetchedAt,
 // getters
 getCredentialById,
 getCredentialsByScope,
 activeCredentials,
 // actions
 fetchCredentials,
 fetchProviderTypes,
 createCredential,
 updateCredential,
 deleteCredential,
 toggleActive,
 testConnection,
 refreshModels,
 getModelsForCredential,
 // helpers（测试用）
 hydrate,
 persist,
 }
})
