<script setup lang="ts">
/**
 * 蓝图查看器顶栏（Phase 115-06，UI-SPEC §5.1 / §5.3 / §16）。
 *
 * 一条 `sticky top-0 z-30` 的卡片带，从左到右：标题 → 11 态徽标 → 三个计数徽标 → 版本切换器
 * → 生成中指示 → 阅读区开关（显示已关闭批注 / 侧栏折叠 / 窄屏批注抽屉）→ 终审操作区。
 *
 * ## 三条纪律
 *
 * 1. ⭐ **不重复实现终审可用性逻辑**：哪个状态下能通过 / 能驳回、`disabled` 时 Tooltip 说什么，
 *    全部是 `BlueprintReviewActions`（115-04）的职责，本组件只把 props/emits 原样透传。
 *    两处各写一份判据，迟早会分叉成「按钮亮着但点了 400」。
 * 2. ⭐ **计数为 0 时不显示 0**：§16 规定「批注 {n}」在 `n === 0` 时作「批注」。三个计数徽标
 *    同理 —— 一个灰色的 `0` 只会让人误以为「有一项待处理」。
 * 3. ⛔ **零颜色字面量**：语义色一律走 `Badge` 的 `variant`，⛔ 不在 `Badge` 上用 `:class` 追加颜色类。
 *
 * ## ⭐ 「未经确认」常驻横幅（Phase 116-05，VIEW-05）
 *
 * 判据是 `CONFIRMED_STATUSES` 这个**闭合白名单**，三个字面量与后端
 * `server/services/process_runtime/blueprint_render.py` 的 `_SUPPRESS_WATERMARK_STATUSES`
 * **逐字对齐**（两侧各有一条变异用例：去掉任一成员即转红）。白名单**之外**的一切取值
 * ——含空串与未知串——都渲染横幅。
 *
 * ⛔ **横幅不可关闭、不做 dismiss**：这是 RELY-01 在界面上的唯一落点，标注一丢，未经人审
 * 的方案就以正式方案的面貌流通。把开关物理删掉，而不是默认开着。
 *
 * ⭐ **导出按钮按 availability「隐藏」而不是 disabled**：不可用时按钮**不存在于 DOM**，
 * 用户不会反复点、反复失败。本组件**只 emit 不发请求**（115-04 立的纪律）——availability
 * 查询与导出 mutation 都归页面。
 *
 * ⚠️ **与 PLAN 的两处签名差异**（登记在 115-06-SUMMARY 的 Deviations）：
 * - 删掉 PLAN 列的 `snapshot` prop —— 顶栏需要的 `currentStatus` / `revisionRound` / 三个计数
 *   都由页面派生后单独传入，快照原件在这里没有消费者（沿用 115-03 订正一「零消费的接口是死接口」）。
 * - 新增 `open-annotations` emit —— 窄屏的「批注 {n}」按钮唤起的是抽屉，与 `xl` 常驻侧栏的
 *   折叠是**两个不同目标**；共用一个 emit 会让页面无法区分（且页面不该去猜断点）。
 */

import type { BlueprintVersionEntry } from './BlueprintVersionSwitcher.vue'
import type { BlueprintDocumentResponse } from '~/types/blueprint'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Switch } from '~/components/ui/switch'
import BlueprintReviewActions from './BlueprintReviewActions.vue'
import BlueprintStatusBadge from './BlueprintStatusBadge.vue'
import BlueprintVersionSwitcher from './BlueprintVersionSwitcher.vue'

