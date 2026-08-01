<script setup lang="ts">
/**
 * 路由候选清单（ROUTE-01 / ROUTE-02 / ROUTE-07 / RELY-03 的用户可见面）。
 *
 * 挂载位置：`ToolProcessGroup` 里「仓库分级路由」那一步的 L2 详情区 —— 也就是
 * 用户今天**真的会看到**候选仓的那块面。此前这四条需求的呈现全部压在
 * `RoutingDecisionPanel.vue` 上，而那个组件自 `29247521`（2026-05-29）起就没有
 * 任何挂载点。
 *
 * 🔴 本组件是**只读解释面**：没有 Checkbox、没有「基于这些仓库创建编码方案」
 * 按钮、不发任何 emit、不写任何 store。当初把面板下线的理由是它与气泡底部的
 * 澄清卡在「选仓 + 提交」这件事上重复；只搬解释、不搬选择，那条重复就不会
 * 被重新引入 —— 选仓仍然只有澄清卡一个入口。
 *
 * 文案沿用本组件家族的 COPY 常量表惯例（`useOrchestrationTimeline.COPY` /
 * `TOOL_LABELS` 先例）：模板里不出现裸中文串，全部集中在一处便于替换。
 */
import type { RoutingDecisionView } from '~/composables/useToolDisplay'
import type { RoutingGroup } from '~/types/routing'
import { ref } from 'vue'
import { Badge } from '~/components/ui/badge'

const props = defineProps<{
  view: RoutingDecisionView
  /** repository_id → 会话级稳定编号（与过程面板其余行同一套编号）。 */
  repoIndex?: Map<string, number>
}>()

/** 全部用户可见文案。 */
const COPY = {
  groupInProject: '本项目关联仓',
  groupGlobal: '全局候选',
  groupCount: (n: number) => `（${n}）`,
  /**
   * 跨组说明句（ROUTE-02）。取**前端常量**而不是后端的 `cross_group_note`：
   * 那是留痕/排障用的自由文本，把上游文本变成渲染面等于凭空多一条泄漏面
   * （T-107-06）。
   */
  crossGroup: '未关联当前平台，可能涉及跨组协作',
  crossGroupBadge: '跨组',
  /** 全局组被置顶：后端 delta 迟滞比较的结果 ⇒ 「更匹配」暗示了一次比较，成立。 */
  promoted: '更匹配的仓不在本项目关联范围内',
  /** 本项目组一条候选都没有时并没有发生比较，也没有被压下去的对比对象 ⇒ 陈述句。 */
  promotedEmpty: '本项目关联范围内没有匹配的仓库',
  degradedTitle: '本次未经 LLM 推理，置信度仅供参考',
  degradedReason: (label: string) => `降级原因：${label}`,
  breakdownToggle: '分数分解',
  breakdownTotal: '合计',
  levelHigh: '高',
  levelMedium: '中',
  levelLow: '低',
} as const

const GROUP_LABELS: Record<RoutingGroup, string> = {
  in_project: COPY.groupInProject,
  global: COPY.groupGlobal,
}

const LEVEL_LABELS = {
  high: COPY.levelHigh,
  medium: COPY.levelMedium,
  low: COPY.levelLow,
} as const

/** 降级原因受控闭集 → 中文文案（与后端 `classify_degrade_reason` 字面对齐）。 */
const DEGRADE_REASON_LABELS: Record<string, string> = {
  timeout: '上游超时',
  upstream_error: '网关错误',
  provider_missing: '未配置模型',
  unparsable: '解析失败',
  no_node_index: '无能力树索引',
  unknown: '未知原因',
}

/**
 * 未命中一律回到「未知原因」、**绝不回显原始值**。降级原因的上游是异常分类，
 * 后端一旦冒出闭集外的值（异常名或截断的上游响应体），回显即成为泄漏面
 * （T-107-02）。这与信号名标签的处理刻意相反——那边回显英文 key 是为了让新
 * 信号零前端改动就能展示，这边没有这个诉求。
 */
const UNKNOWN_DEGRADE_REASON_LABEL = '未知原因'

