<script setup lang="ts">
import type MarkdownIt from 'markdown-it'
import type { CodingPlanRuntime, ExportCodingPlanToFeishuResponse, ExportToFeishuResponse, RepoSelectableItem } from '~/types/chat'
/**
 * 技术方案卡片 — 落地， 扩展为多仓 fan-out 入口。
 *
 * CodingPlan 的主展示组件。承载 Markdown 渲染 + affected_files 列表 + 折叠/展开。
 *
 * 新增两种交互入口：
 *   - 创建态（无 sessions）：codingPlanId 提供时，把旧的「开始编码」单仓按钮
 *     替换为内嵌 RepoMultiSelector，让用户一次性挑多个仓库 fan-out。
 *   - 追加态（已有 sessions）：右上角「+ 对新仓库编码」按钮 + Dialog 弹层
 *     选新仓库；已选 active sessions 的 repo 在 selector 内 disabled。
 *
 * codingPlanId 未提供时（旧 ChatMessageBubble 单仓路径）保留原 draft 按钮，
 * 向后兼容不破。
 *
 * ⭐ **blueprint/v1 识别（同步点 2 收尾）**：从 blueprint/v1 版本投影出来的 CodingPlan，
 * 正文与影响文件走的是 v0 映射器（读 `execution_plan[]`、渲 v0 markdown），而 blueprint/v1
 * **没有那个顶层键** ⇒ 本卡此前会渲染出一份**结构合法而内容为空**的旧形态方案：空 prose
 * 块 + 空影响文件列表，且不给任何错误信号。现按投影响应的 `schema_version` 判别（口径与
 * 后端 `builtin_types.py` 逐字相同），命中即：如实说明形态、渲 11 态状态徽标、给出指向
 * 蓝图查看器的深链，⛔ 不再把空正文渲成「（暂无方案正文）」。
 *
 * 🔴 **v0 逐像素不变**：三个新 prop 全部可选且默认 `undefined`，`isBlueprint` 是**允许
 * 清单**（只有严格等于 `blueprint/v1` 才为真）⇒ 历史调用点与 v0 投影一行未改。
 */
import { storeToRefs } from 'pinia'
import { computed, onMounted, ref, watch, watchEffect } from 'vue'
import { RouterLink } from 'vue-router'
import CodingSessionStatusRow from '~/components/chat/CodingSessionStatusRow.vue'
import ExportConfirmDialog from '~/components/chat/ExportConfirmDialog.vue'
import RepoMultiSelector from '~/components/chat/RepoMultiSelector.vue'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '~/components/ui/alert-dialog'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Checkbox } from '~/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '~/components/ui/dialog'
import { Input } from '~/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '~/components/ui/select'
import { useBranchValidation } from '~/composables/useBranchValidation'
import { getMarkdownRenderer } from '~/composables/useMarkdownRenderer'
import { useToast } from '~/composables/useToast'
import {
  BLUEPRINT_ATTENTION_STATUSES,
  blueprintStatusText,
  blueprintViewerPath,
  isBlueprintSchemaVersion,
} from '~/config/blueprintArtifact'
import { useChatStore } from '~/stores/chat'

const props = withDefaults(defineProps<{
  planId: string
  title?: string
  techPlan: string
  affectedFiles: Array<{ file_path?: string, path?: string, change_type: string }>
  status: 'draft' | 'confirmed' | 'running' | 'awaiting_confirmation' | 'completed' | 'failed'
  isConfirming: boolean
  sessionId?: string
  branchName?: string
  defaultCollapsed?: boolean
  // ：completed 状态可选展示 PR / branch 链接
  prUrl?: string
  branchUrl?: string
  // ：failed 状态可选展示错误原因
  errorMessage?: string
  // ：多仓 fan-out 入口
  //
  // codingPlanId 提供时启用 multi-repo 流程（创建态 / 追加态 / 重试 / 状态行
  // 列表）；不提供时保留旧的 single-session draft 流程（向后兼容
  // ChatMessageBubble 历史调用）。
  codingPlanId?: string | null
  // 109-08（RELY-01）：方案来源标志。承载投影响应本地态（OrchestratedPlanCard
  // 把投影响应直接喂进 props）。类型故意含 string 而非收窄成枚举 —— 后端新增
  // 枚举值时前端要走保守分支（标注），而不是编译失败或静默放行。
  provenance?: string | null
  availableRepositories?: RepoSelectableItem[]
  repositoryGitUrls?: Record<string, string>
  recommendedRepositoryIds?: string[]
  targetRepositories?: RepoSelectableItem[]
  // ── 同步点 2 收尾：blueprint/v1 三个**纯追加**判别 prop ────────────────────
  //
  // 三者都可选、默认 undefined ⇒ 历史调用点（ChatMessageBubble 单仓路径 / v0 投影）
  // 一行不用改，卡片行为与改动前逐字相同。
  //
  // 类型故意含 string 而非收窄成枚举 —— 与 provenance 同一条纪律：后端新增取值时
  // 前端要走保守分支，而不是编译失败或静默放行。
  /** 来源 ArtifactVersion content 的 `schema_version`（v0 恒 `''` / 不传）。 */
  schemaVersion?: string | null
  /** 蓝图 artifact id —— 查看器深链的 `:id`（拿不到就不渲染深链）。 */
  blueprintArtifactId?: string | null
  /** 蓝图 11 态状态（键名与后端响应体一致：`current_status`，非模型字段名）。 */
  blueprintStatus?: string | null
}>(), {
  // 显式保留 undefined（Vue 默认会把缺省 Boolean prop coerce 成 false，
  // 那样会破坏 initialCollapsed 的 fallback 判定）
  defaultCollapsed: undefined,
  availableRepositories: () => [],
  repositoryGitUrls: () => ({}),
  recommendedRepositoryIds: () => [],
  targetRepositories: () => [],
})

const emit = defineEmits<{
  confirm: [planId: string, sessionId: string | undefined, branchName?: string, targetBranch?: string]
  // ：failed 状态下用户点击重试； 起当 codingPlanId
  // 存在时由 store.retrySingleRepository 接管，emit 仍保留作旧接口兜底。
  retry: [planId: string, sessionId: string | undefined]
}>()