const props = withDefaults(defineProps<{
  /** 当前展示的正文（含 `meta.title`）；首屏加载时为 `null` ⇒ 标题位出骨架条。 */
  doc?: BlueprintDocumentResponse | null
  /** 三个语义计数：未决 BLOCKER / 待澄清 / 失锚。 */
  counts?: { blocker: number, clarification: number, orphaned: number }
  /**
   * 批注**总数**（窄屏「批注 {n}」按钮用）。
   *
   * ⭐ 由页面按侧栏四组之和算出（`annotationCounts().total`）。
   * ⛔ **不得**在本组件里用上面三个语义计数相加冒充 —— 它们口径不正交：失锚的未决 blocker
   * 会被数两次，而人工评论 / 已作答 / 已关闭线程一条都数不到（UI-REVIEW M-1）。
   */
  annotationTotal?: number
  versions?: BlueprintVersionEntry[]
  currentVersionId?: string | null
  /** 只读模式（不可编辑状态 / 历史版本 / diff 视图）⇒ 终审操作区整块不渲染。 */
  readonly?: boolean
  /** 生成中（三个活跃态之一）。 */
  isLive?: boolean
  showClosed?: boolean
  sidebarCollapsed?: boolean
  /** 一律以人审快照响应体的 `current_status` 为准。 */
  currentStatus?: string
  revisionRound?: number
  submitting?: boolean
  /** 飞书导出可用性（页面查 availability 后传入）；⛔ 非 `true` 一律不渲染导出按钮。 */
  exportAvailable?: boolean
  exporting?: boolean
}>(), {
  doc: null,
  counts: () => ({ blocker: 0, clarification: 0, orphaned: 0 }),
  annotationTotal: 0,
  versions: () => [],
  currentVersionId: null,
  readonly: false,
  isLive: false,
  showClosed: false,
  sidebarCollapsed: false,
  currentStatus: '',
  revisionRound: 0,
  submitting: false,
  exportAvailable: false,
  exporting: false,
})

const emit = defineEmits<{
  'toggle-sidebar': []
  'open-annotations': []
  'change-version': [versionId: string]
  'open-diff': [baseVersionId: string]
  'approve': []
  'reject': []
  'toggle-closed-annotations': [value: boolean]
  'export': []
}>()

/**
 * ⭐ 抑制「未经确认」横幅的**闭合白名单**。
 *
 * 三个字面量与后端 `blueprint_render._SUPPRESS_WATERMARK_STATUSES` 逐字相同。
 * ⛔ 这是白名单不是黑名单：**集合之外的一切取值都出横幅**（含空串、含未知串）——
 * 新增一个蓝图状态时默认「未确认」，方向是 fail-safe 的。
 */
const CONFIRMED_STATUSES = ['confirmed', 'implementing', 'implemented'] as const

/** 常驻横幅的唯一判据；⛔ 无 dismiss、无 localStorage、无开关。 */
const unconfirmed = computed(
  () => !(CONFIRMED_STATUSES as readonly string[]).includes(props.currentStatus),
)

const { t } = useI18n()

const title = computed(() => props.doc?.content?.meta?.title ?? '')

/** 三个计数徽标；⭐ 值为 0 的档**不进这张表**（§16：不显示 0）。 */
const countBadges = computed(() => {
  const rows: Array<{ key: string, label: string, variant: 'destructive' | 'warning' | 'muted', icon: string }> = []
  if (props.counts.blocker > 0) {
    rows.push({
      key: 'blocker',
      label: t('knowledge.blueprints.annotation.countBlocker', { n: props.counts.blocker }),
      variant: 'destructive',
      icon: 'icon-[lucide--alert-circle]',
    })
  }
  if (props.counts.clarification > 0) {
    rows.push({
      key: 'clarification',
      label: t('knowledge.blueprints.annotation.countClarification', { n: props.counts.clarification }),
      variant: 'warning',
      icon: 'icon-[lucide--help-circle]',
    })
  }
  if (props.counts.orphaned > 0) {
    rows.push({
      key: 'orphaned',
      label: t('knowledge.blueprints.annotation.countOrphaned', { n: props.counts.orphaned }),
      variant: 'muted',
      icon: 'icon-[lucide--unlink]',
    })
  }
  return rows
})

const sidebarToggleLabel = computed(() =>
  props.sidebarCollapsed
    ? t('knowledge.blueprints.annotation.sidebarExpand')
    : t('knowledge.blueprints.annotation.sidebarCollapse'),
)
</script>

