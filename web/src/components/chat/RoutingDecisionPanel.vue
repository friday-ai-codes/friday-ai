<script setup lang="ts">
/**
 * / 07 / 08：路由决策可视化卡片。
 *
 * - 来源：RoutingDecisionData via useRoutingStore（trace_id 由 ChatMessageBubble
 *   通过 props 传入；store 内部维护双索引 + latest 指针）。
 * - 双向勾选：Checkbox v-model 反映 candidate.selected_by_user_final；
 *   debounce 300ms 触发 routingStore.applyManualOverride → POST /override/。
 * - 「基于这些仓库创建编码方案」按钮 emit `create-coding-plan-from-trace`
 *   事件给父组件 ChatMessageBubble，后者发一条 user message 让 LLM 主导
 *   create_coding_plan tool call（RELEV-08）。
 * - 优雅降级：store 无对应 trace → v-if 整个组件不渲染。
 *
 * 视觉：glassmorphism（DESIGN.md）+ shadcn-vue Card/Badge/Tooltip/Checkbox/Button +
 * Tailwind（禁内联样式）。
 */
import type { ManualOverrideRequestCandidate, RoutingCandidate, RoutingGroup, RoutingLevel } from '~/types/routing'
import { useDebounceFn } from '@vueuse/core'
import { computed, ref, watch } from 'vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Card } from '~/components/ui/card'
import { Checkbox } from '~/components/ui/checkbox'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '~/components/ui/collapsible'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/tooltip'
import { useRoutingStore } from '~/stores/routing'

const props = defineProps<{
  traceId: string
  conversationId: string
  messageId?: string
}>()

const emit = defineEmits<{
  createCodingPlanFromTrace: [traceId: string]
  manualSelectRequested: [traceId: string]
}>()

const routingStore = useRoutingStore()

/**
 * 状态来源是 store 中**最新** trace（manual_override 后实时反映），而非 props 初始 trace_id。
 */
const effectiveTraceId = computed(() => {
  return routingStore.getLatestTraceId(props.conversationId) ?? props.traceId
})

const trace = computed(() => routingStore.getTrace(effectiveTraceId.value))

const allCandidates = computed<RoutingCandidate[]>(() => trace.value?.candidates ?? [])

const levelCounts = computed(() => {
  const counts: Record<RoutingLevel, number> = { high: 0, medium: 0, low: 0 }
  for (const c of allCandidates.value)
    counts[c.level]++
  return counts
})

/** 组标题文案（硬编码中文，沿用 SIGNAL_LABELS 惯例，不接 vue-i18n）。 */
const GROUP_LABELS: Record<RoutingGroup, string> = {
  in_project: '本项目关联仓',
  global: '全局候选',
}

// 跨组说明句与置顶提示句一律取这两个前端常量：后端的自由文本留痕字段不进
// DOM，避免把上游文本变成渲染面（T-107-06）。文案全部走 {{ }} 插值，组件内
// 不使用任何原始 HTML 注入指令。
const CROSS_GROUP_SENTENCE = '未关联当前平台，可能涉及跨组协作'
const PROMOTION_SENTENCE = '更匹配的仓不在本项目关联范围内'

/** 每组默认可见条数（叠加 pin-in 规则后可超出）。 */
const VISIBLE_PER_GROUP = 3

interface RoutingBlock {
  group: RoutingGroup
  total: number
  visible: RoutingCandidate[]
  overflow: RoutingCandidate[]
}

/**
 * 归属组兜底：后端契约是「缺省（**空串**）由前端视为 global」，所以必须用 `||` 而非
 * `??` —— `'' ?? 'global'` 仍是 `''`，该候选在 in_project 与 global 两个分区的
 * filter 上都不匹配，于是两个分区都不渲染它，而表头计数仍把它算进总数（「说有 5 个，
 * 只列出 4 个」）。
 */
function groupOf(c: RoutingCandidate): RoutingGroup {
  return c.group || 'global'
}

/** 排序键：score_ranked 是后端凸组合排序分，缺失 / null 时回退 score。 */
function rankKey(c: RoutingCandidate): number {
  return c.score_ranked ?? c.score
}

