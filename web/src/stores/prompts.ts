/**
 * Prompts Store
 *
 * Phase Plan 数据层基石。覆盖 Phase Prompt CRUD / Preview / Versions API，
 * 并通过 `mergedSpaceList` computed 实现 的三态合并（overridden/fallback/project_only）。
 *
 * Pinia setup-syntax。`defineStore`、`ref`、`computed` 通过 `unplugin-auto-import` 全局注入
 * （见 web/vite.config.ts + web/src/auto-imports.d.ts），无需显式 import。
 */
import type {
 PromptCategory,
 PromptCreateInput,
 PromptDetail,
 PromptListItem,
 PromptUpdateInput,
 PromptVersion,
} from '~/types/prompts'
import { promptsApi } from '~/api/prompts'
/**
 * 空间级合并后的列表项（ mergedSpaceList 派生结构）
 */
export interface MergedSpaceListItem extends PromptListItem {
 status: 'overridden' | 'fallback' | 'space_only'
 space_prompt: PromptListItem | null
}
export const usePromptsStore = defineStore('prompts', => {
 // ============================================================================
 // State
 // ============================================================================
 const systemList = ref<PromptListItem>
 const spaceList = ref<PromptListItem>
 const currentPrompt = ref<PromptDetail | null>(null)
 const versions = ref<PromptVersion>
 const loading = ref(false)
 const saving = ref(false)
 const previewing = ref(false)
 const error = ref<string | null>(null)
 // ============================================================================
 // Getters
 // ============================================================================
 /**
 * 三态合并 computed：
 * 1. 遍历 systemList 作为基线，每条检查在 projectList 中是否有 slug 同名覆盖
 * 2. overridden = 系统级 + 空间级覆盖存在
 * 3. fallback = 系统级 + 无空间级覆盖
 * 4. project_only = 空间级存在但系统级无同 slug（极端情况）
 */
 const mergedSpaceList = computed<MergedSpaceListItem>( => {
 const merged: MergedSpaceListItem =
 const spaceBySlug = new Map(spaceList.value.map(p => [p.slug, p] as const))
 for (const sys of systemList.value) {
 const override = spaceBySlug.get(sys.slug) ?? null
 merged.push({
 ...sys,
 space_prompt: override,
 status: override ? 'overridden': 'fallback',
 })
 if (override) {
 spaceBySlug.delete(sys.slug)
 }
 }
 for (const proj of spaceBySlug.values) {
 merged.push({ ...proj, space_prompt: null, status: 'space_only' })
 }
 return merged
 })
 // ============================================================================
 // Actions —— 所有 catch 必须 throw e 上抛让组件层 useErrorHandler 处理
 // ============================================================================
 async function loadSystemList(category?: PromptCategory): Promise<void> {
 loading.value = true
 error.value = null
 try {
 systemList.value = await promptsApi.list({ scope: 'system', category })
 }
 catch (e) {
 error.value = e instanceof Error ? e.message: '加载系统级 Prompt 列表失败'
 throw e
 }
 finally {
 loading.value = false
 }
 }
 async function loadSpaceList(spaceId: string): Promise<void> {
 loading.value = true
 error.value = null
 try {
 const [sys, proj] = await Promise.all([
 promptsApi.list({ scope: 'system' }),
 promptsApi.list({ scope: 'project', space_id: spaceId }),
 ])
 systemList.value = sys
 spaceList.value = proj
 }
 catch (e) {
 error.value = e instanceof Error ? e.message: '加载空间级 Prompt 列表失败'
 throw e
 }
 finally {
 loading.value = false
 }
 }
 async function loadDetail(id: string): Promise<void> {
 loading.value = true
 error.value = null
 try {
 currentPrompt.value = await promptsApi.get(id)
 }
 catch (e) {
 error.value = e instanceof Error ? e.message: '加载 Prompt 详情失败'
 throw e
 }
 finally {
 loading.value = false
 }
 }
 async function loadVersions(id: string): Promise<void> {
 loading.value = true
 error.value = null
 try {
 versions.value = await promptsApi.listVersions(id)
 }
 catch (e) {
 error.value = e instanceof Error ? e.message: '加载版本历史失败'
 throw e
 }
 finally {
 loading.value = false
 }
 }
 async function createPrompt(data: PromptCreateInput): Promise<PromptDetail> {
 saving.value = true
 error.value = null
 try {
 const created = await promptsApi.create(data)
 currentPrompt.value = created
 return created
 }
 catch (e) {
 error.value = e instanceof Error ? e.message: '创建 Prompt 失败'
 throw e
 }
 finally {
 saving.value = false
 }
 }
 async function updatePrompt(id: string, data: PromptUpdateInput): Promise<PromptDetail> {
 saving.value = true
 error.value = null
 try {
 const updated = await promptsApi.update(id, data)
 currentPrompt.value = updated
 return updated
 }
 catch (e) {
 error.value = e instanceof Error ? e.message: '保存 Prompt 失败'
 throw e
 }
 finally {
 saving.value = false
 }
 }
 async function deletePrompt(id: string): Promise<void> {
 saving.value = true
 error.value = null
 try {
 await promptsApi.delete(id)
 if (currentPrompt.value?.id === id) {
 currentPrompt.value = null
 }
 systemList.value = systemList.value.filter(p => p.id !== id)
 spaceList.value = spaceList.value.filter(p => p.id !== id)
 }
 catch (e) {
 error.value = e instanceof Error ? e.message: '删除 Prompt 失败'
 throw e
 }
 finally {
 saving.value = false
 }
 }
 async function previewPrompt(
 id: string,
 variables: Record<string, string>,
 ): Promise<{ rendered: string }> {
 previewing.value = true
 error.value = null
 try {
 return await promptsApi.preview(id, variables)
 }
 catch (e) {
 // PromptVariableMissingError 不写 error 字段，让 UI 层 inline 特判
 if (e instanceof Error && e.name !== 'PromptVariableMissingError') {
 error.value = e.message
 }
 throw e
 }
 finally {
 previewing.value = false
 }
 }
 async function activateVersion(id: string, versionId: string): Promise<PromptDetail> {
 saving.value = true
 error.value = null
 try {
 const updated = await promptsApi.activateVersion(id, versionId)
 currentPrompt.value = updated
 return updated
 }
 catch (e) {
 error.value = e instanceof Error ? e.message: '版本回滚失败'
 throw e
 }
 finally {
 saving.value = false
 }
 }
 function clearCurrent: void {
 currentPrompt.value = null
 versions.value =
 }
 return {
 // State
 systemList,
 spaceList,
 currentPrompt,
 versions,
 loading,
 saving,
 previewing,
 error,
 // Getters
 mergedSpaceList,
 // Actions
 loadSystemList,
 loadSpaceList,
 loadDetail,
 loadVersions,
 createPrompt,
 updatePrompt,
 deletePrompt,
 previewPrompt,
 activateVersion,
 clearCurrent,
 }
})