<template>
  <div
    class="card sticky top-0 z-30 flex flex-wrap items-center gap-x-3 gap-y-2 px-5 py-3"
    data-testid="blueprint-viewer-header"
  >
    <!-- ⭐ 「未经确认」常驻横幅：⛔ 无关闭控件、⛔ 无 dismiss —— 白名单外一律渲染 -->
    <div
      v-if="unconfirmed"
      class="flex w-full items-center gap-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-sm"
      role="status"
      data-testid="blueprint-unconfirmed-banner"
    >
      <span class="icon-[lucide--alert-triangle]" aria-hidden="true" />
      <span>{{ t('knowledge.blueprints.export.unconfirmedBanner') }}</span>
    </div>

    <!-- 标题：与知识库主页 H1 同款字号（§14 的唯一例外） -->
    <h1 v-if="title" class="min-w-0 max-w-full truncate text-2xl font-bold tracking-tight">
      {{ title }}
    </h1>
    <div v-else class="h-7 w-56 animate-pulse rounded-md bg-muted" aria-hidden="true" />

    <BlueprintStatusBadge :status="currentStatus" />

    <!-- 三个计数徽标（⭐ 为 0 的档不出现在 countBadges 里）。
         ⭐ 自己包一层 `flex-nowrap overflow-x-auto`：§5.2 的 `< md` 行写的是「计数徽标折成
         一行可横向滚动」。顶栏是 `sticky`，让徽标参与外层 `flex-wrap` 会在窄屏把整条顶栏
         撑高，直接挤压它下方的正文可视区。 -->
    <div
      v-if="countBadges.length"
      class="flex min-w-0 flex-nowrap items-center gap-2 overflow-x-auto"
      data-testid="blueprint-header-counts"
    >
      <Badge
        v-for="badge in countBadges"
        :key="badge.key"
        :variant="badge.variant"
        :data-count="badge.key"
        class="shrink-0 whitespace-nowrap"
      >
        <span :class="badge.icon" />
        {{ badge.label }}
      </Badge>
    </div>

    <!-- 生成中指示 -->
    <span
      v-if="isLive"
      class="inline-flex items-center gap-1.5 text-xs text-muted-foreground"
      aria-live="polite"
      data-testid="blueprint-viewer-live"
    >
      <span class="icon-[lucide--loader-2] animate-spin" />
      {{ t('knowledge.blueprints.viewer.live') }}
    </span>

    <BlueprintVersionSwitcher
      :versions="versions"
      :current-version-id="currentVersionId"
      @change="emit('change-version', $event)"
      @compare="emit('open-diff', $event)"
    />

    <!-- 阅读区开关 -->
    <label class="inline-flex items-center gap-2 text-xs text-muted-foreground">
      <Switch
        :model-value="showClosed"
        data-testid="blueprint-header-show-closed"
        @update:model-value="emit('toggle-closed-annotations', $event)"
      />
      <span>
        {{ t('knowledge.blueprints.annotation.showClosed') }}
      </span>
    </label>

    <Button
      variant="ghost"
      size="sm"
      class="hidden xl:inline-flex"
      :aria-label="sidebarToggleLabel"
      :title="sidebarToggleLabel"
      data-testid="blueprint-header-sidebar-toggle"
      @click="emit('toggle-sidebar')"
    >
      <span :class="sidebarCollapsed ? 'icon-[lucide--panel-left-open]' : 'icon-[lucide--panel-left-close]'" />
    </Button>

    <!-- 窄屏：唤起批注抽屉 -->
    <Button
      variant="outline"
      size="sm"
      class="xl:hidden"
      :aria-label="t('knowledge.blueprints.annotation.sidebarToggleAria', { n: annotationTotal })"
      data-testid="blueprint-header-open-annotations"
      @click="emit('open-annotations')"
    >
      <span class="icon-[lucide--messages-square] mr-1.5" />
      {{ annotationTotal > 0
        ? t('knowledge.blueprints.annotation.sidebarToggle', { n: annotationTotal })
        : t('knowledge.blueprints.annotation.sidebarToggleEmpty') }}
    </Button>

    <!-- ⭐ 导出按钮：availability 非 true ⇒ **不渲染**（⛔ 不是 disabled + tooltip）；只 emit -->
    <Button
      v-if="exportAvailable"
      variant="outline"
      size="sm"
      :disabled="exporting"
      data-testid="blueprint-header-export"
      @click="emit('export')"
    >
      <span class="icon-[lucide--file-up] mr-1.5" />
      {{ t('knowledge.blueprints.export.action') }}
    </Button>

    <!-- ⭐ 终审操作区：可用性判断、二次确认与 Tooltip 全在 115-04 的组件里，本组件只透传 -->
    <div v-if="!readonly" class="ml-auto flex items-center">
      <BlueprintReviewActions
        :current-status="currentStatus"
        :revision-round="revisionRound"
        :submitting="submitting"
        @approve="emit('approve')"
        @reject="emit('reject')"
      />
    </div>
  </div>
</template>