function byRankDesc(a: RoutingCandidate, b: RoutingCandidate): number {
  const delta = rankKey(b) - rankKey(a)
  if (delta !== 0)
    return delta
  // 同分 tie-break 与后端同口径（repository_id 升序），保证渲染顺序稳定
  return a.repository_id.localeCompare(b.repository_id)
}

/**
 * 分组呈现启用判定：**唯一依据是后端 `block_order`**——长度 2 即启用（后端契约：
 * 有项目上下文时恒为长度 2，即使某组为空）。长度 1 = 无项目上下文 → 平铺，此时标
 * 「跨组」反而误导；缺失（历史 trace / legacy 路径）同样平铺，保持今日渲染。
 *
 * 刻意**不**按候选内容兜底：曾用 `some(c => c.group === 'in_project')`，而它恰在最
 * 需要分组的场景失效——正确仓在跨组、本项目组为空时没有任何候选是 in_project，分组
 * 被判为关闭，「更匹配的仓不在本项目关联范围内」这句最有信息量的提示反而不出现。
 * 判据必须与候选内容无关。
 */
const groupingEnabled = computed(() => trace.value?.block_order?.length === 2)

/** 区顺序权威来自后端；前端不重排区。 */
const blockOrder = computed<RoutingGroup[]>(() => {
  const order = trace.value?.block_order
  return order && order.length === 2 ? [...order] : ['in_project', 'global']
})

/**
 * 分区结构：区顺序 = block_order，区内按 rankKey 降序，空组不产出。
 *
 * 这里**不做**全局重排——曾经的实现按 score 把全部候选重排一次，会覆盖后端
 * 的分区顺序与 block 置顶决策（107-RESEARCH Pitfall 4）。
 */
const groupedBlocks = computed<RoutingBlock[]>(() => {
  const sorted = [...allCandidates.value].sort(byRankDesc)
  if (!groupingEnabled.value) {
    // 平铺分支（历史 trace / 无项目上下文）：单块、不截断、无组标题与标注，
    // 与今日渲染一致
    return [{ group: 'global', total: sorted.length, visible: sorted, overflow: [] }]
  }
  return blockOrder.value
    .map((group) => {
      const members = sorted.filter(c => groupOf(c) === group)
      const visible: RoutingCandidate[] = []
      const overflow: RoutingCandidate[] = []
      members.forEach((c, index) => {
        // pin-in：已选候选无论排名一律可见——候选行承载 Checkbox，被折叠的
        // 已选候选无法取消勾选，用户还会看到「勾了的仓不见了」
        if (index < VISIBLE_PER_GROUP || c.selected_by_ai || c.selected_by_user_final)
          visible.push(c)
        else
          overflow.push(c)
      })
      return { group, total: members.length, visible, overflow }
    })
    .filter(block => block.total > 0)
})

function isCrossGroup(c: RoutingCandidate): boolean {
  return groupingEnabled.value && groupOf(c) === 'global'
}

/** 迟滞置顶（后端 delta 判定的结果，前端不算 delta）时给出因果解释。 */
const showPromotionNotice = computed(
  () => groupingEnabled.value && blockOrder.value[0] === 'global',
)

/**
 * 全局组默认折叠判定（纯呈现派生）：本项目在前 + 本项目首位高置信 → 折叠。
 */
const defaultGlobalOpen = computed(() => {
  if (!groupingEnabled.value || blockOrder.value[0] !== 'in_project')
    return true
  const inProject = groupedBlocks.value.find(b => b.group === 'in_project')
  return inProject?.visible[0]?.level !== 'high'
})

/** null = 跟随默认态；用户点过后本地态优先（trace 变化时置回 null 重算）。 */
const globalGroupOpenOverride = ref<boolean | null>(null)
const globalGroupOpen = computed(
  () => globalGroupOpenOverride.value ?? defaultGlobalOpen.value,
)

function toggleGlobalGroup() {
  globalGroupOpenOverride.value = !globalGroupOpen.value
}

function isBlockOpen(block: RoutingBlock): boolean {
  if (!groupingEnabled.value || block.group !== 'global')
    return true
  return globalGroupOpen.value
}

