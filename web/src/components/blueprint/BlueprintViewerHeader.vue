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
  /** 三个计数：未决 BLOCKER / 待澄清 / 失锚。 */
  counts?: { blocker: number, clarification: number, orphaned: number }
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
}>(), {
  doc: null,
  counts: () => ({ blocker: 0, clarification: 0, orphaned: 0 }),
  versions: () => [],
  currentVersionId: null,
  readonly: false,
  isLive: false,
  showClosed: false,
  sidebarCollapsed: false,
  currentStatus: '',
  revisionRound: 0,
  submitting: false,
})

const emit = defineEmits<{
  'toggle-sidebar': []
  'open-annotations': []
  'change-version': [versionId: string]
  'open-diff': [baseVersionId: string]
  'approve': []
  'reject': []
  'toggle-closed-annotations': [value: boolean]
}>()

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

/** 侧栏里可见的批注总数（窄屏按钮的计数，同样 0 时只显示「批注」）。 */
const annotationTotal = computed(
  () => props.counts.blocker + props.counts.clarification + props.counts.orphaned,
)

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
    <!-- 标题：与知识库主页 H1 同款字号（§14 的唯一例外） -->
    <h1 v-if="title" class="min-w-0 max-w-full truncate text-2xl font-bold tracking-tight">
      {{ title }}
    </h1>
    <div v-else class="h-7 w-56 animate-pulse rounded-md bg-muted" aria-hidden="true" />

    <BlueprintStatusBadge :status="currentStatus" />

    <!-- 三个计数徽标（⭐ 为 0 的档不出现在 countBadges 里） -->
    <Badge
      v-for="badge in countBadges"
      :key="badge.key"
      :variant="badge.variant"
      :data-count="badge.key"
    >
      <span :class="badge.icon" />
      {{ badge.label }}
    </Badge>

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
