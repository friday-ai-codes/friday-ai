<script setup lang="ts">
/**
 * 技术蓝图查看器（Phase 115-06，UI-SPEC §4.1 / §5 / §8 / §9 / §11）。
 *
 * ## ① 唯一权威渲染面
 *
 * 所有入口（知识库「技术方案」tab / 项目物料卡 / 后续 chat 卡片）一律 `RouterLink` 深链跳到
 * 这里。⛔ **不做「全屏 Dialog 形态」的第二套实现** —— 那会让引用预览成为**嵌套 Dialog**
 * （DESIGN §8.3 自承代码库无先例、需新造 z-index 与焦点管理封装）。改成路由页之后，引用预览
 * 就是**第一层** `Dialog`，直接复用既有 `components/ui/dialog/`，零新封装。
 *
 * ## ② ⭐ 十段容器无条件渲染（本页头号靶子，P-4）
 *
 * 段导航（`BlueprintSectionNav`，随头部吸顶的横条）只在 `onMounted` 那一刻按
 * `props.sections` 逐个 `getElementById`，**既没有 `watch(() => props.sections)` 也没有
 * `MutationObserver`**。若十段写成 `v-if="doc"`，mount 那一刻 DOM 里一个段都没有 ⇒
 * IntersectionObserver **一个也挂不上** ⇒ **导航高亮永远停在第一段，而点击跳转照常工作**
 * （`scrollTo` 是点击时才查 DOM）—— 人肉自测只会觉得「高亮有点怪」，根本不会当成缺陷。
 *
 * 因此本页的硬约束是：**十个 `<section id="…">` 恒渲染、`sections` 数组长度恒为 10**，
 * 骨架 / 实渲 / 空态三态全部发生在段容器**内部**；段 `id` 一律写成**静态字面量**
 * （写成绑定形式一旦拼错变量名就会渲染出 `id=""`，症状与条件渲染一模一样）。
 *
 * ⚠️ 这是对 UI-SPEC §6.9「`must_haves` 全空时整段与导航项都不渲染」的**一处显式订正**：
 * 无内容时**段容器与导航项照旧渲染**，只是段内不出内容（段高度可为 0）。
 * ⚠️ 同理，diff 视图下十段容器**仍在**（内容由 `BlueprintBlockDiff` 承担，段内暂不出内容）
 * —— 「容器无条件渲染」优先于 UI-SPEC §9.2「正文区替换」的措辞。
 *
 * ## ③ 并行纪律
 *
 * 实时进展只经 `useBlueprintLive`（全相位唯一轮询消费点）；本页轮询间隔字面量零命中。
 * 同步点 2 之后换 v0.19.0 的推送契约时，只需要改那一个文件。
 */

import type { Ref } from 'vue'
import type { SelectionPayload } from '~/components/blueprint/BlueprintBlockList.vue'
import type { BlueprintRejectPayload } from '~/components/blueprint/BlueprintRejectDialog.vue'
import type { BlueprintCommentDraft } from '~/components/blueprint/BlueprintThreadSidebar.vue'
import type { BlueprintVersionEntry } from '~/components/blueprint/BlueprintVersionSwitcher.vue'
import type { NavSection } from '~/components/layout/AnchorNavLayout.vue'
import type {
  BlueprintAnchor,
  BlueprintBlock,
  BlueprintBlockEditRejection,
  BlueprintBlockOp,
  BlueprintFeaturePoint,
  BlueprintThreadDetail,
  Citation,
} from '~/types/blueprint'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { useMediaQuery, useResizeObserver, useWindowScroll } from '@vueuse/core'
import { useHead } from '@vueuse/head'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import blueprintsApi from '~/api/blueprints'
import { ApiError } from '~/api/client'
import deliveryArtifactsApi from '~/api/deliveryArtifacts'
import { canEditBlueprintBlock } from '~/components/blueprint/blockEditOps'
import BlueprintAssociationsSection from '~/components/blueprint/BlueprintAssociationsSection.vue'
import BlueprintBlockDiff from '~/components/blueprint/BlueprintBlockDiff.vue'
import BlueprintBlockedDialog from '~/components/blueprint/BlueprintBlockedDialog.vue'
import BlueprintBlockEditDialog from '~/components/blueprint/BlueprintBlockEditDialog.vue'
import BlueprintBlockList from '~/components/blueprint/BlueprintBlockList.vue'
import BlueprintCommentPopover from '~/components/blueprint/BlueprintCommentPopover.vue'
import BlueprintErrorState from '~/components/blueprint/BlueprintErrorState.vue'
import BlueprintGatePanel from '~/components/blueprint/BlueprintGatePanel.vue'
import BlueprintQualityPanel from '~/components/blueprint/BlueprintQualityPanel.vue'
import BlueprintRejectDialog from '~/components/blueprint/BlueprintRejectDialog.vue'
import BlueprintResearchDrawer from '~/components/blueprint/BlueprintResearchDrawer.vue'
import BlueprintSectionNav from '~/components/blueprint/BlueprintSectionNav.vue'
import BlueprintSelectionPopover from '~/components/blueprint/BlueprintSelectionPopover.vue'
import BlueprintStageStepper from '~/components/blueprint/BlueprintStageStepper.vue'
import BlueprintThreadSidebar from '~/components/blueprint/BlueprintThreadSidebar.vue'
import BlueprintViewerHeader from '~/components/blueprint/BlueprintViewerHeader.vue'
import CitationPreviewDialog from '~/components/blueprint/CitationPreviewDialog.vue'
import ApiContractsSection from '~/components/blueprint/sections/ApiContractsSection.vue'
import CurrentStateSection from '~/components/blueprint/sections/CurrentStateSection.vue'
import DecisionLogSection from '~/components/blueprint/sections/DecisionLogSection.vue'
import ImpactAnalysisSection from '~/components/blueprint/sections/ImpactAnalysisSection.vue'
import ImplementationOverviewSection from '~/components/blueprint/sections/ImplementationOverviewSection.vue'
import InteractionFlowsSection from '~/components/blueprint/sections/InteractionFlowsSection.vue'
import MustHavesSection from '~/components/blueprint/sections/MustHavesSection.vue'
import RepoAssociationsSection from '~/components/blueprint/sections/RepoAssociationsSection.vue'
import RequirementSpecSection from '~/components/blueprint/sections/RequirementSpecSection.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { ScrollArea } from '~/components/ui/scroll-area'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '~/components/ui/sheet'
import { Skeleton } from '~/components/ui/skeleton'
import { useBlueprintAnnotations } from '~/composables/useBlueprintAnnotations'
import { useBlueprintLive } from '~/composables/useBlueprintLive'
import { useCitationPreview } from '~/composables/useCitationPreview'
import { useToast } from '~/composables/useToast'
import { isBlueprintEditable } from '~/config/blueprintStatus'
import { useBlueprintViewerStore } from '~/stores/useBlueprintViewerStore'
import { isUnresolvedBlocker } from '~/utils/blueprintAnnotations'
import { iterBlocks } from '~/utils/blueprintBlocks'

/**
 * 跨段跳转与深链滚动偏移的**兜底**常量（页面与 `AnchorNavLayout` 共用 `measureScrollOffset`
 * 这一个来源，本值只在 sticky 头量不到时生效）。
 *
 * ⭐ 不再用静态 88：顶栏是 `sticky` 且带「未经确认」警示横幅时实测高约 136px，静态偏移
 * 会让每次锚点跳转都把段标题埋进头下 ~48px。
 */
const SCROLL_OFFSET_FALLBACK = 88

/** 运行时量 sticky 顶栏实际高度 + 12px 呼吸位；量不到回落常量。 */
function measureScrollOffset(): number {
  const header = document.querySelector<HTMLElement>('[data-testid="blueprint-viewer-header"]')
  const height = header?.offsetHeight ?? 0
  return height > 0 ? height + 12 : SCROLL_OFFSET_FALLBACK
}

// ── 侧栏吸顶偏移（quick-260806-tsb）────────────────────────────────────────────
//
// ⭐ 旧值是静态 `top-22`（88px），而 sticky 顶栏带段导航/警示横幅时实测 130px+ ⇒
// 侧栏顶部（含容器上圆角与第一张卡）整个滑进头部底下 —— 用户点名的「圆角没展示全」。
// 与 `measureScrollOffset` 同源：实测头高 + 12px 呼吸位，头高变化由 ResizeObserver 跟随。

const viewerHeaderEl = ref<HTMLElement | null>(null)
const sidebarTopOffset = ref(SCROLL_OFFSET_FALLBACK)

function syncSidebarTopOffset(): void {
  sidebarTopOffset.value = measureScrollOffset()
}

onMounted(() => {
  viewerHeaderEl.value = document.querySelector<HTMLElement>('[data-testid="blueprint-viewer-header"]')
  syncSidebarTopOffset()
})

useResizeObserver(viewerHeaderEl, syncSidebarTopOffset)

/** 侧栏列的 sticky 定位与视口内可用高（16px = 底部呼吸位）。 */
const sidebarStickyStyle = computed(() => ({
  top: `${sidebarTopOffset.value}px`,
  maxHeight: `calc(100vh - ${sidebarTopOffset.value + 16}px)`,
}))
/** 命中目标后的 ring 高亮时长（毫秒）。 */
const HIGHLIGHT_MS = 2000
/** 命中高亮的类名（字面量 ⇒ Tailwind content 扫描直接命中，⛔ 无需 safelist）。
 *  ⭐ ring-offset：段容器自身零 padding，环若贴着内容边界画会像内容顶死在框上；
 *  offset 8px + 背景色填充让环与内容之间有呼吸边距（quick-260806-r7z）。 */
const HIGHLIGHT_CLASS = 'rounded-xl ring-2 ring-primary/60 ring-offset-8 ring-offset-background'

/** 十个段 key —— 顺序即导航顺序，长度恒为 10。 */
const SECTION_KEYS = [
  'requirement_spec',
  'repo_associations',
  'current_state_analysis',
  'implementation_overview',
  'api_contracts',
  'impact_analysis',
  'interaction_flows',
  'must_haves',
  'decision_log',
  'associations',
] as const

/** 段骨架形状（§8.1 按段差异化，⛔ 不用统一矩形）。 */
const SECTION_SKELETON: Record<string, string[]> = {
  requirement_spec: ['h-5 w-40', 'h-16 w-full', 'h-16 w-full'],
  repo_associations: ['h-40 w-full rounded-xl', 'h-40 w-full rounded-xl'],
  current_state_analysis: ['h-5 w-40', 'h-16 w-full', 'h-16 w-full', 'h-16 w-full'],
  implementation_overview: ['h-5 w-40', 'h-16 w-full', 'h-16 w-full', 'h-16 w-full'],
  api_contracts: ['h-40 w-full rounded-xl', 'h-40 w-full rounded-xl'],
  impact_analysis: ['h-5 w-full', 'h-9 w-full', 'h-9 w-full', 'h-9 w-full', 'h-9 w-full'],
  interaction_flows: ['h-56 w-full', 'h-5 w-full', 'h-9 w-full', 'h-9 w-full', 'h-9 w-full'],
  must_haves: ['h-4 w-full', 'h-4 w-full', 'h-4 w-full', 'h-5 w-full', 'h-9 w-full', 'h-9 w-full'],
  decision_log: ['h-12 w-full', 'h-12 w-full', 'h-12 w-full'],
  associations: ['h-12 w-full', 'h-12 w-full', 'h-12 w-full'],
}