// ---------------------------------------------------------------------------
// ：多仓 fan-out 状态机
// ---------------------------------------------------------------------------
const chatStore = useChatStore()
const { activeCodingPlan, repoMultiSelectorState } = storeToRefs(chatStore)
const { success: toastSuccess, error: toastError } = useToast()

/**
 * 本卡对应的 runtime。
 *
 * 🔴 `plan_id` 不匹配一律视为「没有」（109-REVIEW MN-05）：`activeCodingPlan` 的语义
 * 是「对话内**最近**一条 CodingPlan」，不匹配就采用等于把**别的 plan 的状态**渲染到
 * 本卡上。守卫下沉到 runtime 入口而不是每个消费点各写一遍——本组件此前已经把同一道
 * 守卫重复写了四遍（`feishuDocUrl` / `tech_plan` / `affected_files` / `provenance`），
 * 而 `sessions` 那一支漏了，于是投影后的轮询窗口里内嵌卡片会列出别的 plan 的 session
 * 行：选仓面因 `hasSessions` 为真而整块不渲染，用户在那些行上点「重试」还会在新 plan
 * 上建出一条本不该有的 session。加一个消费点就要记得加一次守卫的形状本身就是缺陷。
 *
 * `codingPlanId` 缺省（旧 ChatMessageBubble 单仓路径）时不设限，保持向后兼容。
 */
const codingPlanRuntime = computed<CodingPlanRuntime | null>(() => {
  const runtime = activeCodingPlan.value
  if (!runtime)
    return null
  if (props.codingPlanId && runtime.plan_id !== props.codingPlanId)
    return null
  return runtime
})
const sessions = computed(() => codingPlanRuntime.value?.sessions ?? [])
const hasSessions = computed(() => sessions.value.length > 0)

const ACTIVE_STATUSES = new Set(['draft', 'confirmed', 'running', 'awaiting_confirmation'])
const existingActiveRepoIds = computed(() =>
  sessions.value
    .filter(s => ACTIVE_STATUSES.has(s.status))
    .map(s => s.repository_id),
)

const showInlineSelector = computed(
  () => !!props.codingPlanId && !hasSessions.value,
)
const visibleTargetRepositories = computed(() => {
  if (props.targetRepositories.length > 0)
    return props.targetRepositories
  if (sessions.value.length > 0) {
    return sessions.value.map(s => ({
      id: s.repository_id,
      name: s.repository_name,
    }))
  }
  return props.availableRepositories.filter(repo =>
    props.recommendedRepositoryIds.includes(repo.id),
  )
})

const dialogOpen = ref(false)
const dialogSelectedIds = ref<string[]>([])
const branchTemplate = ref('')
const normalizedBranchTemplate = computed(() => branchTemplate.value.trim() || undefined)
// PR 目标分支：团队工作流默认并入 develop（非 master）。fan-out 时统一应用到所有仓库，
// 用户可改。各仓远端分支列表不一致，故用可编辑输入框而非下拉。
const targetBranch = ref('develop')
const normalizedTargetBranch = computed(() => targetBranch.value.trim() || undefined)

function openAppendDialog() {
  if (!props.codingPlanId)
    return
  dialogSelectedIds.value = []
  chatStore.openRepoMultiSelector(props.codingPlanId, [])
  dialogOpen.value = true
}

async function handleMultiConfirm(repoIds: string[]) {
  if (!props.codingPlanId)
    return
  // 109-08：创建态与追加态共用本函数 ⇒ 两条路径天然都过闸门
  const gate = await ensureUnresearchedAcknowledged()
  if (!gate.proceed)
    return
  try {
    chatStore.openRepoMultiSelector(props.codingPlanId, repoIds)
    const result = await chatStore.submitRepoMultiSelector(
      repoIds,
      normalizedBranchTemplate.value,
      normalizedTargetBranch.value,
      gate.acknowledge,
    )
    // coding-plan workflow 失败时把第一条 error 文案带进 toast，避免用户得开
    // DevTools 看 response 才知道为什么失败。
    const failSuffix = result.failedCount > 0
      ? (result.firstFailedError
          ? `；${result.failedCount} 个失败：${result.firstFailedError}`
          : `；${result.failedCount} 个失败`)
      : ''
    if (result.createdCount > 0)
      toastSuccess(`${result.createdCount} 个仓库已加入编码${failSuffix}`)
    else if (result.failedCount > 0)
      toastError(`未能加入编码${failSuffix}`)
    dialogOpen.value = false
    dialogSelectedIds.value = []
  }
  catch (e: any) {
    if (isDraftGateRejection(e))
      handleDraftGateRejection()
    else
      toastError(e?.message || '批量创建编码失败')
  }
  finally {
    chatStore.closeRepoMultiSelector()
  }
}

// ---------------------------------------------------------------------------
// ：导出到飞书三态按钮
// ---------------------------------------------------------------------------

const showExportDialog = ref(false)

// ：本卡导出成功后的就地兜底 URL。即便本卡不是当前 activeCodingPlan
// （多轮多方案时 store 只指向「最新」plan），@success 写本地态也能立即切换。
const localFeishuDocUrl = ref('')

/**
 * 已导出的飞书文档 URL。
 *
 * 解析优先级（ 修复 UAT test 3 / 6 串态/丢态）：
 *   1. 本地 localFeishuDocUrl（本卡刚导出成功的兜底，不依赖全局 activeCodingPlan）；
 *   2. codingPlanRuntime（已在入口过 plan_id 守卫，不串其它 plan 的已导出态）；
 *   3. 否则空串。
 */
const feishuDocUrl = computed<string>(
  () => localFeishuDocUrl.value || codingPlanRuntime.value?.feishu_doc_url || '',
)

