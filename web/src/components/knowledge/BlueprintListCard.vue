<script setup lang="ts">
/**
 * 蓝图列表卡（Phase 115-06，UI-SPEC §12.1）。
 *
 * ⭐ **整卡就是一个 `RouterLink`，深链直达查看器**（SC-4）：`/knowledge/blueprints/{artifact_id}`
 * 是蓝图对外的唯一形态，Phase 116 的入口收编与导出也一律指向它。
 *
 * ⚠️ **状态键是 `current_status`**（115-01 对 UI-SPEC §3.3 的订正）：后端的 INV-6 字段级守卫
 * 扫全 `server/`，响应键若用模型字段名即判旁路写，所以列表项的状态键与 query 参数名**刻意
 * 不同名**。读错键的症状是徽标恒显示「旧版方案」——不报错、不空白，只是一直不对。
 *
 * ⭐ **阻塞计数为 0 时整个徽标不渲染**（§12.1）：显示一个「阻塞 0」比不显示更糟。
 */

import type { BlueprintListItem } from '~/types/blueprint'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import BlueprintStatusBadge from '~/components/blueprint/BlueprintStatusBadge.vue'
import { Badge } from '~/components/ui/badge'
import { formatBlueprintListTime } from '~/utils/blueprintTitle'

const props = defineProps<{
  item: BlueprintListItem
}>()

/** 仓库 chip 最多展示几个，其余折成 `+{n}`。 */
const REPO_CHIP_LIMIT = 3

const { t } = useI18n()

const visibleRepos = computed(() => props.item.repositories?.slice(0, REPO_CHIP_LIMIT) ?? [])
const extraRepoCount = computed(() => Math.max(0, (props.item.repositories?.length ?? 0) - REPO_CHIP_LIMIT))

/** 优先 created_at；无则回落 updated_at。固定到分钟，不含秒。 */
const listTime = computed(() =>
  formatBlueprintListTime(props.item.created_at || props.item.updated_at),
)
</script>

<template>
  <RouterLink
    :to="`/knowledge/blueprints/${item.artifact_id}`"
    class="card card-interactive block space-y-2 p-4"
    data-testid="blueprint-list-card"
    :data-artifact-id="item.artifact_id"
  >
    <div class="flex items-start gap-2">
      <BlueprintStatusBadge :status="item.current_status" size="sm" class="mt-0.5 shrink-0" />
      <h3 class="line-clamp-2 min-w-0 flex-1 text-base font-semibold leading-snug">
        {{ item.title }}
      </h3>
    </div>

    <p v-if="item.summary" class="line-clamp-2 text-xs text-muted-foreground">
      {{ item.summary }}
    </p>

    <div class="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
      <span v-if="item.project_name" class="inline-flex items-center gap-1">
        <span class="icon-[lucide--folder] text-[11px]" aria-hidden="true" />
        {{ item.project_name }}
      </span>
      <span>{{ t('knowledge.blueprints.tabPanel.versionNo', { n: item.current_version_no }) }}</span>
      <span v-if="item.revision_round > 0">
        {{ t('knowledge.blueprints.tabPanel.revisionRound', { n: item.revision_round }) }}
      </span>
    </div>

    <div v-if="visibleRepos.length" class="flex flex-wrap items-center gap-1">
      <Badge
        v-for="repo in visibleRepos"
        :key="repo.id"
        variant="outline"
        :data-role="repo.role"
        data-testid="blueprint-list-repo"
      >
        {{ repo.name }}
      </Badge>
      <Badge v-if="extraRepoCount > 0" variant="muted">
        +{{ extraRepoCount }}
      </Badge>
    </div>

    <div class="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
      <span class="inline-flex items-center gap-1">
        <span class="icon-[lucide--messages-square] text-[11px]" aria-hidden="true" />
        {{ t('knowledge.blueprints.tabPanel.threadCount', { n: item.thread_count }) }}
      </span>
      <!-- ⭐ 计数为 0 时整块不渲染 -->
      <Badge
        v-if="item.unresolved_blocker_count > 0"
        variant="destructive"
        data-testid="blueprint-list-blocker"
      >
        {{ t('knowledge.blueprints.tabPanel.blockerCount', { n: item.unresolved_blocker_count }) }}
      </Badge>
      <span
        v-if="listTime"
        class="ml-auto tabular-nums"
        data-testid="blueprint-list-time"
      >{{ listTime }}</span>
    </div>
  </RouterLink>
</template>
