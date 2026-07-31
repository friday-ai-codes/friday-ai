<script setup lang="ts">
/**
 * 项目侧的技术方案蓝图卡（Phase 115-06，UI-SPEC §12.2；VIEW-04 / SC-4）。
 *
 * 只读：列该项目的蓝图 + 11 态徽标 + 更新时间 + 深链跳查看器。
 *
 * ## ⚠️ 与同一面板里既有「交付物版本轨」的条目重叠（P-17，必须靠文案区分）
 *
 * 蓝图与旧的 technical_plan **共用同一个 `artifact_type`**，而版本轨那一块是按
 * `artifact_type="technical_plan"` 过滤的 ⇒ 同一份交付物会同时出现在两个区域里，内容看着
 * 很像。用户会以为系统重复展示，或者更糟 —— 误读成「两份不同的方案」。
 *
 * 区分策略：① 本卡的分区标题是「技术方案蓝图」，描述点明它是**结构化蓝图（含批注与人审）**，
 * 与版本轨的「交付物版本轨」在语义上分开；② 本卡只列**走了蓝图状态机**的条目（列表端点
 * 天然只返回 `blueprint_status != ''` 的 artifact）；③ 排在版本轨**之前**，让更新的形态先被看到。
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

function formatTime(raw: string): string {
  if (!raw)
    return ''
  const date = new Date(raw)
  return Number.isNaN(date.getTime()) ? raw : date.toLocaleString('zh-CN', { hour12: false })
}
</script>

<template>
  <section v-if="!hidden" class="flat-section" data-testid="project-blueprints-card">
    <header class="flat-header">
      <span class="section-chip"><span class="icon-[lucide--file-text]" /></span>
      <h3>{{ t('knowledge.blueprints.pageTitle') }}</h3>
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
            <span class="min-w-0 flex-1 truncate text-sm">{{ item.title }}</span>
            <span class="shrink-0 text-[11px] tabular-nums text-muted-foreground">
              {{ formatTime(item.updated_at) }}
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