/**
 * 方案正文（109-06 · SPINE-02 连带面）。
 *
 * 解析优先级（逐字沿用上方 feishuDocUrl 已建立的三级优先与注释纪律）：
 *   1. props.techPlan —— 这一级同时承载两个来源：投影响应本地态
 *      （OrchestratedPlanCard 把投影响应直接喂进 props）与**历史消息的 tool
 *      input 兜底**（ChatMessageBubble 的 codingPlanData.techPlan）。SPINE-02
 *      收窄 schema 后新消息的 tool input 已无 tech_plan，工具结果（109-REVIEW
 *      HI-02 起补齐）与投影响应接手承载正文；这一级不可删 —— 砍掉它会让
 *      SPINE-02 之前的历史会话方案卡集体变空；
 *   2. codingPlanRuntime（已在入口过 plan_id 守卫）；
 *   3. 否则空串（走空正文占位，而不是渲染一个空 prose 块）。
 *
 * 🔴 第 2 级的 plan_id 守卫不可省，理由见 codingPlanRuntime 的注释：多轮多方案
 * 会话里若不匹配就采用，会把**新方案的正文渲染到旧方案卡上** —— 不报错、不崩，
 * 只是内容串了，是最难查的一类缺陷。
 */
const resolvedTechPlan = computed<string>(
  () => props.techPlan || codingPlanRuntime.value?.tech_plan || '',
)

/** 影响文件（109-06）。与 resolvedTechPlan 同形的三级优先。 */
const resolvedAffectedFiles = computed<Array<{ file_path?: string, path?: string, change_type: string }>>(() => {
  if (props.affectedFiles.length > 0)
    return props.affectedFiles
  return codingPlanRuntime.value?.affected_files ?? []
})

/**
 * 方案来源标志（109-08 · RELY-01 界面侧）。
 *
 * 解析优先级与 resolvedTechPlan / resolvedAffectedFiles 同形：
 *   1. props.provenance —— 投影响应本地态 / 工具结果（109-REVIEW HI-02）；
 *   2. codingPlanRuntime（已在入口过 plan_id 守卫）；
 *   3. 否则 undefined（走保守分支 ⇒ 标注）。
 *
 * 🔴 plan_id 守卫在这一支尤其不可省：漏守卫会把**别的方案的来源标志渲染到本卡上**
 * —— 一份草稿因此被漏标，是安全性方向的失守（比正文串态更严重：正文串了看得出来，
 * 标志串了看不出来）。
 */
const resolvedProvenance = computed<string | null | undefined>(
  () => props.provenance || codingPlanRuntime.value?.provenance,
)

/**
 * 是否需要标注「未经代码调研」。
 *
 * 三条硬性纪律（UI-SPEC §B.1，与服务端 gate / 导出告示同口径）：
 *   1. 🔴 采**允许清单**而非拒绝清单：只有严格等于 'orchestrated' 才免标注，
 *      其余（'draft' / 未知取值 / null / undefined / ''）一律标注。写成
 *      `=== 'draft'` 会让后端任何新增枚举值默认放行。
 *   2. 🔴 **不靠文案硬编码判定**：只读 provenance 字段，绝不匹配 tech_plan 正文
 *      里是否含「草稿」「未经调研」等字样 —— 新增产出路径时正文格式不可控，
 *      文案判定必然漏标。
 *   3. 🔴 缺字段同样标注且渲染不得报错：实现是**纯字面比较**，不对 undefined
 *      做属性访问，历史 runtime / 历史消息渲染零报错。
 *
 * 失败代价不对称：把 undefined 当可信 = RELY-01 存在的意义被静默取消（一份没
 * 调研过的方案看起来可信）；当草稿 = 过渡窗口里多挂一条横幅。前者是安全缺陷，
 * 后者是观感瑕疵。故保守默认。
 */
const isUnresearched = computed(() => resolvedProvenance.value !== 'orchestrated')

// ---------------------------------------------------------------------------
// 同步点 2 收尾：blueprint/v1 识别
//
// 界面文案取 COPY 常量表（沿用本组件家族 OrchestratedPlanCard 的既定惯例，
// ⛔ 不接 vue-i18n）。状态中文来自 `~/config/blueprintArtifact`，那张表与
// `zh-CN.json` 之间有一条逐键相等的漂移守卫。
// ---------------------------------------------------------------------------

const BLUEPRINT_COPY = {
  badge: '技术蓝图',
  title: '本方案是一份结构化技术蓝图',
  description:
    '它按需求规格、仓库关联、实现概述等分段组织，需在蓝图查看器中逐段审阅、划线提问并完成终审。此处不展示正文。',
  cta: '打开技术蓝图',
} as const

/**
 * 是否为 blueprint/v1 投影。
 *
 * 🔴 **允许清单**（与 `isUnresearched` 同一条纪律的正向形态）：只有严格等于
 * `blueprint/v1` 才走蓝图分支；`undefined` / `''` / 将来的 `blueprint/v2` 一律按 v0
 * 渲染。失败代价方向正确：多渲一次旧形态只是观感，把未知结构当蓝图渲染则是把真正的
 * 方案正文藏起来。
 */
const isBlueprint = computed(() => isBlueprintSchemaVersion(props.schemaVersion))

/** 蓝图状态（拿不到回空串 ⇒ 落「旧版方案」档而不是未知档）。 */
const resolvedBlueprintStatus = computed(() => String(props.blueprintStatus ?? ''))

/** 状态徽标语气：等人处置（需要澄清 / 待人类审查）用 warning，其余中性。 */
const blueprintBadgeVariant = computed(() =>
  BLUEPRINT_ATTENTION_STATUSES.has(resolvedBlueprintStatus.value) ? 'warning' : 'secondary',
)

/** 查看器深链（拿不到 artifact id 就不渲染入口，⛔ 不给一个点不开的链接）。 */
const blueprintHref = computed(() =>
  props.blueprintArtifactId ? blueprintViewerPath(props.blueprintArtifactId) : '',
)

// ---------------------------------------------------------------------------
// 109-08（RELY-01）：草稿送编码的显式确认闸门
//
// 服务端 fail-closed gate（109-07）是唯一真防线，本弹层只是 UX：让用户在送编码
// **之前**就知道这份方案未经调研，而不是提交后吃一个 400。
// ---------------------------------------------------------------------------