/**
 * 分数分解信号名 → 中文标签（ROUTE-07 / ROUTE-04）。键与后端 SIGNAL_* 常量
 * 字面对齐。未知 key 回退显示原始英文 key（向前兼容：后续新增信号零前端改动
 * 即可展示）。
 */
const SIGNAL_LABELS: Record<string, string> = {
  text: '文本相关',
  breadth: '命中广度',
  activity: '活跃度',
  domain: '业务域匹配',
  stack: '技术栈匹配',
  team: '团队归属',
}

function groupLabel(group: RoutingGroup): string {
  return GROUP_LABELS[group]
}

function signalLabel(key: string): string {
  return SIGNAL_LABELS[key] ?? key
}

function degradeReasonText(): string {
  const reason = props.view.degradeReason
  if (!reason)
    return ''
  return DEGRADE_REASON_LABELS[reason] ?? UNKNOWN_DEGRADE_REASON_LABEL
}

/** 置顶提示句：本项目组为空时没有发生比较，「更匹配」会暗示一次并不存在的比较。 */
function promotionSentence(): string {
  return props.view.inProjectEmpty ? COPY.promotedEmpty : COPY.promoted
}

/** 跨组徽标只在**启用分组**时出现：平铺态下标「跨组」没有对照组，反而误导。 */
function isCrossGroup(group: RoutingGroup): boolean {
  return props.view.grouped && group === 'global'
}

/** 灰化 = 「这个颜色信号本次不可信」；level 值本身不变（RELY-03 徽标半边）。 */
function levelVariant(level: 'high' | 'medium' | 'low'): 'success' | 'warning' | 'secondary' | 'muted' {
  if (props.view.degraded)
    return 'muted'
  if (level === 'high')
    return 'success'
  if (level === 'medium')
    return 'warning'
  return 'secondary'
}

function hasBreakdown(breakdown: Record<string, number>): boolean {
  return Object.keys(breakdown).length > 0
}

/** 展开态：本地 ref，非手风琴（多条候选可同时展开）。 */
const expanded = ref<Set<string>>(new Set())

function isExpanded(id: string): boolean {
  return expanded.value.has(id)
}

function toggle(id: string): void {
  const next = new Set(expanded.value)
  if (next.has(id))
    next.delete(id)
  else
    next.add(id)
  expanded.value = next
}

function candidateKey(id: string, name: string): string {
  return id || name
}

function candidateNumber(id: string, fallbackIndex: number): number {
  return props.repoIndex?.get(id) ?? fallbackIndex + 1
}
</script>

