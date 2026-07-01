<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { knowledgeApi } from '~/api'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'
import { Badge } from '~/components/ui/badge'
import { Skeleton } from '~/components/ui/skeleton'

// 关联展示卡（KDEP-11，read-only）：
// - 正向（工件 document）：展示关联仓库 / 能力 / 关键词，均可点击导航；
// - 反向（仓库 repository）：展示相关交付文档，点击跳该文档知识实体（双向可导航闭环）。
const props = defineProps<{
  sourceKind: string
  sourceId: string
  kind: string
}>()

const { t } = useI18n()

// 工件类型/能力徽标配色令牌（复用 Phase 96 令牌，视觉统一）。
const ARTIFACT_BADGE_CLASS = 'bg-amber-500/10 text-amber-700 border-amber-200 dark:text-amber-400'

// 载体/类型兜底图标（复用 Phase 97 载体图标集合，字面量完整 class 命中 Tailwind 扫描）。
const CARRIER_ICON: Record<string, string> = {
  feishu_doc: 'icon-[lucide--file-text]',
  feishu_bitable: 'icon-[lucide--table]',
  markdown: 'icon-[lucide--file-text]',
  repo_file: 'icon-[lucide--file-code]',
  external_link: 'icon-[lucide--external-link]',
}
function carrierIcon(carrier: string): string {
  return CARRIER_ICON[carrier] ?? 'icon-[lucide--file]'
}

const isForward = computed(() => props.sourceKind === 'artifact')
const isReverse = computed(() => props.kind === 'repository')

const forwardQuery = useQuery({
  queryKey: computed(() => ['knowledge', 'artifact-associations', props.sourceId]),
  queryFn: () => knowledgeApi.getArtifactAssociations(props.sourceId),
  enabled: isForward,
  staleTime: 30_000,
})

const reverseQuery = useQuery({
  queryKey: computed(() => ['knowledge', 'repository-artifacts', props.sourceId]),
  queryFn: () => knowledgeApi.getRepositoryArtifacts(props.sourceId),
  enabled: isReverse,
  staleTime: 30_000,
})

const isLoading = computed(() =>
  (isForward.value && forwardQuery.isLoading.value)
  || (isReverse.value && reverseQuery.isLoading.value),
)
const isError = computed(() =>
  (isForward.value && forwardQuery.isError.value)
  || (isReverse.value && reverseQuery.isError.value),
)

const forward = computed(() => forwardQuery.data.value)
const reverseDocs = computed(() => reverseQuery.data.value?.artifacts ?? [])

const forwardEmpty = computed(() => {
  const f = forward.value
  if (!f)
    return true
  return !f.repositories.length && !f.capabilities.length && !f.keywords.length
})

const isEmpty = computed(() => {
  if (isForward.value)
    return forwardEmpty.value
  if (isReverse.value)
    return reverseDocs.value.length === 0
  return true
})
</script>

<template>
  <div class="card p-5" data-testid="entity-associations-card">
    <Skeleton v-if="isLoading" class="h-24 w-full" />
    <p v-else-if="isError" class="text-xs text-muted-foreground">
      {{ t('knowledge.entity.associations.loadFailed') }}
    </p>
    <CompactEmptyState
      v-else-if="isEmpty"
      icon="lucide--unlink"
      :title="t('knowledge.entity.associations.empty')"
    />
    <template v-else>
      <!-- 正向：工件 → 仓库 / 能力 / 关键词 -->
      <div v-if="isForward && forward" class="space-y-4">
        <div v-if="forward.repositories.length" class="space-y-2">
          <h3 class="text-xs font-semibold text-muted-foreground">
            {{ t('knowledge.entity.associations.repositories') }}
          </h3>
          <RouterLink
            v-for="repo in forward.repositories"
            :key="repo.repository_id"
            :to="`/repositories/${repo.repository_id}`"
            class="flex items-start gap-2 rounded border border-border/60 p-2.5 hover:bg-muted/30"
            data-testid="assoc-repo-link"
          >
            <span class="icon-[lucide--git-branch] mt-0.5 shrink-0 text-muted-foreground" />
            <span class="min-w-0 flex-1">
              <span class="block text-sm font-medium hover:text-primary">{{ repo.repo_name }}</span>
              <span
                v-if="repo.node_paths.length"
                class="mt-0.5 block truncate text-xs text-muted-foreground"
              >{{ repo.node_paths.join(' · ') }}</span>
            </span>
          </RouterLink>
        </div>

        <div v-if="forward.capabilities.length" class="space-y-2">
          <h3 class="text-xs font-semibold text-muted-foreground">
            {{ t('knowledge.entity.associations.capabilities') }}
          </h3>
          <div class="flex flex-wrap gap-1.5">
            <Badge
              v-for="cap in forward.capabilities"
              :key="cap"
              variant="outline"
              :class="ARTIFACT_BADGE_CLASS"
              data-testid="assoc-capability-badge"
            >
              {{ cap }}
            </Badge>
          </div>
        </div>

        <div v-if="forward.keywords.length" class="space-y-2">
          <h3 class="text-xs font-semibold text-muted-foreground">
            {{ t('knowledge.entity.associations.keywords') }}
          </h3>
          <div class="flex flex-wrap gap-1.5">
            <Badge
              v-for="kw in forward.keywords"
              :key="kw"
              variant="secondary"
              data-testid="assoc-keyword-badge"
            >
              {{ kw }}
            </Badge>
          </div>
        </div>
      </div>

      <!-- 反向：仓库 → 相关交付文档 -->
      <div v-else-if="isReverse" class="space-y-2">
        <h3 class="text-xs font-semibold text-muted-foreground">
          {{ t('knowledge.entity.associations.relatedDocs') }}
        </h3>
        <RouterLink
          v-for="doc in reverseDocs"
          :key="doc.artifact_id"
          :to="`/knowledge/entities/${doc.entity_id}`"
          class="flex items-start gap-2 rounded border border-border/60 p-2.5 hover:bg-muted/30"
          data-testid="assoc-doc-link"
        >
          <span :class="carrierIcon(doc.carrier)" class="mt-0.5 shrink-0 text-muted-foreground" />
          <span class="min-w-0 flex-1">
            <span class="flex items-center gap-2">
              <Badge
                variant="outline"
                :class="ARTIFACT_BADGE_CLASS"
                class="shrink-0"
                data-testid="assoc-doc-type-badge"
              >
                {{ doc.type_name || doc.type_key }}
              </Badge>
              <span class="truncate text-sm font-medium hover:text-primary">{{ doc.title }}</span>
            </span>
            <span
              v-if="doc.project_name"
              class="mt-0.5 flex items-center gap-1 text-xs text-muted-foreground"
            >
              <span class="icon-[lucide--folder] text-[11px]" />
              <span class="truncate">{{ doc.project_name }}</span>
            </span>
          </span>
        </RouterLink>
      </div>
    </template>
  </div>
</template>