/** 质量面板（与 `?panel=review`）的可用状态。 */
const REVIEW_PANEL_STATUSES = new Set(['pending_review', 'confirmed'])

const route = useRoute('/knowledge/blueprints/[id]')
const router = useRouter()
const queryClient = useQueryClient()
const { t } = useI18n()
const toast = useToast()
const viewerStore = useBlueprintViewerStore()

/** ⭐ 参数名取 `id`，对齐全仓 14 处 `[id].vue` 惯例。 */
const artifactId = computed(() => String(route.params.id))

useHead({
  title: computed(() => `${t('knowledge.blueprints.pageTitle')} - Friday AI`),
})

// ── query ↔ ref 双向同步（六键，范式抄 `pages/knowledge/index.vue:43-60`）─────────────

/**
 * 建一个与 `?key=` 双向同步的 ref。
 *
 * ⭐ 写回一律走 `router.replace({ query: { ...route.query, key: v } })` 的**展开写法** ——
 * 其它 query（`tab` / `section` / `thread` …）天然保留；空值直接从 query 里摘掉，
 * ⛔ 不留 `?panel=` 这种空壳参数。
 */
function useQueryParam<T extends string>(key: string, normalize: (raw: unknown) => T): Ref<T> {
  const state = ref(normalize(route.query[key])) as Ref<T>
  watch(() => route.query[key], (raw) => {
    const next = normalize(raw)
    if (next !== state.value)
      state.value = next
  })
  watch(state, (value) => {
    if (String(route.query[key] ?? '') === String(value))
      return
    const query: Record<string, string> = { ...(route.query as Record<string, string>), [key]: value }
    if (!value)
      delete query[key]
    router.replace({ query })
  })
  return state
}

function normalizeId(raw: unknown): string {
  return typeof raw === 'string' && raw ? raw : ''
}

function normalizeDiffMode(raw: unknown): '' | 'inline' | 'split' {
  return raw === 'split' ? 'split' : (raw === 'inline' ? 'inline' : '')
}

function normalizeSection(raw: unknown): string {
  const value = String(raw ?? '')
  return (SECTION_KEYS as readonly string[]).includes(value) ? value : ''
}

function normalizePanel(raw: unknown): '' | 'gate' | 'review' {
  return raw === 'gate' || raw === 'review' ? raw : ''
}

const versionParam = useQueryParam('version', normalizeId)
const diffParam = useQueryParam('diff', normalizeId)
const diffModeParam = useQueryParam('diff_mode', normalizeDiffMode)
const threadParam = useQueryParam('thread', normalizeId)
const panelParam = useQueryParam('panel', normalizePanel)

/**
 * ⭐ 段落定位走 **URL hash**（`#requirement_spec`）而非 query（quick-260806：段落是页面内
 * 锚点，hash 是它的语义正解；query 留给版本 / diff / 线程这类会改变数据请求的参数）。
 *
 * 与 `useQueryParam` 同款双向同步；写回用 `router.replace` 保留既有 query。
 * 兼容存量分享链接：`?section=` 仍被读取（仅初始化时消费一次并从 query 摘掉）。
 */