/** 服务端拒绝的稳定机器码（109-07 契约）。🔴 绝不按 detail 文案分支。 */
const ERROR_CODE_DRAFT_REQUIRES_CONFIRM = 'draft_requires_explicit_confirm'
/** gate 拒绝时的提示文案 —— 前端常量，不回显后端 detail。 */
const DRAFT_GATE_REJECTED_MESSAGE = '草稿方案需显式确认后才能送编码'

const unresearchedDialogOpen = ref(false)
/** 风险确认 Checkbox 的稳定 id —— 供 label 的 for 关联，让读屏播报出确认文案。 */
const ackCheckboxId = useId()
/**
 * 必勾状态。组件本地 ref：**不写 store、不入 localStorage、不跨次记忆**，
 * 每次打开弹层重置为 false。
 */
const acknowledged = ref(false)
/** 当前等待用户决策的 resolve；结算后立即清空，避免悬挂。 */
let pendingAcknowledgeResolve: ((confirmed: boolean) => void) | null = null

function settleUnresearchedDialog(confirmed: boolean): void {
  unresearchedDialogOpen.value = false
  const resolve = pendingAcknowledgeResolve
  pendingAcknowledgeResolve = null
  resolve?.(confirmed)
}

function openUnresearchedDialog(): Promise<boolean> {
  // 上一次未结算的等待按「取消」结算，防止 promise 悬挂
  pendingAcknowledgeResolve?.(false)
  pendingAcknowledgeResolve = null
  // 🔴 每次打开重置勾选：确认不跨次记忆
  acknowledged.value = false
  unresearchedDialogOpen.value = true
  return new Promise<boolean>((resolve) => {
    pendingAcknowledgeResolve = resolve
  })
}

function handleUnresearchedCancel(): void {
  settleUnresearchedDialog(false)
}

function handleUnresearchedConfirm(): void {
  // 双保险：按钮已 disabled，这里再校一次，确保 true 只可能来自用户勾选
  if (!acknowledged.value)
    return
  settleUnresearchedDialog(true)
}

function onUnresearchedDialogOpenChange(open: boolean): void {
  unresearchedDialogOpen.value = open
  if (open)
    return
  // 关闭可能来自 Esc / 遮罩 / 取消 / 确认按钮（后者会连带关闭）。用一次微任务让
  // 同一次点击里的显式确认先结算，避免内置关闭把用户的确认吞成取消。
  void Promise.resolve().then(() => {
    if (pendingAcknowledgeResolve)
      settleUnresearchedDialog(false)
  })
}

/**
 * 送编码前的确认闸门。三条路径（创建态确认 / 追加态确认 / 单仓重试）共用。
 *
 * 返回值刻意是三态而非裸布尔：`acknowledge` 只在**用户勾选并确认**的分支上出现，
 * 且只可能是字面 `true`。编排方案走早退分支 ⇒ 弹层不出现、字段不发送。
 *
 * 🔴 不可协商的不变量：`acknowledge_unresearched: true` 只能由用户勾选产生。
 * 本函数是它在前端的**唯一**产生点 —— 不缓存、不记忆、不因「刚才确认过」而复用。
 */
async function ensureUnresearchedAcknowledged(): Promise<{ proceed: boolean, acknowledge?: true }> {
  if (isUnresearched.value === false)
    return { proceed: true }
  const confirmed = await openUnresearchedDialog()
  return confirmed ? { proceed: true, acknowledge: true } : { proceed: false }
}

/**
 * 是否为服务端草稿 gate 的拒绝。
 *
 * 🔴 按响应体 `code` 字段判定（ApiError.body），**绝不匹配 detail 文案** ——
 * 与「标注不靠文案硬编码」同一条纪律：一次后端文案微调就会让文案匹配静默失效。
 */
function isDraftGateRejection(err: unknown): boolean {
  const body = (err as { body?: unknown } | null | undefined)?.body
  if (!body || typeof body !== 'object')
    return false
  return (body as { code?: unknown }).code === ERROR_CODE_DRAFT_REQUIRES_CONFIRM
}

/**
 * gate 拒绝的兜底呈现：前端常量 toast，不重开弹层。
 *
 * 只有「服务端判定为草稿、前端判定为编排」这种不一致才会走到这里，此时弹层本就
 * 不会在提交前出现。重开弹层会得到一个无人 await 的 promise —— 用户勾选确认后
 * 什么都不会发生，比不弹更糟。让用户从原入口重来，行为自洽。
 */
function handleDraftGateRejection(): void {
  toastError(DRAFT_GATE_REJECTED_MESSAGE)
  // 不自动补 ack、不静默重放请求：ack 只能由用户在正规弹层里勾选产生。
}

function onExportSuccess(
  result: ExportToFeishuResponse | ExportCodingPlanToFeishuResponse,
) {
  if ('doc_url' in result)
    localFeishuDocUrl.value = result.doc_url
}

function triggerExport() {
  if (!props.codingPlanId)
    return
  showExportDialog.value = true
}

function openFeishu() {
  if (!feishuDocUrl.value)
    return
  window.open(feishuDocUrl.value, '_blank', 'noopener,noreferrer')
}

async function handleSessionRowRetry(rowSessionId: string) {
  const session = sessions.value.find(s => s.session_id === rowSessionId)
  if (!session || !props.codingPlanId)
    return
  // 109-08：重试同样**创建** session ⇒ 服务端 gate 会一致地拒绝。若前端因
  // 「用户之前已确认过」而自行补 true，等于前端替用户签名 ⇒ 重试也走弹层。
  const gate = await ensureUnresearchedAcknowledged()
  if (!gate.proceed)
    return
  try {
    // 🔴 不把 undefined 当第三参显式传入：让「编排方案不发送该字段」在调用点
    // 也是结构性的，而不是依赖下游把 undefined 过滤掉。
    const result = gate.acknowledge === true
      ? await chatStore.retrySingleRepository(props.codingPlanId, session.repository_id, true)
      : await chatStore.retrySingleRepository(props.codingPlanId, session.repository_id)
    if (result.createdCount > 0)
      toastSuccess('已重新发起编码')
    else
      toastError('重试失败')
  }
  catch (e: any) {
    if (isDraftGateRejection(e))
      handleDraftGateRejection()
    else
      toastError(e?.message || '重试失败')
  }
}

