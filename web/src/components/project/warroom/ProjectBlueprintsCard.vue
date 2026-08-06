<script setup lang="ts">
/**
 * 项目侧的技术方案蓝图卡（Phase 115-06，UI-SPEC §12.2；VIEW-04 / SC-4）。
 *
 * 只读：列该项目的蓝图 + 11 态徽标 + 更新时间 + 深链跳查看器。
 *
 * ## 历史备注：与「交付物版本轨」的条目重叠（P-17）已随版本轨移除而消解
 *
 * 该面板此前另有一块按 `artifact_type="technical_plan"` 过滤的「交付物版本轨」区块，
 * 与本卡条目重叠（蓝图与旧 technical_plan 共用同一 `artifact_type`），用户会误读成
 * 「两份不同的方案」。版本轨区块已于职责收敛（quick 260806-sif）从项目资料面板移除——
 * 本卡是项目侧唯一的技术方案入口；`ArtifactTimeline` 组件仍服务于知识库 blueprints 页。
 * 本卡只列**走了蓝图状态机**的条目（列表端点天然只返回 `blueprint_status != ''` 的 artifact）。
 *
 * ## ⭐ 「无数据整块不渲染」是一个 prop，不是组件自决
 *
 * 照该面板既有 `HumanTaskInbox` 的 `hide-when-empty` 用法 —— 由**面板**决定某个分区在空项目里
 * 要不要出现，组件自己不该替宿主做这个决定（换个宿主就可能要反过来）。
 */

import { useQuery } from '@tanstack/vue-query'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import blueprintsApi from '~/api/blueprints'
import BlueprintStatusBadge from '~/components/blueprint/BlueprintStatusBadge.vue'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Skeleton } from '~/components/ui/skeleton'
import { formatBlueprintListTime } from '~/utils/blueprintTitle'

const props = withDefaults(defineProps<{
  projectId: string
  /** ⭐ 由宿主面板传入：无数据时整块不渲染。 */
  hideWhenEmpty?: boolean
}>(), {
  hideWhenEmpty: false,
})

/** 项目侧只展示最近的若干份，完整列表去知识库 tab。 */
const PAGE_SIZE = 5

const { t } = useI18n()

const listQuery = useQuery({
  queryKey: computed(() => ['blueprint', 'project-list', props.projectId]),
  queryFn: () => blueprintsApi.listBlueprints({ project_id: props.projectId, page_size: PAGE_SIZE }),
  enabled: computed(() => Boolean(props.projectId)),
  staleTime: 60_000,
  retry: false,
})

const items = computed(() => listQuery.data.value?.items ?? [])
const total = computed(() => listQuery.data.value?.total ?? 0)

/**
 * ⭐ `hideWhenEmpty` 只对**真的空**生效，⛔ 不对读失败生效（MJ-04）。
 *
 * 少了 `&& !listQuery.isError.value` 这一项，一次失败的请求（且 `retry: false`，**不重试**）
 * 就满足「不在 loading 且 items 为空」⇒ 整张「技术方案蓝图」卡从项目页上**凭空消失**，
 * 无任何痕迹。宿主 `ProjectMaterialsPanel` 正是传 `hide-when-empty` 的，所以这是默认路径。
 */
const hidden = computed(
  () => props.hideWhenEmpty
    && !listQuery.isLoading.value
    && !listQuery.isError.value
    && items.value.length === 0,
)

function formatTime(item: { created_at?: string, updated_at: string }): string {
  return formatBlueprintListTime(item.created_at || item.updated_at)
}
</script>

<template>
  <!-- ⭐ 样式必须走全局 `card` 模式（同面板的 HumanTaskInbox / ArtifactTimeline 同款）：
       `flat-section` / `flat-header` 只存在于宿主 ProjectMaterialsPanel 的 **scoped** 样式里，
       scoped CSS 不会作用到子组件内部 ⇒ 在这里用它们等于裸 DOM 无样式（头部图标/标题/徽标
       各占一行的破版就是这么来的）。 -->
  <section v-if="!hidden" class="card" data-testid="project-blueprints-card">
    <header class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2.5">
      <span class="section-chip"><span class="icon-[lucide--file-text]" /></span>
      <h2 class="text-sm font-semibold text-foreground">
        {{ t('knowledge.blueprints.pageTitle') }}
      </h2>
      <Badge v-if="total > 0" variant="muted">
        {{ total }}
      </Badge>
    </header>

    <div class="space-y-2 p-5">
      <p class="text-xs text-muted-foreground">
        {{ t('knowledge.blueprints.pageDescription') }}
      </p>

      <div v-if="listQuery.isLoading.value" class="space-y-2">
        <Skeleton v-for="n in 3" :key="n" class="h-10 w-full" />
      </div>

      <!-- ⭐ 读失败留卡片 + 给重试入口（⛔ 不与空态同形，见 `hidden` 的说明）。 -->
      <div
        v-else-if="listQuery.isError.value"
        class="flex items-center gap-2 rounded-lg border border-border bg-muted/20 px-3 py-2 text-sm text-muted-foreground"
        role="alert"
        data-testid="project-blueprints-error"
      >
        <span class="icon-[lucide--cloud-off] shrink-0" aria-hidden="true" />
        <span class="min-w-0 flex-1">{{ t('knowledge.blueprints.error.unavailable') }}</span>
        <Button variant="ghost" size="sm" data-testid="project-blueprints-retry" @click="listQuery.refetch()">
          {{ t('knowledge.blueprints.error.retry') }}
        </Button>
      </div>

      <ul v-else-if="items.length" class="space-y-1">
        <li v-for="item in items" :key="item.artifact_id">
          <RouterLink
            :to="`/knowledge/blueprints/${item.artifact_id}`"
            class="flex items-center gap-2 rounded-lg px-2 py-1.5 transition-colors hover:bg-muted/40"
            data-testid="project-blueprint-item"
            :data-artifact-id="item.artifact_id"
          >
            <BlueprintStatusBadge :status="item.current_status" size="sm" class="shrink-0" />
            <span class="min-w-0 flex-1 truncate text-sm" :title="item.title">{{ item.title }}</span>
            <span
              class="shrink-0 text-xs tabular-nums text-muted-foreground"
              data-testid="project-blueprint-time"
            >
              {{ formatTime(item) }}
            </span>
          </RouterLink>
        </li>
      </ul>

      <CompactEmptyState
        v-else
        icon="lucide--file-x"
        :title="t('knowledge.blueprints.tabPanel.emptyTitle')"
      />
    </div>
  </section>
</template>
