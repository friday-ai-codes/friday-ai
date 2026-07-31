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
 */
import { storeToRefs } from 'pinia'
import { computed, onMounted, ref, watch, watchEffect } from 'vue'
import CodingSessionStatusRow from '~/components/chat/CodingSessionStatusRow.vue'
import ExportConfirmDialog from '~/components/chat/ExportConfirmDialog.vue'
import RepoMultiSelector from '~/components/chat/RepoMultiSelector.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
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

const codingPlanRuntime = computed<CodingPlanRuntime | null>(
  () => activeCodingPlan.value,
)
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
  try {
    chatStore.openRepoMultiSelector(props.codingPlanId, repoIds)
    const result = await chatStore.submitRepoMultiSelector(
      repoIds,
      normalizedBranchTemplate.value,
      normalizedTargetBranch.value,
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
 *   2. 仅当 store 的 activeCodingPlan.plan_id === 本卡 codingPlanId 时采用其值；
 *   3. 否则空串（不串其它 plan 的已导出态）。
 */
const feishuDocUrl = computed<string>(() => {
  if (localFeishuDocUrl.value)
    return localFeishuDocUrl.value
  const runtime = codingPlanRuntime.value
  if (runtime && props.codingPlanId && runtime.plan_id === props.codingPlanId)
    return runtime.feishu_doc_url || ''
  return ''
})

/**
 * 方案正文（109-06 · SPINE-02 连带面）。
 *
 * 解析优先级（逐字沿用上方 feishuDocUrl 已建立的三级优先与注释纪律）：
 *   1. props.techPlan —— 这一级同时承载两个来源：投影响应本地态
 *      （OrchestratedPlanCard 把投影响应直接喂进 props）与**历史消息的 tool
 *      input 兜底**（ChatMessageBubble 的 codingPlanData.techPlan）。SPINE-02
 *      收窄 schema 后新消息的 tool input 已无 tech_plan，但这一级不可删 ——
 *      砍掉它会让 SPINE-02 之前的历史会话方案卡集体变空；
 *   2. 仅当 store 的 activeCodingPlan.plan_id === 本卡 codingPlanId 时采用其
 *      tech_plan；
 *   3. 否则空串（走空正文占位，而不是渲染一个空 prose 块）。
 *
 * 🔴 第 2 级的 plan_id 匹配守卫不可省：activeCodingPlan 只指向「对话内最近
 * CodingPlan」，多轮多方案会话里若不匹配就采用，会把**新方案的正文渲染到旧方案
 * 卡上** —— 不报错、不崩，只是内容串了，是最难查的一类缺陷。与 feishuDocUrl
 * 的「不串其它 plan 的已导出态」同一个坑、同一道守卫。
 */
const resolvedTechPlan = computed<string>(() => {
  if (props.techPlan)
    return props.techPlan
  const runtime = codingPlanRuntime.value
  if (runtime && props.codingPlanId && runtime.plan_id === props.codingPlanId)
    return runtime.tech_plan || ''
  return ''
})

/**
 * 影响文件（109-06）。与 resolvedTechPlan 同形的三级优先，
 * 第 2 级同样过 `runtime.plan_id === props.codingPlanId` 守卫（理由同上）。
 */
const resolvedAffectedFiles = computed<Array<{ file_path?: string, path?: string, change_type: string }>>(() => {
  if (props.affectedFiles.length > 0)
    return props.affectedFiles
  const runtime = codingPlanRuntime.value
  if (runtime && props.codingPlanId && runtime.plan_id === props.codingPlanId)
    return runtime.affected_files ?? []
  return []
})

/**
 * 方案来源标志（109-08 · RELY-01 界面侧）。
 *
 * 解析优先级与 resolvedTechPlan / resolvedAffectedFiles 同形：
 *   1. props.provenance —— 投影响应本地态；
 *   2. 仅当 store 的 activeCodingPlan.plan_id === 本卡 codingPlanId 时采用其
 *      provenance；
 *   3. 否则 undefined（走保守分支 ⇒ 标注）。
 *
 * 🔴 第 2 级的 plan_id 匹配守卫不可省：runtime.provenance 是 runtime.coding_plan
 * 的第三个消费点。漏守卫会把**别的方案的来源标志渲染到本卡上** —— 一份草稿因此
 * 被漏标，是安全性方向的失守（比正文串态更严重：正文串了看得出来，标志串了看不
 * 出来）。与 feishuDocUrl / resolvedTechPlan 同一个坑、同一道守卫。
 */
const resolvedProvenance = computed<string | null | undefined>(() => {
  if (props.provenance)
    return props.provenance
  const runtime = codingPlanRuntime.value
  if (runtime && props.codingPlanId && runtime.plan_id === props.codingPlanId)
    return runtime.provenance
  return undefined
})

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
  try {
    const result = await chatStore.retrySingleRepository(
      props.codingPlanId,
      session.repository_id,
    )
    if (result.createdCount > 0)
      toastSuccess('已重新发起编码')
    else
      toastError('重试失败')
  }
  catch (e: any) {
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
      <div class="px-4 py-2 text-xs text-muted-foreground truncate">
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