<template>
  <div class="flex flex-col gap-1.5" data-test="routing-candidate-list">
    <!--
      降级横幅置于候选之前：先让用户看到「置信度本次不可信」，再看分数。
      放在候选之后等于让用户先按分数做完判断，再告诉他分数不可信。
    -->
    <div
      v-if="view.degraded"
      role="alert"
      class="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 px-2.5 py-2"
      data-test="routing-degraded-banner"
    >
      <span class="icon-[lucide--triangle-alert] mt-0.5 shrink-0 text-[11px] text-amber-600" />
      <div class="min-w-0 space-y-0.5">
        <p class="text-[11px] font-medium text-foreground">
          {{ COPY.degradedTitle }}
        </p>
        <p v-if="degradeReasonText()" class="text-[10px] text-muted-foreground">
          {{ COPY.degradedReason(degradeReasonText()) }}
        </p>
      </div>
    </div>

    <!-- 迟滞置顶提示：与「为什么全局组排在前面」的因果相邻（两区之上） -->
    <p
      v-if="view.promoted"
      role="status"
      class="rounded-lg border border-teal-500/30 bg-teal-500/5 px-2.5 py-1.5 text-[10px] text-teal-700"
      data-test="routing-promotion-notice"
    >
      {{ promotionSentence() }}
    </p>

    <div
      v-for="block in view.blocks"
      :key="block.group"
      class="flex flex-col gap-1"
      :data-test="`routing-block-${block.group}`"
    >
      <!-- 组标题（ROUTE-01）：只在启用分组时出现，平铺态与今日渲染逐字一致 -->
      <p v-if="view.grouped" class="text-[10px]" data-test="routing-group-heading">
        <span class="font-semibold text-foreground">{{ groupLabel(block.group) }}</span>
        <span class="text-muted-foreground">{{ COPY.groupCount(block.candidates.length) }}</span>
      </p>

      <!-- 跨组标注第一层（ROUTE-02）：组级完整句常驻可见，不依赖 hover -->
      <p
        v-if="isCrossGroup(block.group)"
        class="text-[10px] text-muted-foreground"
        data-test="routing-cross-group-note"
      >
        {{ COPY.crossGroup }}
      </p>

      <ul class="m-0 flex list-none flex-col gap-1 p-0" :class="view.grouped ? 'pl-2' : undefined">
        <li
          v-for="(c, ci) in block.candidates"
          :key="candidateKey(c.id, c.name)"
          class="rounded-md border border-border/70 bg-background/70 px-2 py-1.5"
          data-test="routing-candidate"
        >
          <div class="flex flex-wrap items-center gap-1.5">
            <span
              class="inline-flex h-4 min-w-4 shrink-0 items-center justify-center rounded-full bg-primary/10 px-1 text-[9px] font-bold tabular-nums text-primary"
            >
              {{ candidateNumber(c.id, ci) }}
            </span>
            <span class="text-[11px] font-semibold text-foreground">{{ c.name }}</span>
            <!-- 跨组标注第二层：候选级紧凑徽标，完整句由 aria-label 承载 -->
            <Badge
              v-if="isCrossGroup(block.group)"
              variant="info"
              class="shrink-0 px-1.5 py-0 text-[9px]"
              :aria-label="COPY.crossGroup"
              data-test="routing-cross-group-badge"
            >
              {{ COPY.crossGroupBadge }}
            </Badge>
            <Badge
              :variant="levelVariant(c.level)"
              class="shrink-0 px-1.5 py-0 text-[9px]"
              data-test="routing-level-badge"
            >
              {{ LEVEL_LABELS[c.level] }} {{ c.score.toFixed(2) }}
            </Badge>
          </div>

          <p v-if="c.evidence" class="mt-0.5 text-[10px] leading-relaxed text-muted-foreground">
            {{ c.evidence }}
          </p>

          <!-- 分数分解（ROUTE-07）：原生 button + aria-expanded，收起为默认 -->
          <template v-if="hasBreakdown(c.breakdown)">
            <button
              type="button"
              class="mt-0.5 flex items-center gap-1 text-[10px] text-muted-foreground"
              :aria-expanded="isExpanded(candidateKey(c.id, c.name))"
              data-test="routing-breakdown-toggle"
              @click="toggle(candidateKey(c.id, c.name))"
            >
              <span
                class="icon-[lucide--chevron-right] size-2.5 shrink-0 transition-transform"
                :class="isExpanded(candidateKey(c.id, c.name)) ? 'rotate-90' : undefined"
              />
              {{ COPY.breakdownToggle }}
            </button>
            <div
              v-if="isExpanded(candidateKey(c.id, c.name))"
              class="mt-0.5 flex flex-col gap-0.5 pl-3"
              data-test="routing-breakdown"
            >
              <div
                v-for="(value, key) in c.breakdown"
                :key="key"
                class="flex items-center justify-between gap-2"
              >
                <span class="text-[10px] text-muted-foreground">{{ signalLabel(String(key)) }}</span>
                <span class="text-right font-mono text-[10px] text-foreground">{{ value.toFixed(3) }}</span>
              </div>
              <div class="border-t border-border/50" />
              <div class="flex items-center justify-between gap-2">
                <span class="text-[10px] text-muted-foreground">{{ COPY.breakdownTotal }}</span>
                <span class="text-right font-mono text-[10px] font-semibold text-foreground">{{ c.score.toFixed(3) }}</span>
              </div>
            </div>
          </template>
        </li>
      </ul>
    </div>
  </div>
</template>