/** 组内溢出披露态（本地 ref，不持久化）。 */
const overflowOpenGroups = ref<Set<RoutingGroup>>(new Set())

function isOverflowOpen(group: RoutingGroup): boolean {
  return overflowOpenGroups.value.has(group)
}

function toggleOverflow(group: RoutingGroup) {
  const next = new Set(overflowOpenGroups.value)
  if (next.has(group))
    next.delete(group)
  else
    next.add(group)
  overflowOpenGroups.value = next
}

function rowsOf(block: RoutingBlock): RoutingCandidate[] {
  return isOverflowOpen(block.group)
    ? [...block.visible, ...block.overflow]
    : block.visible
}

const collapsed = ref(false)

/** 降级是后端算好的事实；前端绝不按 router_version 或候选内容自行推断。 */
const degraded = computed(() => trace.value?.degraded === true)

const DEGRADED_BANNER_TITLE = '本次未经 LLM 推理，置信度仅供参考'

/** 降级原因受控闭集 → 中文文案（与后端 classify_degrade_reason 字面对齐）。 */
const DEGRADE_REASON_LABELS: Record<string, string> = {
  timeout: '上游超时',
  upstream_error: '网关错误',
  provider_missing: '未配置模型',
  unparsable: '解析失败',
  no_node_index: '无能力树索引',
  unknown: '未知原因',
}

// 未命中回退与 signalLabel 刻意相反：signalLabel 回显原始英文 key（新信号零
// 前端改动即可展示），这里一律回到「未知原因」、绝不回显原始值。原因是降级
// 原因的上游是异常分类，后端一旦出现闭集外的值（异常名或截断的上游响应体），
// 回显即成为泄漏面（T-107-02）。
const UNKNOWN_DEGRADE_REASON_LABEL = '未知原因'

function degradeReasonLabel(key: string): string {
  return DEGRADE_REASON_LABELS[key] ?? UNKNOWN_DEGRADE_REASON_LABEL
}

/** 空串表示「不渲染原因次行」（后端未给原因时只出主句）。 */
const degradeReasonText = computed(() => {
  const reason = trace.value?.degrade_reason
  return reason ? degradeReasonLabel(reason) : ''
})

function variantOf(level: RoutingLevel): 'success' | 'warning' | 'secondary' | 'muted' {
  // 灰化 = 「这个颜色信号本次不可信」；level 值本身不变
  if (degraded.value)
    return 'muted'
  if (level === 'high')
    return 'success'
  if (level === 'medium')
    return 'warning'
  return 'secondary'
}

function labelOf(level: RoutingLevel): string {
  return ({ high: '高', medium: '中', low: '低' } as const)[level]
}

/**
 * 分数分解信号名 → 中文标签（ROUTE-07 / ROUTE-04）。键与后端
 * SIGNAL_TEXT/SIGNAL_BREADTH/SIGNAL_ACTIVITY/SIGNAL_DOMAIN/SIGNAL_STACK/
 * SIGNAL_TEAM 常量字面对齐——Phase 106 六信号已入分；criticality 为同分带
 * tie-break 旁路字段不入 breakdown，故无标签。未知 key 回退显示原始英文
 * key（向前兼容，后续新增信号零前端改动即可展示）。
 */
const SIGNAL_LABELS: Record<string, string> = {
  text: '文本相关',
  breadth: '命中广度',
  activity: '活跃度',
  domain: '业务域匹配',
  stack: '技术栈匹配',
  team: '团队归属',
}

function signalLabel(key: string): string {
  return SIGNAL_LABELS[key] ?? key
}

/** 确定性 confidence 分级依据文案（UI-SPEC Copywriting 原文）。 */
const CONFIDENCE_TOOLTIPS: Record<RoutingLevel, string> = {
  high: '高置信：首位分数与领先幅度均超过阈值，由分数确定性推导',
  medium: '中置信：首位分数达标但领先幅度不足，建议人工确认',
  low: '低置信：候选分数整体偏低，请人工选择',
}

