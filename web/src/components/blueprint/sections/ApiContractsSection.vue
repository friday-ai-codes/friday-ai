<script setup lang="ts">
/**
 * API 契约段（Phase 115-05，UI-SPEC §6.1 段 4 / §6.6）。
 *
 * **职责**：`lg:grid-cols-2` 网格渲染 N 张 `ApiContractCard`，并把 blockCtx 五个 prop 原样
 * 透传下去；⛔ 段组件内不自行处理批注与引用（UI-SPEC §13.3）。
 *
 * **导航 badge 的 tone 不在这里算**：段头 badge「存在 `needs_support` 时 tone=warning」归
 * 115-06 的导航层自算（它已经持有整份 content）。本组件**不 expose** 派生值 —— 多一个
 * 出口就多一处会和导航层算不一致的地方。
 *
 * **分工边界（P-4）**：`<section id="api_contracts">` 容器与导航项由页面无条件渲染；
 * 本组件只决定段内出不出内容（空数据出 `CompactEmptyState`，而不是整段消失）。
 */

import type { SelectionPayload } from '../BlueprintBlockList.vue'
import type { BlueprintApiContract, BlueprintThreadDetail, Citation } from '~/types/blueprint'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'
import ApiContractCard from '../ApiContractCard.vue'

const props = withDefaults(defineProps<{
  contracts?: BlueprintApiContract[]
  repoNames?: Record<string, string>
  /** —— 以下五项是 blockCtx，原样透传给 `BlueprintBlockList` —— */
  threads?: BlueprintThreadDetail[]
  citations?: Record<string, Citation>
  readonly?: boolean
  activeThreadId?: string | null
  showClosed?: boolean
}>(), {
  contracts: () => [],
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

const items = computed(() => props.contracts ?? [])

function repoLabel(repositoryId: string | undefined): string {
  if (!repositoryId)
    return ''
  return props.repoNames?.[repositoryId] ?? ''
}

/** ⭐ 支持仓名同样只从 `data_source` 内取仓库 id 再查名（⛔ 不回落读顶层）。 */
function supportRepoLabel(contract: BlueprintApiContract): string {
  const repositoryId = contract.data_source?.support_repository_id
  return repositoryId ? (props.repoNames?.[repositoryId] ?? '') : ''
}

function forwardThread(threadId: string, allThreadIds: string[]): void {
  emit('thread-click', threadId, allThreadIds)
}
</script>

<template>
  <div data-testid="blueprint-api-contracts">
    <CompactEmptyState
      v-if="!items.length"
      icon="lucide--link"
      :title="t('knowledge.blueprints.api.empty')"
    />

    <div v-else class="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <ApiContractCard
        v-for="contract in items"
        :key="contract.id"
        :contract="contract"
        :repo-name="repoLabel(contract.repository_id)"
        :support-repo-name="supportRepoLabel(contract)"
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
