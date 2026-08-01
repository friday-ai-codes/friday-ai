<script setup lang="ts">
/**
 * 仓库关联段（Phase 115-05，UI-SPEC §6.1 段 1）。
 *
 * **职责**：`lg:grid-cols-2` 网格渲染 N 张 `RepoAssociationCard`，并把 blockCtx 五个 prop
 * 原样透传下去；⛔ 段组件内不自行处理批注与引用（UI-SPEC §13.3）。
 *
 * **分工边界（P-4）**：`<section id="repo_associations">` 容器与左栏导航项由页面（115-06）
 * **无条件渲染**（mount-only 的 IntersectionObserver 观察不到后渲染的容器）。本组件只决定
 * 段内出不出内容 —— 空数据时出 `CompactEmptyState`，而不是整段消失。
 *
 * 段头 badge 的 direct/indirect 分色 tone 归导航层（115-06），本组件只出内容。
 */

import type { SelectionPayload } from '../BlueprintBlockList.vue'
import type { BlueprintRepoAssociation, BlueprintThreadDetail, Citation } from '~/types/blueprint'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'
import RepoAssociationCard from '../RepoAssociationCard.vue'

const props = withDefaults(defineProps<{
  associations?: BlueprintRepoAssociation[]
  /** 页面解析出的 `{repository_id: 仓名}`（缺省时卡片回落条目自带的 `repository_name`）。 */
  repoNames?: Record<string, string>
  /** —— 以下五项是 blockCtx，原样透传给 `BlueprintBlockList` —— */
  threads?: BlueprintThreadDetail[]
  citations?: Record<string, Citation>
  readonly?: boolean
  activeThreadId?: string | null
  showClosed?: boolean
}>(), {
  associations: () => [],
  repoNames: () => ({}),
  threads: () => [],
  citations: () => ({}),
  readonly: false,
  activeThreadId: null,
  showClosed: false,
})

const emit = defineEmits<{
  'thread-click': [threadId: string, allThreadIds: string[]]
  'citation-click': [citationId: string]
  'selection-comment': [payload: SelectionPayload]
  'cross-block-selection': []
}>()

const { t } = useI18n()

const items = computed(() => props.associations ?? [])

function repoNameOf(repositoryId: string): string {
  return props.repoNames?.[repositoryId] ?? ''
}

function forwardThread(threadId: string, allThreadIds: string[]): void {
  emit('thread-click', threadId, allThreadIds)
}
</script>

<template>
  <div data-testid="blueprint-repo-associations">
    <CompactEmptyState
      v-if="!items.length"
      icon="lucide--folder-git-2"
      :title="t('knowledge.blueprints.repo.empty')"
    />

    <div v-else class="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <RepoAssociationCard
        v-for="association in items"
        :key="association.repository_id"
        :association="association"
        :repo-name="repoNameOf(association.repository_id)"
        :threads="threads"
        :citations="citations"
        :readonly="readonly"
        :active-thread-id="activeThreadId"
        :show-closed="showClosed"
        @thread-click="forwardThread"
        @citation-click="emit('citation-click', $event)"
        @selection-comment="emit('selection-comment', $event)"
        @cross-block-selection="emit('cross-block-selection')"
      />
    </div>
  </div>
</template>