/** 降级态覆盖版：分数与分级仍是真实的 Stage 0 事实，只是未经语义校验。 */
const CONFIDENCE_TOOLTIPS_DEGRADED: Record<RoutingLevel, string> = {
  high: '本次未经 LLM 推理：分级由检索分数确定性推导，未经语义校验，仅供参考',
  medium: '本次未经 LLM 推理：首位领先幅度不足且未经语义校验，请人工确认',
  low: '本次未经 LLM 推理：候选分数整体偏低，请人工选择',
}

function confidenceTooltip(level: RoutingLevel): string {
  return degraded.value ? CONFIDENCE_TOOLTIPS_DEGRADED[level] : CONFIDENCE_TOOLTIPS[level]
}

function hasBreakdown(c: RoutingCandidate): boolean {
  return !!c.breakdown && Object.keys(c.breakdown).length > 0
}

/**
 * 展开态为组件本地 ref（非手风琴，多候选可同时展开）；
 * trace 更新（manual_override 写新 trace）后重置为收起。
 */
const expandedBreakdowns = ref<Set<string>>(new Set())

function setBreakdownOpen(repoId: string, open: boolean) {
  const next = new Set(expandedBreakdowns.value)
  if (open)
    next.add(repoId)
  else
    next.delete(repoId)
  expandedBreakdowns.value = next
}

watch(effectiveTraceId, () => {
  expandedBreakdowns.value = new Set()
  // 分组折叠态与溢出披露态同样不跨 trace 保留（override 会写新 trace）
  globalGroupOpenOverride.value = null
  overflowOpenGroups.value = new Set()
})

// 容差校验（每次 trace 数据变化跑一次）：|Σbreakdown − score| > 1e-6 仅
// console.warn，不阻断渲染——不变量由后端测试守护，前端不承担校验职责。
// 吃的是扁平化后的**全部**候选（不是分区后的可见集），语义与既有一致。
watch(
  allCandidates,
  (cands) => {
    for (const c of cands) {
      if (!hasBreakdown(c))
        continue
      const sum = Object.values(c.breakdown!).reduce((acc, v) => acc + v, 0)
      if (Math.abs(sum - c.score) > 1e-6) {
        console.warn(
          '[RoutingDecisionPanel] breakdown 合计与 score 不一致',
          { repository_id: c.repository_id, sum, score: c.score },
        )
      }
    }
  },
  { immediate: true },
)

/**
 * pendingOverrides 累积当前 debounce 窗口内的勾选变化；
 * sync 触发后清空。失败回滚由 store 内部返回 null 通知调用方处理。
 */
const pendingOverrides = ref<Map<string, boolean>>(new Map())

async function syncPending() {
  if (pendingOverrides.value.size === 0)
    return
  const payload: ManualOverrideRequestCandidate[] = Array.from(
    pendingOverrides.value,
    ([rid, sel]) => ({ repository_id: rid, selected: sel }),
  )
  pendingOverrides.value = new Map()
  const result = await routingStore.applyManualOverride(
    props.conversationId,
    effectiveTraceId.value,
    payload,
  )
  if (!result) {
    console.warn('manual override 失败，下一次操作时会重试')
  }
}

const debouncedSync = useDebounceFn(syncPending, 300)

function onToggle(repoId: string, value: boolean | string | undefined) {
  pendingOverrides.value.set(repoId, value === true)
  debouncedSync()
}

function checkedFor(c: RoutingCandidate): boolean {
  if (pendingOverrides.value.has(c.repository_id))
    return pendingOverrides.value.get(c.repository_id) === true
  return c.selected_by_user_final
}

function onCreateCodingPlan() {
  emit('createCodingPlanFromTrace', effectiveTraceId.value)
}

function onOpenManualSelect() {
  emit('manualSelectRequested', effectiveTraceId.value)
}
</script>