// ---------------------------------------------------------------------------
// 折叠状态：默认 draft 展开、其它状态折叠（用户可点击切换）
// ---------------------------------------------------------------------------
function computedInitialCollapsed(): boolean {
  if (props.defaultCollapsed !== undefined)
    return props.defaultCollapsed
  return props.status !== 'draft'
}
const collapsed = ref<boolean>(computedInitialCollapsed())
function toggleCollapsed() {
  collapsed.value = !collapsed.value
}

// ---------------------------------------------------------------------------
// affected_files schema 软回退（兼容 backend 还没归一化的旧 path）
// ---------------------------------------------------------------------------
function filePath(file: { file_path?: string, path?: string }): string {
  return file.file_path ?? file.path ?? ''
}

// ---------------------------------------------------------------------------
// Markdown 渲染
// ---------------------------------------------------------------------------
const renderedPlan = ref('')
const mdReady = ref(false)
const mdInstance = ref<MarkdownIt | null>(null)

onMounted(async () => {
  mdInstance.value = await getMarkdownRenderer()
  mdReady.value = true
})

watchEffect(() => {
  if (!mdInstance.value)
    return
  // 正文为空时清空渲染结果，避免上一份正文残留在 DOM 上
  renderedPlan.value = resolvedTechPlan.value
    ? mdInstance.value.render(resolvedTechPlan.value)
    : ''
})

// ---------------------------------------------------------------------------
// 分支名编辑（沿用 CodingPlanCard 逻辑；D-06 / D-07）
// ---------------------------------------------------------------------------
const { parseBranchName, buildBranchName, validateShortDesc } = useBranchValidation()
const parsed = computed(() => props.branchName ? parseBranchName(props.branchName) : null)
const branchType = ref(parsed.value?.type || 'feat')
const branchDate = computed(() => parsed.value?.date || '')
const shortDesc = ref(parsed.value?.shortDesc || '')

const validation = computed(() => validateShortDesc(shortDesc.value))
const previewBranchName = computed(() =>
  branchDate.value ? buildBranchName(branchType.value, branchDate.value, shortDesc.value) : '',
)

watch(() => props.branchName, (newVal) => {
  if (newVal) {
    const p = parseBranchName(newVal)
    if (p) {
      branchType.value = p.type
      shortDesc.value = p.shortDesc
    }
  }
}, { immediate: true })

/**
 * legacy 单仓确认（仅 codingPlanId 缺失时可达）。
 *
 * 109-08 边界：**不加**草稿确认闸门。理由：此时前端拿不到 provenance（无 plan
 * 关联）、服务端也无 plan_id 可据以判定；且它确认的是**已存在**的 session，而
 * 服务端 gate 的落点是 session **创建**。若后续该路径仍有真实流量，需先补 plan
 * 关联再谈 gate（UI-SPEC §Unresolved #2）。
 */
function handleConfirm() {
  const editedBranch = previewBranchName.value || undefined
  emit('confirm', props.planId, props.sessionId, editedBranch, normalizedTargetBranch.value)
}

function handleRetry() {
  emit('retry', props.planId, props.sessionId)
}

// ---------------------------------------------------------------------------
// ：completed/failed 状态卡片整体染色
// ---------------------------------------------------------------------------
const cardClass = computed(() => {
  if (props.status === 'completed')
    return 'ring-1 ring-emerald-500/30 border-emerald-500/30'
  if (props.status === 'failed')
    return 'ring-1 ring-destructive/30 border-destructive/30'
  return ''
})

// ---------------------------------------------------------------------------
// 状态徽章
// ---------------------------------------------------------------------------
const badgeClass = computed(() => {
  if (props.status === 'confirmed' || props.status === 'running' || props.status === 'awaiting_confirmation') {
    return 'text-primary border-primary/30 bg-primary/5'
  }
  if (props.status === 'completed') {
    return 'text-emerald-500 border-emerald-500/30 bg-emerald-500/5'
  }
  return ''
})

const badgeText = computed(() => {
  if (props.status === 'confirmed' || props.status === 'running')
    return '已确认'
  if (props.status === 'awaiting_confirmation')
    return '确认中'
  if (props.status === 'completed')
    return '已完成'
  if (props.status === 'failed')
    return '失败'
  return ''
})
</script>