const sectionParam = ref(
  normalizeSection(String(route.hash || '').replace(/^#/, ''))
  || normalizeSection(route.query.section),
) as Ref<string>

watch(() => route.hash, (raw) => {
  const next = normalizeSection(String(raw || '').replace(/^#/, ''))
  if (next && next !== sectionParam.value)
    sectionParam.value = next
})

// ⭐ 写回用 history.replaceState 而非 router.replace：router 导航会触发全局
// scrollBehavior 的 hash 定位（静态 offset 80），与页面自己的精确滚动
// （measureScrollOffset，随警示横幅动态变高）打架产生二次滚动。replaceState 只改
// 地址栏；浏览器前进/后退与外部直链仍走 router，享受原生 hash 定位。
watch(sectionParam, (value) => {
  const url = new URL(window.location.href)
  const nextHash = value ? `#${value}` : ''
  if (url.hash === nextHash)
    return
  url.hash = nextHash
  window.history.replaceState(window.history.state, '', url)
})

// 存量 `?section=` 链接的一次性迁移：消费进 sectionParam 后把 query 键摘掉。
if (route.query.section !== undefined) {
  const query = { ...(route.query as Record<string, string>) }
  delete query.section
  router.replace({ query, hash: sectionParam.value ? `#${sectionParam.value}` : '' })
}

const diffMode = computed<'inline' | 'split'>(() => (diffModeParam.value === 'split' ? 'split' : 'inline'))
const isDiffMode = computed(() => Boolean(diffParam.value))

// ── 数据层 ────────────────────────────────────────────────────────────────────

const versionId = computed(() => versionParam.value || undefined)

/** ⭐ doc / snapshot / events / stages 四个实时查询全在这里，页面**不再单独建**。 */
const {
  isLive,
  currentStatus,
  doc: docQuery,
  snapshot: snapshotQuery,
  eventsQuery,
  stagesQuery,
  events,
  researchProgress,
  sectionProgress,
  statusProgressKey,
  refetchAll,
} = useBlueprintLive(artifactId, versionId)

/**
 * 节点快照（stage_state 分片 + 重跑面 + 版本谱系）。
 *
 * ⭐ 与 gate 查询同款例外：**它的任何失败都不进错误分档** —— 查询失败只让 stepper 的
 * 状态分片/重跑面降级不渲染、版本树为空，事件驱动的节点状态照常（events 是主查询）。
 */
const stagesData = computed(() => stagesQuery.data.value ?? null)

/** 版本树切换器的供数（带 `version_label` 的谱系清单）。 */
const stageVersions = computed(() => stagesData.value?.versions ?? [])

const threadsQuery = useQuery({
  queryKey: computed(() => ['blueprint', 'threads', artifactId.value]),
  queryFn: () => blueprintsApi.getBlueprintThreads(artifactId.value),
  enabled: computed(() => Boolean(artifactId.value)),
  staleTime: 0,
})

/** 版本轨继续用既有交付物端点（⛔ 零新端点）；它的失败只让版本切换器为空。 */
const timelineQuery = useQuery({
  queryKey: computed(() => ['blueprint', 'timeline', artifactId.value]),
  queryFn: () => deliveryArtifactsApi.getArtifactTimeline(artifactId.value),
  enabled: computed(() => Boolean(artifactId.value)),
  staleTime: 30_000,
  retry: false,
})

/**
 * ⭐ 确认门快照：**它的任何非 200 都不进错误分档**（§8.2 例外一 / P-10）。
 *
 * 这条链**至今没有项目范围闸**，它的 404 混合了「门未开启」「artifact 不存在」「无蓝图编排
 * 会话」三种语义 ⇒ **状态码不携带任何权限信息**，据它推断权限必然出错。因此判据只有一条：
 * 查询非 200 ⇒ 挂载点不渲染。⛔ 不报错、⛔ 不弹提示、⛔ 不写入任何错误态。页面的权限判定
 * **只由四个主查询**（正文 / 人审快照 / 线程 / 阶段事件）承担。
 */
const gateQuery = useQuery({
  queryKey: computed(() => ['blueprint', 'gate', artifactId.value]),
  queryFn: () => blueprintsApi.getBlueprintGate(artifactId.value),
  enabled: computed(() => Boolean(artifactId.value)),
  staleTime: 0,
  retry: false,
})

const gateAvailable = computed(() => Boolean(gateQuery.data.value) && !gateQuery.error.value)
const gateSettled = computed(() => Boolean(gateQuery.data.value) || Boolean(gateQuery.error.value))

/** diff 基线版本的正文（只在 `?diff=` 存在时启用）。 */
const diffBaseQuery = useQuery({
  queryKey: computed(() => ['blueprint', 'doc', artifactId.value, `diff:${diffParam.value}`]),
  queryFn: () => blueprintsApi.getBlueprintDocument(artifactId.value, { version_id: diffParam.value }),
  enabled: computed(() => Boolean(artifactId.value) && Boolean(diffParam.value)),
  staleTime: 30_000,
  retry: false,
})

/**
 * 飞书导出可用性（Phase 116-05，VIEW-05）。
 *
 * ⭐ 与 `gateQuery` 同款例外：**它的任何非 200 都不进错误分档** —— 只决定导出按钮是否
 * 渲染，⛔ 不弹 toast、⛔ 不影响四个主查询驱动的页面状态。
 */
const exportAvailabilityQuery = useQuery({
  queryKey: computed(() => ['blueprint', 'export-availability', artifactId.value]),
  queryFn: () => blueprintsApi.getBlueprintExportAvailability(artifactId.value),
  enabled: computed(() => Boolean(artifactId.value)),
  staleTime: 30_000,
  retry: false,
})

const exportAvailable = computed(() => exportAvailabilityQuery.data.value?.available === true)

const content = computed(() => docQuery.data.value?.content ?? null)

const threads = computed<BlueprintThreadDetail[]>(() => threadsQuery.data.value?.threads ?? [])

/**
 * 人审快照的失锚线程。
 *
 * ⚠️ 快照条目是 `BlueprintThreadRow`（九键，无 `options` / `messages`），侧栏收的是
 * `BlueprintThreadDetail` —— 115-04 的侧栏会用 `threads/` 的同 id 条目覆盖它，查不到时
 * 用快照条目占位。这里原样透传，⛔ 不做任何锚点维度的二次过滤（§20 断言 5）。
 */
const orphanedThreads = computed<BlueprintThreadDetail[]>(
  () => (snapshotQuery.data.value?.orphaned_threads ?? []) as unknown as BlueprintThreadDetail[],
)

const { activeThreadId, counts, selectThread, findThread } = useBlueprintAnnotations(threads, orphanedThreads)

/**
 * ⭐ 顶栏的「未决 BLOCKER」取**人审快照的权威字段**（MJ-03）。
 *
 * `unresolved_blocker_count` 由后端 confirm 闸的同一个方法产出
 * （`blueprint_review_views.py:401` ← `blueprint_lifecycle_service.py:441-446`）⇒ 它与
 * 「点确认会不会吃 409」天然同口径。前端派生（`counts.unresolvedBlocker`）只作快照未就绪时
 * 的占位，两者判据已统一到 `isUnresolvedBlocker`。
 *
 * ⚠️ 用 `??` 而不是 `||`：`0` 是**合法且常见**的权威值，`||` 会把它退回本地派生。
 */
const unresolvedBlockerCount = computed(
  () => snapshotQuery.data.value?.unresolved_blocker_count ?? counts.value.unresolvedBlocker,
)

const {
  open: previewOpen,
  citation: previewCitation,
  openWithSnapshot,
} = useCitationPreview()

const versions = computed<BlueprintVersionEntry[]>(
  () => (timelineQuery.data.value?.versions ?? []) as BlueprintVersionEntry[],
)

/**
 * 驳回弹窗「重跑指定仓」的可选清单（Phase 120，REDO-01）。
 *
 * 源是蓝图正文的 `repo_associations` —— 那正是「这份方案涉及哪些仓」的权威位置。
 * ⛔ 不用 `indirect` 仓：它们没有分仓方案可重跑（只是被依赖调研），列出来会让人勾了没反应。
 */
const reworkRepositories = computed<Array<{ id: string, name: string }>>(() =>
  (content.value?.repo_associations ?? [])
    .filter(association => association.repository_id && association.role !== 'indirect')
    .map(association => ({
      id: association.repository_id,
      name: association.repository_name || association.repository_id,
    })),
)

const repoNames = computed<Record<string, string>>(() => {
  const names: Record<string, string> = {}
  for (const association of content.value?.repo_associations ?? []) {
    if (association.repository_id)
      names[association.repository_id] = association.repository_name || association.repository_id
  }
  return names
})

const citations = computed<Record<string, Citation>>(() => content.value?.citations ?? {})

/** 执行摘要（`meta.summary`）：融合阶段起草的人读导读；旧版本可能没有，空时整卡不渲染。 */
const summaryBlocks = computed(() => content.value?.meta?.summary ?? [])

/** 功能点 id → 标题；澄清向导 chip 展示用（缺标题时回退 id）。 */
const featurePointTitles = computed<Record<string, string>>(() => {
  const map: Record<string, string> = {}
  for (const point of content.value?.requirement_spec?.feature_points ?? []) {
    const id = String(point?.id ?? '').trim()
    if (!id)
      continue
    map[id] = String(point?.title ?? '').trim() || id
  }
  return map
})

/**
 * 功能点 id → 完整功能点；现状分析与实现概述的 `BlueprintFeaturePointChip` 靠它出
 * 悬浮预览（标题 + intent + 验收要点）。索引不存在的 id 让 chip 自行降级成「只有 id」，
 * ⛔ 不在这里过滤 —— 悄悄少一个 chip 比一个没标题的 chip 更难排查。
 */
const featurePointIndex = computed<Record<string, BlueprintFeaturePoint>>(() => {
  const map: Record<string, BlueprintFeaturePoint> = {}
  for (const point of content.value?.requirement_spec?.feature_points ?? []) {
    const id = String(point?.id ?? '').trim()
    if (id)
      map[id] = point
  }
  return map
})

const isHistoricalVersion = computed(() => {
  const doc = docQuery.data.value
  return Boolean(versionParam.value) && Boolean(doc) && doc?.is_current === false
})

/** 只读闸：不可编辑状态 / 历史版本 / diff 视图，三者任一为真即全关写动作。 */
const readonly = computed(
  () => !isBlueprintEditable(currentStatus.value) || isHistoricalVersion.value || isDiffMode.value,
)

const showReadonlyNotice = computed(
  () => !isHistoricalVersion.value && !isDiffMode.value && !isBlueprintEditable(currentStatus.value),
)

// ── 错误分档（§8.2）────────────────────────────────────────────────────────────

/**
 * ⭐ 只有**四个主查询**参与分档：正文 / 人审快照 / 线程 / 阶段事件。
 *
 * 返回 `-1` = 无错误；`0` = 网络 / 解析失败；其余为 `ApiError.status`。
 * `401` / `403` 一律跳过 —— 交给 `~/api/client.ts` 既有的刷新与全局事件机制。
 */
const mainError = computed<ApiError | null>(() => {
  const errors = [
    docQuery.error.value,
    snapshotQuery.error.value,
    threadsQuery.error.value,
    eventsQuery.error.value,
  ]
  for (const error of errors) {
    if (error instanceof ApiError && error.status !== 401 && error.status !== 403)
      return error
  }
  return null
})

const hasUnknownMainError = computed(() =>
  [docQuery.isError.value, snapshotQuery.isError.value, threadsQuery.isError.value, eventsQuery.isError.value]
    .some(Boolean) && !mainError.value,
)

const errorStatus = computed(() => {
  if (mainError.value)
    return mainError.value.status
  return hasUnknownMainError.value ? 0 : -1
})

/** 404 与 5xx / 网络失败整页替换；400 就近渲染。 */
const isFullPageError = computed(
  () => errorStatus.value === 404 || errorStatus.value === 0 || errorStatus.value >= 500,
)

/**
 * ⭐ 「失效的 `?version=`」这一档需要一个恢复出口（MN-02）。
 *
 * 正文端点对「版本不存在 / 不属于该 artifact」返 404（后端这是对的：带 `artifact_id` 约束
 * 防跨项目读版本）。但前端分档只看状态码 ⇒ 整页被换成中性 404，而页面上那个
 * 「回到当前版本」按钮此刻已经跟着整页一起被替换掉了 —— 一个 superseded 清理过的分享链接，
 * 会让一份**用户完全有权限、当前版本好好的**蓝图变成死路，只能手改 URL 或退回知识库重进。
 *
 * ⭐ 判据是**纯结构化**的三条 AND，⛔ 不读 `detail` 文本：
 * `?version=` 非空（是版本读）+ 正文 404（就是它挂了）+ 人审快照成功（不带 version 参数，
 * 它 200 就证明权限没问题、蓝图也在）。⚠️ 这不放宽任何存在性防线：中性文案一字不改，
 * 且这一档的前提本身就是「已经证明有权访问」。
 */
const isStaleVersionParam = computed(
  () => Boolean(versionParam.value)
    && docQuery.error.value instanceof ApiError
    && docQuery.error.value.status === 404
    && snapshotQuery.isSuccess.value,
)
const inlineErrorDetail = computed(() => (errorStatus.value === 400 ? (mainError.value?.detail ?? '') : ''))

// ── 导航段（⭐ 恒 10 项）──────────────────────────────────────────────────────

/** 段内条目数（用于 badge；⛔ 不影响段容器是否渲染）。 */
const sectionCounts = computed<Record<string, number>>(() => {
  const body = content.value
  const mustHaves = body?.must_haves
  return {
    requirement_spec: body?.requirement_spec?.feature_points?.length ?? 0,
    repo_associations: body?.repo_associations?.length ?? 0,
    current_state_analysis: (body?.current_state_analysis ?? []).reduce(
      (total, group) => total + (group.findings?.length ?? 0),
      0,
    ),
    implementation_overview: body?.implementation_overview?.items?.length ?? 0,
    api_contracts: body?.api_contracts?.length ?? 0,
    impact_analysis: body?.impact_analysis?.affected_features?.length ?? 0,
    interaction_flows: body?.interaction_flows?.length ?? 0,
    must_haves: (mustHaves?.truths?.length ?? 0) + (mustHaves?.artifacts?.length ?? 0) + (mustHaves?.key_links?.length ?? 0),
    decision_log: body?.decision_log?.length ?? 0,
    associations: Object.keys(body?.citations ?? {}).length + (body?.meta?.project_id ? 1 : 0),
  }
})

/** 由线程锚点的 `section_path` 反查所属段（取不到返回 `''`）。 */
function sectionOfThread(anchor: BlueprintAnchor | null): string {
  const head = String(anchor?.section_path ?? '').split(/[.[]/)[0]
  return (SECTION_KEYS as readonly string[]).includes(head) ? head : ''
}

/**
 * 段 badge 的色调（§6.1）：未决 BLOCKER → `danger`；open 澄清 → `warning`；
 * 生成中 → `primary`；其余 → `muted`。
 *
 * ⭐ 「未决 BLOCKER」走**共用判据** `isUnresolvedBlocker`（MJ-03）：本页曾有两个派生量各写
 * 一份口径，结果左栏段徽标标红、顶栏计数说 0，在同一个文件里自己跟自己打架。
 */
const sectionTones = computed<Record<string, NavSection['badgeTone']>>(() => {
  const tones: Record<string, NavSection['badgeTone']> = {}
  for (const key of SECTION_KEYS)
    tones[key] = isLive.value ? 'primary' : 'muted'
  for (const thread of threads.value) {
    const key = sectionOfThread(thread.anchor)
    if (!key)
      continue
    if (isUnresolvedBlocker(thread)) {
      tones[key] = 'danger'
      continue
    }
    if (thread.kind === 'ai_clarification' && thread.status === 'open' && tones[key] !== 'danger')
      tones[key] = 'warning'
  }
  return tones
})

/**
 * ⭐ badge 一律传空串而不是 `0`（P-18）。
 *
 * `AnchorNavLayout:95` 的空值判定是 `badge !== undefined && badge !== null && badge !== ''`
 * —— **它不排除 `0`** ⇒ 传数字 0 会在导航项右侧渲染出一个灰色的 `0`，被读成「有一项待办」。
 */
function badgeOf(key: string): string {
  const count = sectionCounts.value[key] ?? 0
  return count > 0 ? String(count) : ''
}

function toneOf(key: string): NavSection['badgeTone'] {
  return sectionTones.value[key] ?? 'muted'
}

function labelOf(suffix: string): string {
  return t(`knowledge.blueprints.section.${suffix}`)
}

// ── 段内三态 ─────────────────────────────────────────────────────────────────

function isSectionEmpty(key: string): boolean {
  return (sectionCounts.value[key] ?? 0) === 0
}

/** 生成中且该段尚无内容 ⇒ 段内出骨架 + 进度文案（⛔ 不做全页 loading）。 */
function isSectionPending(key: string): boolean {
  return isLive.value && isSectionEmpty(key)
}

/** 段级进度文案：命中事件优先，未被任何事件覆盖的段回落状态级文案（P-8 已在 composable 里降级）。 */
function progressTextOf(key: string): string {
  const progress = sectionProgress.value[key]
  if (progress)
    return t(progress.key, progress.payload as Record<string, unknown>)
  return statusProgressKey.value ? t(statusProgressKey.value) : ''
}

function skeletonOf(key: string): string[] {
  return SECTION_SKELETON[key] ?? ['h-16 w-full']
}

// ── 滚动与高亮 ───────────────────────────────────────────────────────────────

const highlightId = ref('')

/** ⭐ 页面统一处理跨段跳转：偏移与 `AnchorNavLayout` 共用 `measureScrollOffset`，⛔ 段组件内零滚动实现。 */
function scrollToDom(domId: string): void {
  if (!domId)
    return
  const el = document.getElementById(domId)
  if (!el)
    return
  window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - measureScrollOffset(), behavior: 'smooth' })
  highlightId.value = domId
  setTimeout(() => {
    if (highlightId.value === domId)
      highlightId.value = ''
  }, HIGHLIGHT_MS)
}

function sectionClass(key: string): string {
  return highlightId.value === key ? `space-y-4 scroll-mt-24 ${HIGHLIGHT_CLASS}` : 'space-y-4 scroll-mt-24'
}

function onGotoAnchor(domId: string): void {
  scrollToDom(domId)
}

function onNavigateSection(key: string): void {
  sectionParam.value = key
  scrollToDom(key)
}

// ── 侧栏 / 抽屉 / 选区 ────────────────────────────────────────────────────────

const sheetOpen = ref(false)
/** 按仓调研明细抽屉；由 stepper 的 `view-research` 打开。 */
const researchDrawerOpen = ref(false)
/** 抽屉打开时默认选中的仓（stepper 分组卡片点「查看明细」带过来）；缺省选第一个。 */
const researchInitialRepoId = ref('')

/** 打开调研抽屉；带 `initialRepositoryId` 时定位到该仓。 */
function openResearchDrawer(payload?: { initialRepositoryId?: string }): void {
  researchInitialRepoId.value = payload?.initialRepositoryId ?? ''
  researchDrawerOpen.value = true
}
const selection = ref<SelectionPayload | null>(null)

// ── 划线评论就地浮层（quick-260806-j1z，交互对齐飞书文档）───────────────────────
//
// 「发起评论」不再把草稿塞进右侧栏，而是在选区下方浮出评论输入卡；
// 点击正文划线在划线旁浮出线程卡。两者互斥（同一浮层组件的两种模式）。
const inlineDraft = ref<SelectionPayload | null>(null)
const inlineThreadId = ref<string | null>(null)
const inlineThreadRect = ref<DOMRect | null>(null)

const inlineThread = computed(() =>
  inlineThreadId.value ? findThread(inlineThreadId.value) ?? null : null,
)

function closeInlineThread(): void {
  inlineThreadId.value = null
  inlineThreadRect.value = null
  selectThread(null)
}

/**
 * ⭐ `xl` 断点闸（§5.2 逐字：`xl`（≥1280px）三栏、右侧线程侧栏常驻、**`Sheet` 停用**）。
 *
 * 字面量与 Tailwind 的 `xl` 同值；⛔ 不另设断点，改这里就得同步改常驻侧栏那行的 `xl:flex`。
 */
const XL_MEDIA_QUERY = '(min-width: 1280px)'
const isWide = useMediaQuery(XL_MEDIA_QUERY)

/** ⭐ §18.1：抽屉关闭后焦点回到唤起它的按钮。 */
watch(sheetOpen, (open) => {
  if (open)
    return
  nextTick(() => {
    document.querySelector<HTMLElement>('[data-testid="blueprint-header-open-annotations"]')?.focus()
  })
})

/**
 * 露出线程侧栏的**唯一入口**（UI-REVIEW H-2）。
 *
 * ⚠️ 四条程序化路径（选区「发起评论」/ 确认门 409 解药 / approve 409 清单跳转 / `?thread=`
 * 深链）原本各自无条件 `sheetOpen = true`。常驻侧栏是 `hidden xl:flex`、抽屉当时没有任何
 * 断点闸 ⇒ **≥1280px 下两者同时渲染同一个 `BlueprintThreadSidebar`**：草稿输入框出现两份，
 * 而 `draftBody` 是各自组件实例的局部 `ref`（`BlueprintThreadSidebar.vue`）—— 用户在其中
 * 一个里打的字，另一个里是空的。
 *
 * 因此宽屏只做一件事：**把常驻侧栏展开**（§5.2「`Sheet` 停用」+「`?thread=` 深链会强制
 * 展开」）。⛔ 宽屏不开抽屉；抽屉本体也由 `v-if="!isWide"` 从 DOM 上摘掉，任何时刻
 * 侧栏实例都只有一份。
 */
function revealAnnotations(): void {
  if (isWide.value) {
    viewerStore.sidebarCollapsed = false
    return
  }
  sheetOpen.value = true
}

/** 窄屏开着抽屉再拉宽 ⇒ 顺手收起，⛔ 否则再拉回窄屏时抽屉会「自己」弹回来。 */
watch(isWide, (wide) => {
  if (wide)
    sheetOpen.value = false
})

function onSelectionComment(payload: SelectionPayload): void {
  selection.value = payload
  // ⭐ 键盘路径（block 内「对此块评论」）：popover 是鼠标形态的浮层，键盘焦点进不去 ——
  // 直接进入草稿卡（与 popover 里点「发起评论」殊途同归）。
  if (payload.viaKeyboard)
    startDraft()
}

function onCrossBlockSelection(): void {
  toast.info(t('knowledge.blueprints.annotation.crossBlock'))
}

function startDraft(): void {
  const payload = selection.value
  if (!payload)
    return
  // ⭐ 飞书式就地输入卡（quick-260806-j1z）：草稿不再进右侧栏，⛔ 不再 revealAnnotations。
  inlineThreadId.value = null
  inlineThreadRect.value = null
  inlineDraft.value = payload
  selection.value = null
}

async function copySelection(): Promise<void> {
  const text = selection.value?.quotedText ?? ''
  selection.value = null
  try {
    await navigator.clipboard?.writeText(text)
  }
  catch {
    // 复制失败不反噬主流程
  }
}

/**
 * 点击正文划线 ⇒ 在划线旁就地浮出线程卡（quick-260806-j1z，飞书文档式）。
 *
 * 矩形取该线程**第一枚** `<mark>`；整块降级（角标）没有 mark ⇒ 回退锚点块矩形；
 * 两者都取不到（如失锚）⇒ 退回旧行为（拉开侧栏看）。侧栏选中态仍同步（selectThread）。
 */
function onThreadClick(threadId: string): void {
  selectThread(threadId)
  inlineDraft.value = null
  const mark = document.querySelector(
    `[data-testid="blueprint-annotation-mark"][data-thread-id="${threadId}"]`,
  )
  if (mark) {
    inlineThreadRect.value = mark.getBoundingClientRect()
    inlineThreadId.value = threadId
    return
  }
  const anchor = findThread(threadId)?.anchor
  const blockEl = anchor?.block_id ? document.getElementById(`blk-${anchor.block_id}`) : null
  if (blockEl) {
    inlineThreadRect.value = blockEl.getBoundingClientRect()
    inlineThreadId.value = threadId
    return
  }
  revealAnnotations()
}

/** 就地输入卡提交：复用 onCreateComment，成功才关卡（失败保留已输入内容）。 */
async function onInlineCommentSubmit(body: string): Promise<void> {
  const payload = inlineDraft.value
  if (!payload)
    return
  const ok = await onCreateComment(body, {
    blockId: payload.blockId,
    startOffset: payload.startOffset,
    endOffset: payload.endOffset,
    quotedText: payload.quotedText,
  })
  if (ok)
    inlineDraft.value = null
}

/**
 * ⭐ §18.2 焦点归还：引用预览是**纯受控**弹层（没有 `DialogTrigger`）。
 *
 * reka-ui 的自动归还依赖 Trigger，这里没有 ⇒ `onCloseAutoFocus` 会把焦点丢回 `<body>`，
 * 键盘用户关掉弹层后得从文档顶部重新 Tab 一遍。范式与上面 `Sheet` 那处一致，区别是
 * 触发元素不是固定的顶栏按钮而是**被点的那一枚 citation chip** ⇒ 必须在开弹层**之前**
 * 把 `document.activeElement` 记下来。
 */
const citationTrigger = ref<HTMLElement | null>(null)

function onCitationClick(citationId: string): void {
  const citation = citations.value[citationId]
  if (!citation)
    return
  citationTrigger.value = document.activeElement as HTMLElement | null
  openWithSnapshot(citation)
}

watch(previewOpen, (open) => {
  if (open)
    return
  const trigger = citationTrigger.value
  citationTrigger.value = null
  nextTick(() => trigger?.focus())
})

/**
 * 115-07：确认门 `confirm/` 409 `pending_clarification` 的解药落点。
 *
 * kind 分组恒 `defaultOpen`，所以「展开未决组」要做的是**把它露出来**：展开侧栏
 * （xl 及以上）+ 打开抽屉（窄屏）+ 关掉已关闭批注的显示（降噪，未决条目恒排各组最前）。
 * kind 筛选 chips 已随按 kind 分组废弃，无需再清 kind 筛选。⛔ 不弹 toast ——
 * 面板内已有提示与入口，再弹一条只是重复。
 */
function onGotoUnresolved(): void {
  viewerStore.sidebarCollapsed = false
  viewerStore.showClosedAnnotations = false
  revealAnnotations()
}

// ── 动作端点（⭐ 零乐观更新，一律以响应体 current_status 为准 + 前缀失效）────────────

const submitting = ref(false)
const rejectOpen = ref(false)
const blockedOpen = ref(false)
const blockedThreadIds = ref<string[]>([])

/** ⭐ 前缀匹配失效（本页只有一个 artifact，全域失效无副作用）。 */
function invalidateBlueprint(): void {
  queryClient.invalidateQueries({ queryKey: ['blueprint'] })
}

/** 400 原样回显后端 detail，其余落到「暂时读取不到」。 */
function reportFailure(error: unknown): void {
  if (error instanceof ApiError) {
    if (error.status === 400) {
      toast.error(error.detail)
      return
    }
    if (error.status === 409) {
      toast.error(t('knowledge.blueprints.error.conflict'), error.detail)
      invalidateBlueprint()
      return
    }
  }
  toast.error(t('knowledge.blueprints.error.unavailable'))
}

async function onApprove(): Promise<void> {
  if (submitting.value)
    return
  submitting.value = true
  try {
    await blueprintsApi.approveBlueprint(artifactId.value)
    toast.success(t('knowledge.blueprints.review.approveSuccess'))
    invalidateBlueprint()
  }
  catch (error) {
    // ⭐ 409 blocked：把 `unresolved_blocker_thread_ids` 逐条渲染成可点处置入口 ——
    // 那是超界死锁的唯一解药，只弹一句「不可确认」等于把用户锁死在原地。
    if (error instanceof ApiError && error.status === 409) {
      const body = (error.body ?? {}) as Record<string, unknown>
      const ids = Array.isArray(body.unresolved_blocker_thread_ids)
        ? body.unresolved_blocker_thread_ids.map(String)
        : []
      if (ids.length > 0) {
        blockedThreadIds.value = ids
        blockedOpen.value = true
        return
      }
    }
    reportFailure(error)
  }
  finally {
    submitting.value = false
  }
}

async function onRejectSubmit(payload: BlueprintRejectPayload): Promise<void> {
  if (submitting.value)
    return
  submitting.value = true
  try {
    const result = await blueprintsApi.rejectBlueprint(artifactId.value, payload)
    rejectOpen.value = false
    // ⭐ 回显用**响应体**的 rework_scope，⛔ 不用请求里那个：后端对非法值回落 merge，
    // 回显请求值会告诉用户「已完整重做」而实际只重跑了融合。
    toast.success(
      `${t('knowledge.blueprints.review.rejectSuccess', { n: result.revision_round })} · ${
        t(`knowledge.blueprints.review.reworkScope.${result.rework_scope}`)}`,
    )
    invalidateBlueprint()
  }
  catch (error) {
    if (error instanceof ApiError && error.status === 409) {
      const body = (error.body ?? {}) as Record<string, unknown>
      toast.error(t('knowledge.blueprints.error.conflictVersion', { version_no: body.version_no ?? '' }))
      invalidateBlueprint()
      return
    }
    reportFailure(error)
  }
  finally {
    submitting.value = false
  }
}

/**
 * 带指令重跑某个流程节点（quick-260806 节点重跑）。
 *
 * `stage` 已由 stepper 映射成**后端 stage key**（confirmation → repo_confirmation）。
 * 三档：**200 accepted** 提示新轮次并前缀失效（stepper 随 stages/snapshot 重取自动进入
 * 运行态）；**400 / 409** 原样回显后端 `detail`（409 额外失效以拉齐并发后的最新态）。
 * ⛔ 零乐观更新 —— 与其余动作端点同一纪律。
 */
async function onStageRerun(payload: { stage: string, instruction: string }): Promise<void> {
  if (submitting.value)
    return
  submitting.value = true
  try {
    const result = await blueprintsApi.rerunBlueprintStage(artifactId.value, {
      stage: payload.stage,
      instruction: payload.instruction || undefined,
    })
    toast.success(t('knowledge.blueprints.rerun.accepted', { label: result.run_label }))
    invalidateBlueprint()
  }
  catch (error) {
    if (error instanceof ApiError && (error.status === 400 || error.status === 409)) {
      toast.error(error.detail)
      if (error.status === 409)
        invalidateBlueprint()
      return
    }
    reportFailure(error)
  }
  finally {
    submitting.value = false
  }
}

/**
 * 导出到飞书（Phase 116-05，VIEW-05）。
 *
 * 三档分档：**200** 成功并给一个可点的文档链接；**400** 原样回显后端中性 `detail`
 * （配置/权限类，重试也不会好）；**502** 上游暂不可用，提示稍后重试。
 *
 * ⛔ **零乐观更新**；⛔ **不 invalidate `['blueprint']` 前缀** —— 导出不改任何蓝图状态，
 * 失效等于白刷五个查询。
 */
const exporting = ref(false)

async function onExportToFeishu(): Promise<void> {
  if (exporting.value)
    return
  exporting.value = true
  try {
    const result = await blueprintsApi.exportBlueprintToFeishu(artifactId.value)
    toast.toast.success(t('knowledge.blueprints.export.success'), {
      description: result.url,
      action: {
        label: t('knowledge.blueprints.export.openDoc'),
        onClick: () => window.open(result.url, '_blank', 'noopener'),
      },
    })
  }
  catch (error) {
    if (error instanceof ApiError && error.status === 400) {
      toast.error(error.detail)
      return
    }
    toast.error(t('knowledge.blueprints.export.unavailable'))
  }
  finally {
    exporting.value = false
  }
}

/**
 * 回复澄清 / 评论线程。
 *
 * ⭐ 端点**恒 200**，`reflow.status` 只决定语气：`applied` 成功 / `unchanged` · `noop` 提示 /
 * `conflict` 警告并列出冲突块 / `failed` · `invalid` 警告。⛔ **任何分支都不当作失败**，
 * 也不渲染红色错误态、不回滚 UI —— 否则用户会重复提交，答案重复落库。
 */
async function onAnswer(threadId: string, body: string): Promise<void> {
  if (submitting.value)
    return
  submitting.value = true
  try {
    const result = await blueprintsApi.answerThread(artifactId.value, threadId, { body })
    const status = String(result.reflow?.status ?? '')
    if (status === 'applied')
      toast.success(t('knowledge.blueprints.review.answerApplied', { version_no: result.reflow.version_no }))
    else if (status === 'unchanged' || status === 'noop')
      toast.info(t('knowledge.blueprints.review.answerUnchanged'))
    else if (status === 'conflict')
      toast.warning(t('knowledge.blueprints.review.answerConflict'), (result.reflow.conflict_block_ids ?? []).join(' · '))
    else
      toast.warning(t('knowledge.blueprints.review.answerFailed'))
    invalidateBlueprint()
  }
  catch (error) {
    reportFailure(error)
  }
  finally {
    submitting.value = false
  }
}

function onResolve(threadId: string, reason: string): void {
  void onFindingAction('resolve', threadId, reason)
}

function onDismiss(threadId: string, reason: string): void {
  void onFindingAction('dismiss', threadId, reason)
}

async function onFindingAction(kind: 'resolve' | 'dismiss', threadId: string, reason: string): Promise<void> {
  if (submitting.value)
    return
  submitting.value = true
  try {
    const call = kind === 'resolve' ? blueprintsApi.resolveFinding : blueprintsApi.dismissFinding
    const result = await call(artifactId.value, threadId, { reason })
    if (String(result.status) === 'noop')
      toast.info(t('knowledge.blueprints.finding.noopNotice'))
    else if (kind === 'resolve')
      toast.success(t('knowledge.blueprints.finding.resolveSuccess'))
    else
      toast.success(t('knowledge.blueprints.finding.dismissSuccess'))
    invalidateBlueprint()
  }
  catch (error) {
    reportFailure(error)
  }
  finally {
    submitting.value = false
  }
}

/** 返回是否创建成功（就地输入卡据此决定关卡还是保留已输入内容）。 */
async function onCreateComment(body: string, payload: BlueprintCommentDraft | null): Promise<boolean> {
  if (submitting.value)
    return false
  submitting.value = true
  try {
    await blueprintsApi.createBlueprintComment(artifactId.value, {
      body,
      anchor: payload
        ? {
            block_id: payload.blockId,
            start_offset: payload.startOffset,
            end_offset: payload.endOffset,
            quoted_text: payload.quotedText,
          }
        : undefined,
    })
    toast.success(t('knowledge.blueprints.thread.commentCreated'))
    invalidateBlueprint()
    return true
  }
  catch (error) {
    reportFailure(error)
    return false
  }
  finally {
    submitting.value = false
  }
}

// ── block 级人工编辑（CLAR-03 闭环相位）─────────────────────────────────────────

const editOpen = ref(false)
const editingBlockId = ref('')
const editErrorDetail = ref('')
const editRejected = ref<BlueprintBlockEditRejection[]>([])
const editConflict = ref(false)

/** 在**当前正文**里按 `block_id` 反查块；查不到返回 `null`（版本已推进 / 块已被删）。 */
function findBlock(blockId: string): BlueprintBlock | null {
  if (!blockId)
    return null
  return iterBlocks(content.value).find(item => item.block.block_id === blockId)?.block ?? null
}

const selectedBlock = computed(() => findBlock(selection.value?.blockId ?? ''))
const editingBlock = computed(() => findBlock(editingBlockId.value))

/**
 * ⭐ 编辑入口的可达性闸 —— 判据整体下沉到 `canEditBlueprintBlock`（那份纯函数的三个条件与
 * 上面 `readonly` 的三个条件逐条同构）。为假时「编辑此块」**不存在于 DOM**（§7.9 的
 * 「不渲染而非 disabled」，与终审两按钮的 `disabled` 形态刻意不同），而 115 已有的
 * `blueprint-readonly-notice` 只读提示条照常渲染 —— 不可编辑状态下的交代由它承担。
 */
const canEditSelection = computed(
  () => canEditBlueprintBlock(currentStatus.value, selectedBlock.value, {
    historicalVersion: isHistoricalVersion.value,
    diffMode: isDiffMode.value,
  }),
)

function startBlockEdit(): void {
  const blockId = selection.value?.blockId ?? ''
  selection.value = null
  if (!blockId)
    return
  editingBlockId.value = blockId
  editErrorDetail.value = ''
  editRejected.value = []
  editConflict.value = false
  editOpen.value = true
}

/** 冲突态的唯一解药：丢掉这次编辑，拿最新正文重来。 */
function onBlockEditRefresh(): void {
  editOpen.value = false
  editConflict.value = false
  invalidateBlueprint()
}

/**
 * 提交 block 编辑。
 *
 * 三档：**200 applied** 落新版本（`human_edit:` 归属）；**200 unchanged** 同 hash 未翻版本
 * （提示语气，⛔ 不当失败）；**400** 就近回显在弹窗里，其中 `rejected` 含 `block_not_found`
 * 的那一档单独判为**冲突**（基线已被推进），给刷新出口。
 *
 * ⛔ 400 时**不关窗**：关掉等于把用户刚写的正文一并丢掉，而这一档恰恰是最需要让人看清
 * 「哪一条没被应用」的时候。
 */
async function onBlockEditSubmit(ops: BlueprintBlockOp[]): Promise<void> {
  if (submitting.value)
    return
  submitting.value = true
  editErrorDetail.value = ''
  editRejected.value = []
  try {
    const result = await blueprintsApi.editBlueprintBlocks(artifactId.value, { ops })
    editOpen.value = false
    if (String(result.status) === 'unchanged')
      toast.info(t('knowledge.blueprints.edit.unchanged'))
    else
      toast.success(t('knowledge.blueprints.edit.applied', { version_no: result.version_no }))
    invalidateBlueprint()
  }
  catch (error) {
    if (error instanceof ApiError && error.status === 400) {
      const body = (error.body ?? {}) as Record<string, unknown>
      const rejected = Array.isArray(body.rejected)
        ? (body.rejected as BlueprintBlockEditRejection[])
        : []
      editRejected.value = rejected
      editConflict.value = rejected.some(item => String(item?.reason) === 'block_not_found')
      editErrorDetail.value = editConflict.value ? '' : (error.detail ?? '')
      return
    }
    reportFailure(error)
  }
  finally {
    submitting.value = false
  }
}

function onGotoBlockedThread(threadId: string): void {
  selectThread(threadId)
  revealAnnotations()
  const anchor = findThread(threadId)?.anchor
  nextTick(() => {
    if (anchor?.block_id)
      scrollToDom(`blk-${anchor.block_id}`)
  })
}

/**
 * 一次 `router.replace` 批量摘掉多个 query 键。
 *
 * ⚠️ **⛔ 不要改成逐个写 param ref**：每个 ref 的 watcher 各自 `router.replace({
 * ...route.query })`，而 `replace` 是异步的 —— 同一 tick 里第二次写会拿**旧** query
 * 合并，把第一次清掉的键原样带回来（「退出 diff」点了没反应的根因）。批量清除只发
 * 一次导航，各 ref 由 `route.query` 的反向 watcher 自然同步。
 */
function clearQueryParams(...keys: string[]): void {
  const query = { ...(route.query as Record<string, string>) }
  for (const key of keys)
    delete query[key]
  router.replace({ query })
}

function backToCurrentVersion(): void {
  clearQueryParams('version', 'diff', 'diff_mode')
}

/** 退出 diff 模式：只清 `?diff=` 族（`?version=` 保留——用户可能正查看某个历史版本）。 */
function exitDiffMode(): void {
  clearQueryParams('diff', 'diff_mode')
}

// ── 深链的一次性消费（§4.1）────────────────────────────────────────────────────

const threadConsumed = ref(false)
const panelConsumed = ref(false)

watch(
  [threadParam, () => threadsQuery.isSuccess.value],
  () => {
    if (threadConsumed.value || !threadParam.value || !threadsQuery.isSuccess.value)
      return
    threadConsumed.value = true
    const threadId = threadParam.value
    selectThread(threadId)
    revealAnnotations()
    const anchor = findThread(threadId)?.anchor
    nextTick(() => {
      if (anchor?.block_id)
        scrollToDom(`blk-${anchor.block_id}`)
    })
    threadParam.value = ''
  },
  { immediate: true },
)

watch(
  [panelParam, gateSettled, currentStatus],
  () => {
    if (panelConsumed.value || !panelParam.value)
      return
    if (panelParam.value === 'gate') {
      if (!gateSettled.value)
        return
      panelConsumed.value = true
      // ⭐ 目标缺席 ⇒ 静默忽略：确认门未开启是绝对多数的正常态，为它弹提示等于
      // 把正常态渲染成异常。⛔ 不滚动、不报错、不提示，只把 query 摘掉。
      if (gateAvailable.value)
        nextTick(() => scrollToDom('gate'))
      panelParam.value = ''
      return
    }
    if (!currentStatus.value)
      return
    panelConsumed.value = true
    if (REVIEW_PANEL_STATUSES.has(currentStatus.value)) {
      nextTick(() => scrollToDom('blueprint-quality'))
    }
    else {
      // 用户拿着旧链接来的信息缺口，静默会让人以为页面坏了。
      window.scrollTo({ top: 0, behavior: 'smooth' })
      toast.info(t('knowledge.blueprints.review.panelUnavailable'))
    }
    panelParam.value = ''
  },
  { immediate: true },
)

/**
 * ⭐ `?section=` 深链的定位时机 = **正文数据落地之后**（一次性消费）。
 *
 * 原先只在 `onMounted` 定位一次：那一刻十段还是骨架高度，目标段可能在 3 万像素外，
 * 数据到位后内容膨胀而滚动不重做 ⇒ 深链实测永远停在顶部、静默失效。
 * `immediate: true` 覆盖「数据已在缓存、挂载即 success」的情形；rAF 让重排先完成。
 */
const sectionScrolled = ref(false)
watch(
  [() => docQuery.isSuccess.value, sectionParam],
  () => {
    if (sectionScrolled.value || !sectionParam.value || !docQuery.isSuccess.value)
      return
    sectionScrolled.value = true
    const target = sectionParam.value
    nextTick(() => requestAnimationFrame(() => scrollToDom(target)))
  },
  { immediate: true },
)

// ── 浮动导航：长文档的返回顶部 + 未决批注巡航 ─────────────────────────────────

const { y: windowScrollY } = useWindowScroll()
/** 滚过约 1.5 屏才出现，避免短文档上常驻一个没用的按钮。 */
const showBackTop = computed(() => windowScrollY.value > 1200)

function scrollBackToTop(): void {
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

/** 未决（open）且未失锚的线程 —— 巡航目标集合。 */
const openThreads = computed(
  () => threads.value.filter(thread => thread.status === 'open' && thread.anchor_status !== 'orphaned'),
)

/**
 * 跳到当前滚动位置之下的第一条未决批注（到底后回绕到第一条）。
 * 全部未决线程都无锚（如规格门系统线程）时退化为「选中 + 展开侧栏」。
 */
function gotoNextOpenThread(): void {
  const rows = openThreads.value
  if (!rows.length)
    return
  const positioned = rows
    .map((thread) => {
      const blockId = thread.anchor?.block_id
      const el = blockId ? document.getElementById(`blk-${blockId}`) : null
      return el ? { thread, top: el.getBoundingClientRect().top + window.scrollY } : null
    })
    .filter((row): row is { thread: BlueprintThreadDetail, top: number } => row !== null)
    .sort((a, b) => a.top - b.top)
  const cursor = window.scrollY + measureScrollOffset() + 1
  const next = positioned.find(row => row.top > cursor) ?? positioned[0]
  if (next) {
    selectThread(next.thread.thread_id)
    scrollToDom(`blk-${next.thread.anchor!.block_id}`)
    return
  }
  selectThread(rows[0].thread_id)
  revealAnnotations()
}

const hasKeyConclusions = computed(() => {
  const body = content.value
  return Boolean(
    body?.current_state_analysis?.length
    || body?.repo_associations?.length
    || body?.impact_analysis?.affected_features?.length,
  )
})

const qualityData = computed(() => docQuery.data.value?.quality ?? null)

const showQualityPanel = computed(
  () => Boolean(docQuery.data.value) && REVIEW_PANEL_STATUSES.has(currentStatus.value),
)

const activeSectionId = computed(() => sectionParam.value || SECTION_KEYS[0])

/**
 * ⭐ 导航项：**长度恒为 10**，⛔ 不按内容增删。
 *
 * `NavSection.icon` 收**完整类名**（`AnchorNavLayout:91` 直接把它拼进 `:class`）——
 * 与 `CompactEmptyState` / `StatusBadge` 收裸名的契约**不同，两者都对，⛔ 不要统一**。
 */
const sections = computed<NavSection[]>(() => [
  { id: 'requirement_spec', label: labelOf('requirementSpec'), icon: 'icon-[lucide--target]', badge: badgeOf('requirement_spec'), badgeTone: toneOf('requirement_spec') },
  { id: 'repo_associations', label: labelOf('repoAssociations'), icon: 'icon-[lucide--folder-git-2]', badge: badgeOf('repo_associations'), badgeTone: toneOf('repo_associations') },
  { id: 'current_state_analysis', label: labelOf('currentStateAnalysis'), icon: 'icon-[lucide--scan-eye]', badge: badgeOf('current_state_analysis'), badgeTone: toneOf('current_state_analysis') },
  { id: 'implementation_overview', label: labelOf('implementationOverview'), icon: 'icon-[lucide--layers]', badge: badgeOf('implementation_overview'), badgeTone: toneOf('implementation_overview') },
  { id: 'api_contracts', label: labelOf('apiContracts'), icon: 'icon-[lucide--plug]', badge: badgeOf('api_contracts'), badgeTone: toneOf('api_contracts') },
  { id: 'impact_analysis', label: labelOf('impactAnalysis'), icon: 'icon-[lucide--alert-triangle]', badge: badgeOf('impact_analysis'), badgeTone: toneOf('impact_analysis') },
  { id: 'interaction_flows', label: labelOf('interactionFlows'), icon: 'icon-[lucide--workflow]', badge: badgeOf('interaction_flows'), badgeTone: toneOf('interaction_flows') },
  { id: 'must_haves', label: labelOf('mustHaves'), icon: 'icon-[lucide--clipboard-check]', badge: badgeOf('must_haves'), badgeTone: toneOf('must_haves') },
  { id: 'decision_log', label: labelOf('decisionLog'), icon: 'icon-[lucide--gavel]', badge: badgeOf('decision_log'), badgeTone: toneOf('decision_log') },
  { id: 'associations', label: labelOf('associations'), icon: 'icon-[lucide--link]', badge: badgeOf('associations'), badgeTone: toneOf('associations') },
])
</script>

<template>
  <!-- ⭐ fluid：三栏工作台（左导航 + 正文 + 批注栏）固定开销 ~560px，默认 1400 封顶
       会把正文读写区压到 700px 以下（quick-260806 布局整改）。 -->
  <PageContainer fluid>
    <!-- ⭐ 404 / 5xx：整页替换，且不渲染任何蓝图元信息 -->
    <BlueprintErrorState
      v-if="isFullPageError"
      :status="errorStatus"
      :detail="mainError?.detail ?? ''"
      :show-back-to-current-version="isStaleVersionParam"
      @retry="refetchAll()"
      @back-to-current="backToCurrentVersion()"
    />

    <template v-else>
      <BlueprintViewerHeader
        :doc="docQuery.data.value ?? null"
        :counts="{ blocker: unresolvedBlockerCount, clarification: counts.pendingClarification, orphaned: counts.orphaned }"
        :annotation-total="counts.total"
        :versions="versions"
        :stage-versions="stageVersions"
        :current-version-id="docQuery.data.value?.version_id ?? null"
        :readonly="readonly"
        :is-live="isLive"
        :show-closed="viewerStore.showClosedAnnotations"
        :sidebar-collapsed="viewerStore.sidebarCollapsed"
        :current-status="currentStatus"
        :revision-round="snapshotQuery.data.value?.revision_round ?? 0"
        :submitting="submitting"
        :export-available="exportAvailable"
        :exporting="exporting"
        @export="onExportToFeishu()"
        @toggle-sidebar="viewerStore.toggleSidebar()"
        @open-annotations="revealAnnotations()"
        @change-version="versionParam = $event"
        @open-diff="diffParam = $event"
        @approve="onApprove()"
        @reject="rejectOpen = true"
        @toggle-closed-annotations="viewerStore.showClosedAnnotations = $event"
      >
        <!-- ⭐ 段导航随头部同卡吸顶（quick-260806 布局整改：左栏纵向导航 → 头部横向导航，
             正文列拿回 ~200px）。滚动跟随高亮由组件内 observer 承担，页面只处理跳转。 -->
        <template #nav>
          <BlueprintSectionNav
            :sections="sections"
            :active-id="activeSectionId"
            @navigate="onNavigateSection"
          />
        </template>
      </BlueprintViewerHeader>

      <!-- 正文两栏：中栏正文 + 右批注栏（左栏段导航已并入头部横条）。
           偏移与页面 scrollToDom 共用 measureScrollOffset（sticky 头随横幅/导航条变高）。 -->
      <div>
        <div class="flex gap-6">
          <div class="min-w-0 flex-1 space-y-6">
            <!-- 400：就近渲染，原样回显后端 detail -->
            <BlueprintErrorState v-if="inlineErrorDetail" :status="400" :detail="inlineErrorDetail" />

            <!-- 历史版本：常驻只读提示 -->
            <!-- ⭐ diff 模式横幅：进入 diff 后**唯一**的退出入口（quick-260806 实测反馈：
                 只能进不能出）。优先于历史版本横幅 —— diff 才是当前视图的主语义。 -->
            <div
              v-if="isDiffMode"
              class="flex flex-wrap items-center gap-2 rounded-lg border border-info/40 bg-info/10 px-3 py-2 text-sm"
              role="status"
              data-testid="blueprint-diff-notice"
            >
              <span class="icon-[lucide--git-compare]" aria-hidden="true" />
              <span>{{ t('knowledge.blueprints.diff.notice', {
                base: diffBaseQuery.data.value?.version_no ?? '…',
                target: docQuery.data.value?.version_no ?? '…',
              }) }}</span>
              <Button variant="outline" size="sm" data-testid="blueprint-exit-diff" @click="exitDiffMode()">
                <span class="icon-[lucide--x] mr-1" aria-hidden="true" />
                {{ t('knowledge.blueprints.diff.exit') }}
              </Button>
            </div>

            <div
              v-else-if="isHistoricalVersion"
              class="flex flex-wrap items-center gap-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-sm"
              role="status"
              data-testid="blueprint-history-notice"
            >
              <span class="icon-[lucide--history]" aria-hidden="true" />
              <span>{{ t('knowledge.blueprints.version.historyNotice', { n: docQuery.data.value?.version_no ?? 0 }) }}</span>
              <Button variant="ghost" size="sm" data-testid="blueprint-back-to-current" @click="backToCurrentVersion()">
                {{ t('knowledge.blueprints.version.backToCurrent') }}
              </Button>
            </div>

            <div
              v-else-if="showReadonlyNotice"
              class="flex items-center gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground"
              role="status"
              data-testid="blueprint-readonly-notice"
            >
              <span class="icon-[lucide--lock]" aria-hidden="true" />
              <span>{{ t('knowledge.blueprints.readonly.notice') }}</span>
            </div>

            <!-- ⭐ 横向节点进度 stepper（quick-260806）：替换原「阶段时间线 + 阶段全景」两块
                 纵向面板 —— 八节点状态 / 节点详情 / stage_state 分片 / 带指令重跑收进一个组件。
                 `current-stage` / `current-status` 与旧时间线传同一对值：阶段状态推断委托
                 同一个 buildStageTimeline，喂不同入参会让两处对同一阶段给出不同状态。 -->
            <BlueprintStageStepper
              :events="events"
              :research-progress="researchProgress"
              :current-stage="eventsQuery.data.value?.current_stage ?? ''"
              :current-status="currentStatus"
              :stages="stagesData"
              :submitting="submitting"
              @rerun="onStageRerun"
              @view-research="researchDrawerOpen = true"
            />

            <!-- ⭐ 确认门（阶段 1 澄清）挂在正文**顶部**而非页尾：它是当前阻塞整条链的
                 待办动作，「跟哪些仓库关联」必须首屏可见（quick-260806 视觉整改：原先挂在
                 十段之后，离首屏 3 万像素，用户只能从侧栏问答卡猜内容）。
                 挂载条件仍只有一条：gate 查询 200；`#gate` 与 `blueprint-gate-mount` 是
                 `?panel=gate` 深链与侧栏「前往确认门」的滚动落点，随面板一起搬家。 -->
            <div v-if="gateAvailable" id="gate" data-testid="blueprint-gate-mount" :class="highlightId === 'gate' ? HIGHLIGHT_CLASS : ''" />

            <div v-if="gateAvailable && gateQuery.data.value" :class="highlightId === 'gate' ? HIGHLIGHT_CLASS : ''">
              <BlueprintGatePanel
                :artifact-id="artifactId"
                :snapshot="gateQuery.data.value"
                :submitting="submitting"
                @goto-unresolved="onGotoUnresolved"
              />
            </div>

            <!-- ⭐ 方案摘要（meta.summary）：融合阶段起草的 300~500 字人读导读，置于正文
                 十段之前（结论先行）。diff 视图下不渲染；旧版本无摘要时整卡缺席。 -->
            <div
              v-if="!isDiffMode && summaryBlocks.length"
              class="card px-4 py-3.5"
              data-testid="blueprint-meta-summary"
            >
              <p class="mb-1.5 text-xs font-medium text-muted-foreground">
                {{ t('knowledge.blueprints.viewer.summaryTitle') }}
              </p>
              <BlueprintBlockList
                class="max-w-208"
                :blocks="summaryBlocks"
                section-path="meta.summary"
                :threads="threads"
                :citations="citations"
                :readonly="readonly"
                :active-thread-id="activeThreadId"
                :show-closed="viewerStore.showClosedAnnotations"
                @thread-click="onThreadClick"
                @citation-click="onCitationClick"
                @selection-comment="onSelectionComment"
                @cross-block-selection="onCrossBlockSelection"
              />
            </div>

            <!-- diff 视图：批注层与全部写动作关闭（readonly 已置真） -->
            <BlueprintBlockDiff
              v-if="isDiffMode && diffBaseQuery.data.value && docQuery.data.value"
              :base-doc="diffBaseQuery.data.value"
              :target-doc="docQuery.data.value"
              :mode="diffMode"
              @update:mode="diffModeParam = $event"
            />

            <!-- ⭐⭐ 十个段容器：无条件渲染、id 为静态字面量、长度恒为 10（P-4）。
                 骨架 / 进度 / 实渲 / 空态三态全部发生在容器内部。 -->
            <section id="requirement_spec" :class="sectionClass('requirement_spec')" data-testid="blueprint-section-requirement-spec">
              <h2 class="text-base font-semibold">
                {{ labelOf('requirementSpec') }}
              </h2>
              <template v-if="!isDiffMode">
                <div v-if="docQuery.isLoading.value || isSectionPending('requirement_spec')" class="space-y-2" aria-busy="true">
                  <Skeleton v-for="(shape, index) in skeletonOf('requirement_spec')" :key="index" :class="shape" />
                  <p v-if="isSectionPending('requirement_spec')" class="text-xs text-muted-foreground" aria-live="polite">
                    {{ progressTextOf('requirement_spec') }}
                  </p>
                </div>
                <RequirementSpecSection
                  v-else
                  :spec="content?.requirement_spec ?? null"
                  :threads="threads"
                  :citations="citations"
                  :readonly="readonly"
                  :active-thread-id="activeThreadId"
                  :show-closed="viewerStore.showClosedAnnotations"
                  @thread-click="onThreadClick"
                  @citation-click="onCitationClick"
                  @selection-comment="onSelectionComment"
                  @cross-block-selection="onCrossBlockSelection"
                />
              </template>
            </section>

            <section id="repo_associations" :class="sectionClass('repo_associations')" data-testid="blueprint-section-repo-associations">
              <h2 class="text-base font-semibold">
                {{ labelOf('repoAssociations') }}
              </h2>
              <template v-if="!isDiffMode">
                <div v-if="docQuery.isLoading.value || isSectionPending('repo_associations')" class="space-y-2" aria-busy="true">
                  <Skeleton v-for="(shape, index) in skeletonOf('repo_associations')" :key="index" :class="shape" />
                  <p v-if="isSectionPending('repo_associations')" class="text-xs text-muted-foreground" aria-live="polite">
                    {{ progressTextOf('repo_associations') }}
                  </p>
                </div>
                <RepoAssociationsSection
                  v-else
                  :associations="content?.repo_associations ?? []"
                  :repo-names="repoNames"
                  :threads="threads"
                  :citations="citations"
                  :readonly="readonly"
                  :active-thread-id="activeThreadId"
                  :show-closed="viewerStore.showClosedAnnotations"
                  @thread-click="onThreadClick"
                  @citation-click="onCitationClick"
                  @selection-comment="onSelectionComment"
                  @cross-block-selection="onCrossBlockSelection"
                />
              </template>
            </section>

            <section id="current_state_analysis" :class="sectionClass('current_state_analysis')" data-testid="blueprint-section-current-state">
              <h2 class="text-base font-semibold">
                {{ labelOf('currentStateAnalysis') }}
              </h2>
              <template v-if="!isDiffMode">
                <div v-if="docQuery.isLoading.value || isSectionPending('current_state_analysis')" class="space-y-2" aria-busy="true">
                  <Skeleton v-for="(shape, index) in skeletonOf('current_state_analysis')" :key="index" :class="shape" />
                  <p v-if="isSectionPending('current_state_analysis')" class="text-xs text-muted-foreground" aria-live="polite">
                    {{ progressTextOf('current_state_analysis') }}
                  </p>
                </div>
                <CurrentStateSection
                  v-else
                  :analysis="content?.current_state_analysis ?? []"
                  :repo-names="repoNames"
                  :feature-points="featurePointIndex"
                  :threads="threads"
                  :citations="citations"
                  :readonly="readonly"
                  :active-thread-id="activeThreadId"
                  :show-closed="viewerStore.showClosedAnnotations"
                  @goto-anchor="onGotoAnchor"
                  @thread-click="onThreadClick"
                  @citation-click="onCitationClick"
                  @selection-comment="onSelectionComment"
                  @cross-block-selection="onCrossBlockSelection"
                />
              </template>
            </section>

            <section id="implementation_overview" :class="sectionClass('implementation_overview')" data-testid="blueprint-section-implementation-overview">
              <h2 class="text-base font-semibold">
                {{ labelOf('implementationOverview') }}
              </h2>
              <template v-if="!isDiffMode">
                <div v-if="docQuery.isLoading.value || isSectionPending('implementation_overview')" class="space-y-2" aria-busy="true">
                  <Skeleton v-for="(shape, index) in skeletonOf('implementation_overview')" :key="index" :class="shape" />
                  <p v-if="isSectionPending('implementation_overview')" class="text-xs text-muted-foreground" aria-live="polite">
                    {{ progressTextOf('implementation_overview') }}
                  </p>
                </div>
                <ImplementationOverviewSection
                  v-else
                  :overview="content?.implementation_overview ?? null"
                  :repo-names="repoNames"
                  :feature-points="featurePointIndex"
                  :threads="threads"
                  :citations="citations"
                  :readonly="readonly"
                  :active-thread-id="activeThreadId"
                  :show-closed="viewerStore.showClosedAnnotations"
                  @goto-anchor="onGotoAnchor"
                  @thread-click="onThreadClick"
                  @citation-click="onCitationClick"
                  @selection-comment="onSelectionComment"
                  @cross-block-selection="onCrossBlockSelection"
                />
              </template>
            </section>

            <section id="api_contracts" :class="sectionClass('api_contracts')" data-testid="blueprint-section-api-contracts">
              <h2 class="text-base font-semibold">
                {{ labelOf('apiContracts') }}
              </h2>
              <template v-if="!isDiffMode">
                <div v-if="docQuery.isLoading.value || isSectionPending('api_contracts')" class="space-y-2" aria-busy="true">
                  <Skeleton v-for="(shape, index) in skeletonOf('api_contracts')" :key="index" :class="shape" />
                  <p v-if="isSectionPending('api_contracts')" class="text-xs text-muted-foreground" aria-live="polite">
                    {{ progressTextOf('api_contracts') }}
                  </p>
                </div>
                <ApiContractsSection
                  v-else
                  :contracts="content?.api_contracts ?? []"
                  :repo-names="repoNames"
                  :threads="threads"
                  :citations="citations"
                  :readonly="readonly"
                  :active-thread-id="activeThreadId"
                  :show-closed="viewerStore.showClosedAnnotations"
                  @thread-click="onThreadClick"
                  @citation-click="onCitationClick"
                  @selection-comment="onSelectionComment"
                  @cross-block-selection="onCrossBlockSelection"
                />
              </template>
            </section>

            <section id="impact_analysis" :class="sectionClass('impact_analysis')" data-testid="blueprint-section-impact-analysis">
              <h2 class="text-base font-semibold">
                {{ labelOf('impactAnalysis') }}
              </h2>
              <template v-if="!isDiffMode">
                <div v-if="docQuery.isLoading.value || isSectionPending('impact_analysis')" class="space-y-2" aria-busy="true">
                  <Skeleton v-for="(shape, index) in skeletonOf('impact_analysis')" :key="index" :class="shape" />
                  <p v-if="isSectionPending('impact_analysis')" class="text-xs text-muted-foreground" aria-live="polite">
                    {{ progressTextOf('impact_analysis') }}
                  </p>
                </div>
                <ImpactAnalysisSection
                  v-else
                  :impact="content?.impact_analysis ?? null"
                  :repo-names="repoNames"
                  :threads="threads"
                  :citations="citations"
                  :readonly="readonly"
                  :active-thread-id="activeThreadId"
                  :show-closed="viewerStore.showClosedAnnotations"
                  @thread-click="onThreadClick"
                  @citation-click="onCitationClick"
                  @selection-comment="onSelectionComment"
                  @cross-block-selection="onCrossBlockSelection"
                />
              </template>
            </section>

            <section id="interaction_flows" :class="sectionClass('interaction_flows')" data-testid="blueprint-section-interaction-flows">
              <h2 class="text-base font-semibold">
                {{ labelOf('interactionFlows') }}
              </h2>
              <template v-if="!isDiffMode">
                <div v-if="docQuery.isLoading.value || isSectionPending('interaction_flows')" class="space-y-2" aria-busy="true">
                  <Skeleton v-for="(shape, index) in skeletonOf('interaction_flows')" :key="index" :class="shape" />
                  <p v-if="isSectionPending('interaction_flows')" class="text-xs text-muted-foreground" aria-live="polite">
                    {{ progressTextOf('interaction_flows') }}
                  </p>
                </div>
                <InteractionFlowsSection
                  v-else
                  :flows="content?.interaction_flows ?? []"
                  :threads="threads"
                  :citations="citations"
                  :readonly="readonly"
                  :active-thread-id="activeThreadId"
                  :show-closed="viewerStore.showClosedAnnotations"
                  @goto-anchor="onGotoAnchor"
                  @thread-click="onThreadClick"
                  @citation-click="onCitationClick"
                  @selection-comment="onSelectionComment"
                  @cross-block-selection="onCrossBlockSelection"
                />
              </template>
            </section>

            <!-- ⭐ must_haves / decision_log / associations 三段不收 blockCtx（零 block_id 可锚） -->
            <section id="must_haves" :class="sectionClass('must_haves')" data-testid="blueprint-section-must-haves">
              <h2 class="text-base font-semibold">
                {{ labelOf('mustHaves') }}
              </h2>
              <template v-if="!isDiffMode">
                <div v-if="docQuery.isLoading.value || isSectionPending('must_haves')" class="space-y-2" aria-busy="true">
                  <Skeleton v-for="(shape, index) in skeletonOf('must_haves')" :key="index" :class="shape" />
                  <p v-if="isSectionPending('must_haves')" class="text-xs text-muted-foreground" aria-live="polite">
                    {{ progressTextOf('must_haves') }}
                  </p>
                </div>
                <MustHavesSection v-else :must-haves="content?.must_haves ?? null" />
              </template>
            </section>

            <section id="decision_log" :class="sectionClass('decision_log')" data-testid="blueprint-section-decision-log">
              <h2 class="text-base font-semibold">
                {{ labelOf('decisionLog') }}
              </h2>
              <template v-if="!isDiffMode">
                <div v-if="docQuery.isLoading.value || isSectionPending('decision_log')" class="space-y-2" aria-busy="true">
                  <Skeleton v-for="(shape, index) in skeletonOf('decision_log')" :key="index" :class="shape" />
                  <p v-if="isSectionPending('decision_log')" class="text-xs text-muted-foreground" aria-live="polite">
                    {{ progressTextOf('decision_log') }}
                  </p>
                </div>
                <DecisionLogSection
                  v-else
                  :decision-log="content?.decision_log ?? []"
                  :deferred-ideas="content?.deferred_ideas ?? []"
                  @open-thread="onGotoBlockedThread"
                />
              </template>
            </section>

            <section id="associations" :class="sectionClass('associations')" data-testid="blueprint-section-associations">
              <h2 class="text-base font-semibold">
                {{ labelOf('associations') }}
              </h2>
              <template v-if="!isDiffMode">
                <div v-if="docQuery.isLoading.value || isSectionPending('associations')" class="space-y-2" aria-busy="true">
                  <Skeleton v-for="(shape, index) in skeletonOf('associations')" :key="index" :class="shape" />
                  <p v-if="isSectionPending('associations')" class="text-xs text-muted-foreground" aria-live="polite">
                    {{ progressTextOf('associations') }}
                  </p>
                </div>
                <BlueprintAssociationsSection
                  v-else
                  :artifact-id="artifactId"
                  :citations="citations"
                  :project-id="docQuery.data.value?.project_id ?? content?.meta?.project_id ?? null"
                  :project-name="docQuery.data.value?.project_name ?? ''"
                  :knowledge-entity-id="docQuery.data.value?.knowledge_entity_id ?? null"
                  @citation-click="onCitationClick"
                />
              </template>
            </section>

            <div
              v-if="showQualityPanel && qualityData"
              id="blueprint-quality"
              :class="highlightId === 'blueprint-quality' ? HIGHLIGHT_CLASS : ''"
            >
              <BlueprintQualityPanel
                :quality="qualityData"
                :has-key-conclusions="hasKeyConclusions"
              />
            </div>
          </div>

          <!-- 第三栏：xl 及以上常驻，可由顶栏折叠。
               ⭐ 宽度随视口升档（336 → 384）：这一栏装的是全页最密的多轮问答文本，
               320px 再扣两层卡片内边距只剩 ~270px 行宽，是「越往右越挤」的主因。
               ⭐ 吸顶偏移随头部实测高度（sidebarStickyStyle），⛔ 不再写静态 top-22 ——
               头部带段导航/横幅时静态值会把侧栏顶部埋进头下（圆角被裁的根因）。 -->
          <aside
            v-if="!viewerStore.sidebarCollapsed"
            class="sticky hidden w-84 shrink-0 xl:flex 2xl:w-96"
            :style="sidebarStickyStyle"
            data-testid="blueprint-sidebar-column"
          >
            <!-- ⭐ card 容器 = 面板头（常驻，不随滚动）+ 滚动正文；
                 内容 padding 收在 BlueprintThreadSidebar 里（分组吸顶头要全出血）。 -->
            <div class="card flex min-h-0 w-full flex-col overflow-hidden">
              <div class="flex shrink-0 items-center justify-between gap-2 border-b border-border/60 py-1.5 pr-1.5 pl-3.5">
                <div class="flex min-w-0 items-center gap-2">
                  <span class="icon-[lucide--messages-square] shrink-0 text-muted-foreground" aria-hidden="true" />
                  <!-- ⭐ 面板标题走 §14 Heading 档（text-base font-semibold）：写成 text-sm
                       会与正文同号，源码守卫（UI-REVIEW M-6）锁死该组合。 -->
                  <span class="text-base font-semibold text-foreground">
                    {{ t('knowledge.blueprints.annotation.sidebarTitle') }}
                  </span>
                  <Badge v-if="counts.total > 0" variant="muted">
                    {{ counts.total }}
                  </Badge>
                </div>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  :aria-label="t('knowledge.blueprints.annotation.sidebarCollapse')"
                  :title="t('knowledge.blueprints.annotation.sidebarCollapse')"
                  data-testid="blueprint-sidebar-panel-collapse"
                  @click="viewerStore.toggleSidebar()"
                >
                  <span class="icon-[lucide--panel-right-close] text-muted-foreground" aria-hidden="true" />
                </Button>
              </div>
              <ScrollArea class="min-h-0 flex-1">
                <BlueprintThreadSidebar
                  :threads="threads"
                  :orphaned-threads="orphanedThreads"
                  :active-thread-id="activeThreadId"
                  :readonly="readonly"
                  :show-closed="viewerStore.showClosedAnnotations"
                  :gate-available="gateAvailable"
                  :submitting="submitting"
                  :feature-point-titles="featurePointTitles"
                  @select="selectThread"
                  @answer="onAnswer"
                  @resolve="onResolve"
                  @dismiss="onDismiss"
                  @goto-gate="scrollToDom('gate')"
                  @goto-anchor="onGotoAnchor"
                  @create-comment="onCreateComment"
                  @update:show-closed="viewerStore.showClosedAnnotations = $event"
                />
              </ScrollArea>
            </div>
          </aside>
        </div>
      </div>

      <!-- ⭐ < xl：线程侧栏收成抽屉。`xl` 及以上抽屉**整块不存在于 DOM**（§5.2「Sheet 停用」）
           —— 与上面那个 `hidden xl:flex` 的常驻侧栏正好互补，任何宽度下侧栏实例恰好一份。
           ⛔ 不能只用 `xl:hidden` 把它藏起来：reka-ui 的焦点陷阱会锁进一个不可见容器里。 -->
      <Sheet v-if="!isWide" v-model:open="sheetOpen">
        <SheetContent side="right" class="w-full sm:max-w-md" data-testid="blueprint-sidebar-sheet">
          <SheetHeader>
            <!-- ⭐ 用独立的标题键：`sidebarToggleEmpty` 是**按钮**的零计数文案，
                 复用它会让「改按钮文案」连带改抽屉标题（键语义错位）。 -->
            <SheetTitle>{{ t('knowledge.blueprints.annotation.sidebarTitle') }}</SheetTitle>
          </SheetHeader>
          <ScrollArea class="h-full">
            <BlueprintThreadSidebar
              :threads="threads"
              :orphaned-threads="orphanedThreads"
              :active-thread-id="activeThreadId"
              :readonly="readonly"
              :show-closed="viewerStore.showClosedAnnotations"
              :gate-available="gateAvailable"
              :submitting="submitting"
              :feature-point-titles="featurePointTitles"
              @select="selectThread"
              @answer="onAnswer"
              @resolve="onResolve"
              @dismiss="onDismiss"
              @goto-gate="scrollToDom('gate')"
              @goto-anchor="onGotoAnchor"
              @create-comment="onCreateComment"
              @update:show-closed="viewerStore.showClosedAnnotations = $event"
            />
          </ScrollArea>
        </SheetContent>
      </Sheet>

      <!-- 按仓调研明细：结论 + agent 过程日志。⛔ 不进 5s 轮询，抽屉打开才取数。 -->
      <BlueprintResearchDrawer
        v-model:open="researchDrawerOpen"
        :artifact-id="artifactId"
      />

      <BlueprintSelectionPopover
        :rect="selection?.rect ?? null"
        :can-comment="!readonly"
        :can-edit="canEditSelection"
        @comment="startDraft()"
        @edit="startBlockEdit()"
        @copy="copySelection()"
        @dismiss="selection = null"
      />

      <!-- ⭐ 飞书式就地浮层（quick-260806-j1z）：draft 输入卡 / thread 线程卡二选一 -->
      <BlueprintCommentPopover
        v-if="inlineDraft"
        :rect="inlineDraft.rect"
        :quoted-text="inlineDraft.quotedText"
        :submitting="submitting"
        @submit="onInlineCommentSubmit"
        @close="inlineDraft = null"
      />
      <BlueprintCommentPopover
        v-else-if="inlineThread && inlineThreadRect"
        :rect="inlineThreadRect"
        :thread="inlineThread"
        :readonly="readonly"
        :submitting="submitting"
        :gate-available="gateAvailable"
        :feature-point-titles="featurePointTitles"
        @close="closeInlineThread"
        @answer="onAnswer"
        @resolve="onResolve"
        @dismiss="onDismiss"
        @goto-gate="scrollToDom('gate')"
        @goto-anchor="onGotoAnchor"
      />

      <BlueprintBlockEditDialog
        v-model:open="editOpen"
        :block="editingBlock"
        :submitting="submitting"
        :error-detail="editErrorDetail"
        :rejected="editRejected"
        :conflict="editConflict"
        @submit="onBlockEditSubmit"
        @refresh="onBlockEditRefresh()"
      />

      <BlueprintRejectDialog
        v-model:open="rejectOpen"
        :revision-round="snapshotQuery.data.value?.revision_round ?? 0"
        :submitting="submitting"
        :repositories="reworkRepositories"
        @submit="onRejectSubmit"
      />

      <BlueprintBlockedDialog
        v-model:open="blockedOpen"
        :thread-ids="blockedThreadIds"
        :threads="threads"
        @goto-thread="onGotoBlockedThread"
      />

      <CitationPreviewDialog v-model:open="previewOpen" :citation="previewCitation" />

      <!-- 浮动导航：38 屏长文档的位置感与未决项巡航（P1 修复） -->
      <div class="fixed bottom-6 right-6 z-40 flex flex-col items-end gap-2">
        <Button
          v-if="openThreads.length && !isDiffMode"
          variant="outline"
          size="sm"
          class="shadow-card"
          data-testid="blueprint-goto-next-open"
          @click="gotoNextOpenThread()"
        >
          <span class="icon-[lucide--corner-right-down] mr-1.5" aria-hidden="true" />
          {{ t('knowledge.blueprints.viewer.nextOpen', { n: openThreads.length }) }}
        </Button>
        <Button
          v-show="showBackTop"
          variant="outline"
          size="icon-sm"
          class="shadow-card"
          :aria-label="t('knowledge.blueprints.viewer.backToTop')"
          :title="t('knowledge.blueprints.viewer.backToTop')"
          data-testid="blueprint-back-to-top"
          @click="scrollBackToTop()"
        >
          <span class="icon-[lucide--arrow-up]" aria-hidden="true" />
        </Button>
      </div>
    </template>
  </PageContainer>
</template>