<template>
  <Card
    v-if="trace"
    class="relative my-2 rounded-md border border-zinc-200 bg-white/60 p-4 backdrop-blur"
  >
    <div class="flex w-full items-center gap-2">
      <button
        type="button"
        class="flex flex-1 items-center justify-between text-left text-sm font-medium text-zinc-800 transition-colors hover:text-zinc-950"
        @click="collapsed = !collapsed"
      >
        <span class="inline-flex items-center gap-2">
          <span>→ 路由决策（{{ allCandidates.length }} 个仓库相关）</span>
          <span class="text-xs text-zinc-500">
            高 {{ levelCounts.high }} · 中 {{ levelCounts.medium }} · 低 {{ levelCounts.low }}
          </span>
        </span>
        <span class="text-xs text-zinc-400">
          {{ collapsed ? '展开' : '收起' }}
        </span>
      </button>
      <!-- 折叠也藏不住降级：收起时由这枚紧凑徽标承载该事实 -->
      <Badge v-if="collapsed && degraded" variant="warning" class="shrink-0">
        <span class="icon-[lucide--triangle-alert] size-3" />
        降级
      </Badge>
    </div>

    <div v-if="!collapsed" class="mt-3 space-y-2">
      <!-- 降级横幅：位置在候选之前，让用户先看到「置信度本次不可信」 -->
      <div
        v-if="degraded"
        role="alert"
        aria-live="polite"
        class="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2.5"
      >
        <span class="icon-[lucide--triangle-alert] shrink-0 mt-0.5 text-amber-500" />
        <div class="min-w-0 space-y-1">
          <p class="text-sm font-medium text-foreground">
            {{ DEGRADED_BANNER_TITLE }}
          </p>
          <p v-if="degradeReasonText" class="text-xs text-muted-foreground">
            降级原因：{{ degradeReasonText }}
          </p>
        </div>
      </div>

      <div v-if="trace.query" class="text-xs text-zinc-500">
        query: <span class="text-zinc-700">{{ trace.query }}</span>
        <span class="ml-2">阈值 {{ trace.threshold.toFixed(2) }}</span>
      </div>

      <!-- 迟滞置顶提示：与「为什么全局组在前面」的因果相邻（两区之上） -->
      <div
        v-if="showPromotionNotice"
        role="status"
        class="flex items-start gap-2 rounded-lg border border-teal-500/30 bg-teal-500/5 px-3 py-2.5"
      >
        <span class="icon-[lucide--arrow-up-narrow-wide] shrink-0 mt-0.5 text-teal-700" />
        <p class="text-xs text-teal-700">
          {{ PROMOTION_SENTENCE }}
        </p>
      </div>

      <TooltipProvider :delay-duration="200">
        <div
          v-for="block in groupedBlocks"
          :key="block.group"
          class="space-y-1.5"
        >
          <!-- 全局组标题：可折叠（原生 button + aria-expanded，chevron 旋转沿用
               「分数分解」trigger 惯例） -->
          <button
            v-if="groupingEnabled && block.group === 'global'"
            type="button"
            :aria-expanded="globalGroupOpen"
            class="flex w-full items-center gap-1 text-left text-xs"
            @click="toggleGlobalGroup"
          >
            <span
              class="icon-[lucide--chevron-right] size-3 shrink-0 transition-transform"
              :class="{ 'rotate-90': globalGroupOpen }"
            />
            <span class="font-semibold text-foreground">{{ GROUP_LABELS[block.group] }}</span>
            <span class="text-muted-foreground">（{{ block.total }}）</span>
          </button>
          <!-- 本项目组标题：默认可见内容不该需要额外点击，故为纯静态标题 -->
          <div v-else-if="groupingEnabled" class="text-xs">
            <span class="font-semibold text-foreground">{{ GROUP_LABELS[block.group] }}</span>
            <span class="text-muted-foreground">（{{ block.total }}）</span>
          </div>

          <!-- 跨组标注第一层：组级完整句常驻可见（不依赖 hover，也不随折叠消失） -->
          <p
            v-if="groupingEnabled && block.group === 'global'"
            class="text-xs text-muted-foreground"
          >
            {{ CROSS_GROUP_SENTENCE }}
          </p>

          <template v-if="isBlockOpen(block)">
            <ul class="space-y-1.5" :class="{ 'pl-3': groupingEnabled }">
              <li
                v-for="c in rowsOf(block)"
                :key="c.repository_id"
                class="rounded px-1 py-1.5 hover:bg-zinc-50"
              >
                <div class="flex items-start gap-3">
                  <Checkbox
                    :model-value="checkedFor(c)"
                    class="mt-0.5"
                    @update:model-value="(v) => onToggle(c.repository_id, v)"
                  />
                  <span class="min-w-0 flex-1 truncate text-sm font-medium text-zinc-900">
                    {{ c.repository_name }}
                  </span>
                  <!-- 跨组标注第二层：候选级紧凑徽标，完整句由 Tooltip 与 aria-label 承载 -->
                  <Tooltip v-if="isCrossGroup(c)">
                    <TooltipTrigger as-child>
                      <Badge variant="info" class="shrink-0" :aria-label="CROSS_GROUP_SENTENCE">
                        跨组
                      </Badge>
                    </TooltipTrigger>
                    <TooltipContent class="max-w-[24rem] text-xs">
                      {{ CROSS_GROUP_SENTENCE }}
                    </TooltipContent>
                  </Tooltip>
                  <Tooltip>
                    <TooltipTrigger as-child>
                      <Badge :variant="variantOf(c.level)" class="shrink-0">
                        {{ Math.round(c.score * 100) }}% {{ labelOf(c.level) }}
                      </Badge>
                    </TooltipTrigger>
                    <TooltipContent class="max-w-[24rem] text-xs">
                      {{ confidenceTooltip(c.level) }}
                    </TooltipContent>
                  </Tooltip>
                  <Tooltip>
                    <TooltipTrigger as-child>
                      <p class="hidden max-w-[18rem] cursor-help truncate text-xs text-zinc-500 sm:block">
                        {{ c.evidence }}
                      </p>
                    </TooltipTrigger>
                    <TooltipContent class="max-w-[24rem] text-xs">
                      {{ c.evidence }}
                    </TooltipContent>
                  </Tooltip>
                </div>

                <Collapsible
                  v-if="hasBreakdown(c)"
                  :open="expandedBreakdowns.has(c.repository_id)"
                  @update:open="(v) => setBreakdownOpen(c.repository_id, v)"
                >
                  <CollapsibleTrigger class="flex items-center gap-1 py-1 pl-3 text-xs text-muted-foreground">
                    <span
                      class="icon-[lucide--chevron-right] size-3 transition-transform"
                      :class="{ 'rotate-90': expandedBreakdowns.has(c.repository_id) }"
                    />
                    分数分解
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <div class="flex flex-col gap-1 py-1 pl-3">
                      <div
                        v-for="(value, key) in c.breakdown"
                        :key="key"
                        class="flex items-center justify-between gap-2 px-2"
                      >
                        <span class="text-xs text-muted-foreground">{{ signalLabel(String(key)) }}</span>
                        <span class="text-right font-mono text-xs text-foreground">{{ value.toFixed(3) }}</span>
                      </div>
                      <div class="border-t border-border/50" />
                      <div class="flex items-center justify-between gap-2 px-2">
                        <span class="text-xs text-muted-foreground">合计</span>
                        <span class="text-right font-mono text-xs font-semibold text-foreground">{{ c.score.toFixed(3) }}</span>
                      </div>
                    </div>
                  </CollapsibleContent>
                </Collapsible>
              </li>
            </ul>

            <!-- 溢出披露：原生 button + aria-expanded，展开的候选按 rank 续在同一列表内 -->
            <button
              v-if="block.overflow.length"
              type="button"
              :aria-expanded="isOverflowOpen(block.group)"
              class="flex items-center gap-1 py-1 pl-3 text-xs text-muted-foreground"
              @click="toggleOverflow(block.group)"
            >
              <span
                class="icon-[lucide--chevron-right] size-3 shrink-0 transition-transform"
                :class="{ 'rotate-90': isOverflowOpen(block.group) }"
              />
              {{ isOverflowOpen(block.group) ? '收起其余候选' : `显示其余 ${block.overflow.length} 个候选` }}
            </button>
          </template>
        </div>
      </TooltipProvider>

      <div class="mt-3 flex flex-wrap gap-2">
        <Button size="sm" @click="onCreateCodingPlan">
          基于这些仓库创建编码方案
        </Button>
        <Button size="sm" variant="ghost" @click="onOpenManualSelect">
          手动调整选择
        </Button>
      </div>
    </div>
  </Card>
</template>