<template>
  <div class="card mt-2 animate-fade-in" :class="cardClass">
    <!-- 头部（可点击折叠） -->
    <button
      class="px-4 py-3 border-b border-border/50 flex items-center gap-2 w-full text-left"
      type="button"
      @click="toggleCollapsed"
    >
      <span class="icon-[lucide--file-code] text-primary" />
      <span class="text-sm font-semibold">{{ title || '编码方案' }}</span>
      <!--
        同步点 2 收尾：蓝图形态 + 11 态状态两枚徽标。
        🔴 插在标题之后、既有两枚徽标之前 —— 那两枚与 chevron 之间的 `ml-auto` 接力链
        逐条依赖彼此的渲染条件，插在链中间会让 v0 的排版随之改变。
      -->
      <template v-if="isBlueprint">
        <Badge variant="outline" class="ml-1" data-test="blueprint-badge">
          {{ BLUEPRINT_COPY.badge }}
        </Badge>
        <Badge :variant="blueprintBadgeVariant" class="ml-1" data-test="blueprint-status-badge">
          {{ blueprintStatusText(resolvedBlueprintStatus) }}
        </Badge>
      </template>
      <!--
        109-08：草稿徽标头部常驻（展开与折叠态都渲染），让「未经调研」这条事实
        不被一次折叠操作藏起来。纯 variant、不加 :class 颜色（DESIGN.md Badge 禁令）。
      -->
      <Badge v-if="isUnresearched" variant="warning" class="ml-auto">
        未经调研
      </Badge>
      <Badge
        v-if="status !== 'draft'"
        :variant="status === 'failed' ? 'destructive' : 'outline'"
        :class="[badgeClass, isUnresearched ? 'ml-1' : 'ml-auto']"
      >
        {{ badgeText }}
      </Badge>
      <span
        class="icon-[lucide--chevron-right] text-xs transition-transform"
        :class="[
          !isUnresearched && status === 'draft' ? 'ml-auto' : 'ml-1',
          { 'rotate-90': !collapsed },
        ]"
      />
    </button>

    <!-- 展开内容 -->
    <template v-if="!collapsed">
      <!-- Markdown + affected_files -->
      <div class="p-4 space-y-3">
        <!--
          109-08：草稿告警横幅。位置在方案正文**之前** —— 用户在读到任何方案内容
          前先看到「这份东西未经调研」。DOM 形状沿用 CommitConfirmCard 的告警条。
          role="alert" 但**不加** aria-live：横幅随卡片首次渲染出现（非动态插入），
          aria-live 在此不产生播报价值反而可能重复朗读。
        -->
        <div
          v-if="isUnresearched"
          class="p-3 rounded-lg border border-amber-500/30 bg-amber-500/5"
          role="alert"
          data-test="unresearched-banner"
        >
          <div class="flex items-start gap-2">
            <span class="icon-[lucide--alert-triangle] text-amber-500 shrink-0 mt-0.5" />
            <div class="space-y-1 min-w-0">
              <p class="text-sm font-medium text-foreground">
                本方案未经代码调研
              </p>
              <p class="text-xs text-muted-foreground">
                由对话直接生成，未经仓库路由、代码召回与并行调研，文件清单与实现步骤可能不准确。
              </p>
            </div>
          </div>
        </div>
        <!-- ：markdown 异步初始化期间的 skeleton 占位 -->
        <div v-if="!mdReady" class="space-y-2 animate-pulse" data-test="md-skeleton">
          <div class="h-4 rounded bg-muted/60 w-3/4" />
          <div class="h-4 rounded bg-muted/60 w-1/2" />
          <div class="h-4 rounded bg-muted/60 w-2/3" />
        </div>
        <!--
          同步点 2 收尾：蓝图**不在此渲染正文**。
          🔴 这一档必须排在「正文为空 ⇒ 占位」之前：blueprint/v1 经 v0 映射器渲出来的
          `tech_plan` 是一份结构合法而内容为空的壳，落到那一档就成了「（暂无方案正文）」
          —— 把「形态不同」讲成「方案没了」，正是本次要消除的静默降级。
        -->
        <div
          v-else-if="isBlueprint"
          class="p-3 rounded-lg border border-primary/30 bg-primary/5 space-y-2"
          role="status"
          data-test="blueprint-notice"
        >
          <div class="flex items-start gap-2">
            <span class="icon-[lucide--file-text] text-primary shrink-0 mt-0.5" />
            <div class="space-y-1 min-w-0">
              <p class="text-sm font-medium text-foreground">
                {{ BLUEPRINT_COPY.title }}
              </p>
              <p class="text-xs text-muted-foreground">
                {{ BLUEPRINT_COPY.description }}
              </p>
            </div>
          </div>
          <RouterLink
            v-if="blueprintHref"
            :to="blueprintHref"
            class="text-xs text-primary underline-offset-4 hover:underline inline-flex items-center gap-1"
            data-test="blueprint-link"
          >
            <span class="icon-[lucide--external-link]" />
            {{ BLUEPRINT_COPY.cta }}
          </RouterLink>
        </div>
        <!-- 109-06：正文为空时渲染一行占位，而不是一个空 prose 块 -->
        <p v-else-if="!resolvedTechPlan" class="text-xs text-muted-foreground">
          （暂无方案正文）
        </p>
        <div v-else class="prose prose-sm max-w-none" v-html="renderedPlan" />
        <div v-if="visibleTargetRepositories.length > 0" class="space-y-1">
          <p class="text-xs text-muted-foreground font-medium">
            目标仓库
          </p>
          <div class="flex flex-wrap gap-1.5">
            <Badge
              v-for="repo in visibleTargetRepositories"
              :key="repo.id"
              variant="outline"
              class="font-mono text-[11px]"
            >
              {{ repo.name }}
            </Badge>
          </div>
        </div>
        <div v-if="resolvedAffectedFiles.length > 0" class="space-y-1">
          <p class="text-xs text-muted-foreground font-medium">
            影响文件
          </p>
          <div
            v-for="(file, i) in resolvedAffectedFiles"
            :key="i"
            class="text-xs text-muted-foreground flex items-center gap-1"
          >
            <span class="icon-[lucide--file] text-[10px]" />
            <code class="text-xs">{{ filePath(file) }}</code>
            <span class="text-muted-foreground/60">({{ file.change_type }})</span>
          </div>
        </div>
      </div>

      <!-- ：导出到飞书三态按钮 -->
      <div v-if="codingPlanId" class="px-4 pb-3 pt-1 flex items-center gap-2">
        <Button
          v-if="!feishuDocUrl"
          variant="outline"
          size="sm"
          class="text-xs"
          @click="triggerExport"
        >
          <span class="icon-[lucide--file-up] mr-1" />
          导出到飞书
        </Button>
        <template v-else>
          <Button
            variant="outline"
            size="sm"
            class="text-xs"
            @click="openFeishu"
          >
            <span class="icon-[lucide--external-link] mr-1" />
            在飞书打开
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label="重新导出"
            class="h-7 w-7"
            @click="triggerExport"
          >
            <span class="icon-[lucide--refresh-cw] text-sm" />
          </Button>
        </template>
      </div>

      <!-- / ：已加入的仓库 sessions 列表 -->
      <div v-if="hasSessions" class="px-4 pb-3 pt-2 space-y-1">
        <div class="flex items-center justify-between">
          <p class="text-xs text-muted-foreground font-medium">
            目标仓库（{{ sessions.length }}）
          </p>
          <Button
            v-if="codingPlanId"
            variant="ghost"
            size="sm"
            class="text-xs"
            @click="openAppendDialog"
          >
            <span class="icon-[lucide--plus] mr-1" />
            对新仓库编码
          </Button>
        </div>
        <div class="divide-y divide-border/30">
          <CodingSessionStatusRow
            v-for="s in sessions"
            :key="s.session_id"
            :session="s"
            :repo-git-url="repositoryGitUrls[s.repository_id] ?? ''"
            @retry="handleSessionRowRetry"
          />
        </div>
      </div>

      <!-- ：创建态内嵌 selector（替代旧的「开始编码」单仓按钮） -->
      <div v-if="showInlineSelector" class="px-4 pb-4 pt-2">
        <div class="space-y-2 mb-3">
          <p class="text-xs text-muted-foreground font-medium">
            功能分支 / 分支模板
          </p>
          <Input
            v-model="branchTemplate"
            data-test="branch-template-input"
            class="h-9 font-mono text-sm"
            placeholder="例如 fix.gift-empty-list 或 fix.${repo}"
          />
          <p class="text-xs text-muted-foreground/80">
            单仓时填写完整分支名；多仓时可使用 <code>${repo}</code> 作为仓库名占位符。
          </p>
        </div>
        <div class="space-y-2 mb-3">
          <p class="text-xs text-muted-foreground font-medium">
            目标分支（PR 合并目标）
          </p>
          <Input
            v-model="targetBranch"
            data-test="target-branch-input"
            class="h-9 font-mono text-sm"
            placeholder="develop"
          />
          <p class="text-xs text-muted-foreground/80">
            PR 将合并到该分支，统一应用到本次所有选中仓库，默认 <code>develop</code>。
          </p>
        </div>
        <p class="text-xs text-muted-foreground font-medium mb-2">
          选择目标仓库
        </p>
        <RepoMultiSelector
          :repositories="availableRepositories"
          :model-value="dialogSelectedIds"
          :disabled-ids="existingActiveRepoIds"
          :recommended-ids="recommendedRepositoryIds"
          :submitting="repoMultiSelectorState.submitting"
          @update:model-value="(v: string[]) => dialogSelectedIds = v"
          @confirm="handleMultiConfirm"
        />
      </div>

      <!-- draft：分支名编辑 + 开始编码（codingPlanId 未提供时的向后兼容路径） -->
      <div v-if="!codingPlanId && status === 'draft'" class="px-4 pb-4">
        <div v-if="branchName" class="space-y-3 mb-3">
          <p class="text-xs text-muted-foreground font-medium">
            功能分支
          </p>
          <div class="flex items-end gap-2">
            <Select v-model="branchType">
              <SelectTrigger class="w-24 h-9">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="feat">
                  feat
                </SelectItem>
                <SelectItem value="fix">
                  fix
                </SelectItem>
                <SelectItem value="chore">
                  chore
                </SelectItem>
                <SelectItem value="test">
                  test
                </SelectItem>
              </SelectContent>
            </Select>
            <span class="text-xs font-mono text-muted-foreground shrink-0 pb-2">/{{ branchDate }}.</span>
            <Input
              v-model="shortDesc"
              class="flex-1 h-9 font-mono text-sm"
              placeholder="简短描述（中文优先）"
              :disabled="isConfirming"
            />
          </div>
          <p v-if="shortDesc && !validation.valid" class="text-xs text-destructive mt-1">
            {{ validation.error }}
          </p>
          <div v-if="previewBranchName" class="text-xs font-mono text-foreground bg-muted/50 rounded px-2 py-1">
            分支名预览: {{ previewBranchName }}
          </div>
        </div>
        <div class="space-y-2 mb-3">
          <p class="text-xs text-muted-foreground font-medium">
            目标分支（PR 合并目标）
          </p>
          <Input
            v-model="targetBranch"
            data-test="target-branch-input-single"
            class="h-9 font-mono text-sm"
            placeholder="develop"
            :disabled="isConfirming"
          />
          <p class="text-xs text-muted-foreground/80">
            PR 将合并到该分支，默认 <code>develop</code>。
          </p>
        </div>
        <Button
          class="w-full"
          :disabled="isConfirming || (branchName && (!validation.valid || !shortDesc.trim()) ? true : false)"
          @click="handleConfirm"
        >
          <span v-if="isConfirming" class="icon-[lucide--loader-2] animate-spin mr-2" />
          开始编码
        </Button>
      </div>

      <!-- confirmed / running：等待 / 编码中提示 -->
      <div v-else-if="status === 'confirmed' || status === 'running'" class="px-4 pb-3">
        <div class="text-xs text-muted-foreground flex items-center gap-1">
          <span class="icon-[lucide--loader-2] animate-spin text-primary" />
          {{ status === 'running' ? '正在编码中…' : '已确认，正在启动编码…' }}
        </div>
      </div>

      <!-- awaiting_confirmation：等待用户确认下一步 -->
      <div v-else-if="status === 'awaiting_confirmation'" class="px-4 pb-3">
        <div class="text-xs text-muted-foreground flex items-center gap-1">
          <span class="icon-[lucide--pause-circle] text-primary" />
          等待用户确认下一步
        </div>
      </div>

      <!-- completed：绿框 + PR/branch 链接（缺失时显示占位） -->
      <div v-else-if="status === 'completed'" class="px-4 pb-4 space-y-2">
        <div class="text-xs text-emerald-600 dark:text-emerald-400 flex items-center gap-1">
          <span class="icon-[lucide--check-circle-2]" />
          编码完成
        </div>
        <div v-if="prUrl" class="text-xs">
          <a
            :href="prUrl"
            target="_blank"
            rel="noopener noreferrer"
            class="text-primary underline-offset-4 hover:underline inline-flex items-center gap-1"
          >
            <span class="icon-[lucide--git-pull-request]" />
            查看 PR
          </a>
        </div>
        <div v-if="branchUrl" class="text-xs">
          <a
            :href="branchUrl"
            target="_blank"
            rel="noopener noreferrer"
            class="text-muted-foreground hover:text-foreground inline-flex items-center gap-1"
          >
            <span class="icon-[lucide--git-branch]" />
            查看分支
          </a>
        </div>
        <div v-if="!prUrl && !branchUrl" class="text-xs text-muted-foreground/80">
          PR 链接将由 multi-confirm 流程回填
        </div>
      </div>

      <!-- failed：红框 + 错误原因 + 重试按钮 -->
      <div v-else-if="status === 'failed'" class="px-4 pb-4 space-y-2">
        <div class="text-xs text-destructive flex items-start gap-1">
          <span class="icon-[lucide--alert-triangle] mt-0.5 shrink-0" />
          <span>{{ errorMessage || '编码失败，未提供错误信息' }}</span>
        </div>
        <Button
          variant="outline"
          size="sm"
          class="h-8"
          @click="handleRetry"
        >
          <span class="icon-[lucide--refresh-cw] mr-1.5" />
          重试
        </Button>
      </div>
    </template>

    <!-- 折叠态：一行摘要 -->
    <template v-else>
      <!-- 蓝图折叠态同理：摘要取蓝图形态说明，⛔ 不取那份空壳 markdown 的首行 -->
      <div
        v-if="isBlueprint"
        class="px-4 py-2 text-xs text-muted-foreground truncate"
        data-test="blueprint-collapsed-summary"
      >
        {{ BLUEPRINT_COPY.title }}（{{ blueprintStatusText(resolvedBlueprintStatus) }}）
      </div>
      <div v-else class="px-4 py-2 text-xs text-muted-foreground truncate">
        {{ resolvedTechPlan.split('\n')[0] || '（无方案文本）' }}
      </div>
    </template>

    <!-- ：追加态 Dialog -->
    <Dialog v-model:open="dialogOpen">
      <DialogContent class="max-w-2xl">
        <DialogHeader>
          <DialogTitle>对新仓库追加编码</DialogTitle>
          <DialogDescription>
            选择尚未加入的仓库；已有进行中编码的仓库将被禁用。
          </DialogDescription>
        </DialogHeader>
        <div class="space-y-2 mb-3">
          <p class="text-xs text-muted-foreground font-medium">
            功能分支 / 分支模板
          </p>
          <Input
            v-model="branchTemplate"
            data-test="branch-template-input"
            class="h-9 font-mono text-sm"
            placeholder="例如 fix.gift-empty-list 或 fix.${repo}"
          />
          <p class="text-xs text-muted-foreground/80">
            单仓时填写完整分支名；多仓时可使用 <code>${repo}</code> 作为仓库名占位符。
          </p>
        </div>
        <div class="space-y-2 mb-3">
          <p class="text-xs text-muted-foreground font-medium">
            目标分支（PR 合并目标）
          </p>
          <Input
            v-model="targetBranch"
            data-test="target-branch-input"
            class="h-9 font-mono text-sm"
            placeholder="develop"
          />
          <p class="text-xs text-muted-foreground/80">
            PR 将合并到该分支，统一应用到本次所有选中仓库，默认 <code>develop</code>。
          </p>
        </div>
        <RepoMultiSelector
          :repositories="availableRepositories"
          :model-value="dialogSelectedIds"
          :disabled-ids="existingActiveRepoIds"
          :recommended-ids="recommendedRepositoryIds"
          :submitting="repoMultiSelectorState.submitting"
          @update:model-value="(v: string[]) => dialogSelectedIds = v"
          @confirm="handleMultiConfirm"
        />
      </DialogContent>
    </Dialog>

    <!--
      109-08（RELY-01）：草稿送编码的阻断式确认弹层。
      用 AlertDialog 而非普通 Dialog（需要焦点陷阱与显式取消）；不复用
      GlobalConfirmDialog / useConfirmDialog —— 其 ConfirmOptions 无法承载必勾
      Checkbox，为它加字段会改动一个被 20+ 处复用的全局组件。
    -->
    <AlertDialog
      :open="unresearchedDialogOpen"
      @update:open="onUnresearchedDialogOpenChange"
    >
      <AlertDialogContent data-test="unresearched-dialog">
        <AlertDialogHeader>
          <AlertDialogTitle>该方案未经代码调研</AlertDialogTitle>
          <AlertDialogDescription>
            它由对话直接生成，未经仓库路由、代码召回与并行调研。继续送编码可能产出偏离预期的改动。建议先经技术方案编排产出正式方案。
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div class="p-3 rounded-lg border border-amber-500/30 bg-amber-500/5">
          <!--
            label 经 for 关联到 Checkbox 的 id：点文字能勾选，同时读屏能播报出
            确认文案。仅用 label 包裹时 reka-ui 的 CheckboxRoot 推导不出可访问名，
            读屏只念「复选框 未勾选」—— 而这是 RELY-01 唯一的人工签名点。
          -->
          <label :for="ackCheckboxId" class="flex items-start gap-2 text-sm">
            <Checkbox
              :id="ackCheckboxId"
              v-model="acknowledged"
              class="mt-0.5 shrink-0"
              data-test="ack-checkbox"
            />
            <span>我已了解风险，仍要用该草稿送编码</span>
          </label>
        </div>
        <AlertDialogFooter>
          <!-- 显式结算「取消」，不只依赖内置关闭事件（意图更明确，也让取消可测） -->
          <AlertDialogCancel data-test="ack-cancel" @click="handleUnresearchedCancel">
            取消
          </AlertDialogCancel>
          <!-- 不用 destructive 配色：送编码不销毁数据、不可逆性有限（产出 PR 可关闭） -->
          <AlertDialogAction
            data-test="ack-confirm"
            :disabled="!acknowledged"
            :aria-disabled="!acknowledged"
            @click="handleUnresearchedConfirm"
          >
            仍要送编码
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>

    <!-- ：导出技术方案到飞书 -->
    <ExportConfirmDialog
      v-if="codingPlanId"
      :open="showExportDialog"
      :default-title="title || codingPlanRuntime?.title || '编码方案'"
      mode="coding_plan"
      :coding-plan-id="codingPlanId"
      @success="onExportSuccess"
      @update:open="(v: boolean) => showExportDialog = v"
    />
  </div>
</template>
