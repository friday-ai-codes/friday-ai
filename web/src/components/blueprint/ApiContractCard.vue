<script setup lang="ts">
/**
 * API 契约卡（Phase 115-05，UI-SPEC §6.6 逐行实现）。
 *
 * **职责**：把 `api_contracts[]` 的一条排版成一张卡；`description` 与 `data_source.notes`
 * 交给 `BlueprintBlockList`，⛔ 卡内不自行处理批注与引用（UI-SPEC §13.3）。
 *
 * ⭐ **`availability` 与 `support_repository_id` 只从 `contract.data_source` 内读，⛔ 不得回落
 * 读顶层**（113-05 决策：这两个键在顶层零残留）。理由是对称防线 —— 后端哪天把它们写错位置写
 * 到顶层，回落读顶层的 UI 会照常显示「数据已有」，评审人据此放行，缺陷被静默掩盖（T-115-42）。
 * 只从 `data_source` 读，读不到就渲染「未标注」，错误位置立刻可见。
 *
 * **`method` 单色**：`GET`/`POST`/`PUT`/`DELETE`/`PATCH` **不按动词分色**（`web/DESIGN.md` 禁彩虹）。
 *
 * **跨段跳转的目标锚点**：卡根挂 `id="api-<契约 id>"`，供交互流程段的 `api_ref` chip
 * emit 的 `goto-anchor('api-<id>')` 命中（滚动与偏移由页面统一处理）。
 *
 * ⚠️ **i18n 缺口（按 §13.2 回报而不自补）**：`availability` 读不到时的「未标注」无键 ⇒ 降级
 * 复用 `quality.noData`（暂无数据），身份由 `data-availability="unknown"` 承载。
 */

import type { SelectionPayload } from './BlueprintBlockList.vue'
import type { BlueprintApiContract, BlueprintThreadDetail, Citation } from '~/types/blueprint'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Badge } from '~/components/ui/badge'
import BlueprintBlockList from './BlueprintBlockList.vue'

const props = withDefaults(defineProps<{
  contract: BlueprintApiContract
  repoName?: string
  /** `data_source.support_repository_id` 对应的仓名（由页面解析后传入）。 */
  supportRepoName?: string
  /** —— 以下五项是 blockCtx，原样透传给 `BlueprintBlockList` —— */
  threads?: BlueprintThreadDetail[]
  citations?: Record<string, Citation>
  readonly?: boolean
  activeThreadId?: string | null
  showClosed?: boolean
}>(), {
  repoName: '',
  supportRepoName: '',
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

/** 示例超过该行数即折叠（UI-SPEC §6.6）。 */
const EXAMPLE_FOLD_LINES = 20

const DIRECTION_META: Record<string, { variant: 'default' | 'secondary', labelKey: string }> = {
  provided: { variant: 'default', labelKey: 'directionProvided' },
  consumed: { variant: 'secondary', labelKey: 'directionConsumed' },
}

const directionMeta = computed(() => DIRECTION_META[props.contract.direction] ?? null)

const descriptionBlocks = computed(() => props.contract.description ?? [])

/** ⭐ 只从 `data_source` 内读，⛔ 无顶层回落分支。 */
const dataSource = computed(() => props.contract.data_source ?? null)
const availability = computed(() => dataSource.value?.availability ?? '')
const supportRepositoryId = computed(() => dataSource.value?.support_repository_id ?? '')
const dataSourceNotes = computed(() => dataSource.value?.notes ?? [])
const fieldsNeeded = computed(() => dataSource.value?.fields_needed ?? [])

const availabilityMeta = computed(() => {
  if (availability.value === 'existing')
    return { variant: 'success' as const, labelKey: 'availabilityExisting', state: 'existing' }
  if (availability.value === 'needs_support')
    return { variant: 'warning' as const, labelKey: 'availabilityNeedsSupport', state: 'needs_support' }
  return null
})

const hasDataSource = computed(() =>
  Boolean(
    dataSource.value
    && (dataSource.value.from_service
      || dataSource.value.from_api
      || fieldsNeeded.value.length
      || availability.value
      || dataSourceNotes.value.length),
  ),
)

function stringifyExample(example: Record<string, unknown> | undefined): string {
  if (!example)
    return ''
  try {
    return JSON.stringify(example, null, 2)
  }
  catch {
    // 循环引用等异常一律退化为空（⛔ 不把异常抛给渲染层）。
    return ''
  }
}

const requestText = computed(() => stringifyExample(props.contract.request_example))
const responseText = computed(() => stringifyExample(props.contract.response_example))

const requestExpanded = ref(false)
const responseExpanded = ref(false)

function lineCount(text: string): number {
  return text ? text.split('\n').length : 0
}

function clamp(text: string, expanded: boolean): string {
  if (expanded || lineCount(text) <= EXAMPLE_FOLD_LINES)
    return text
  return text.split('\n').slice(0, EXAMPLE_FOLD_LINES).join('\n')
}

const requestFoldable = computed(() => lineCount(requestText.value) > EXAMPLE_FOLD_LINES)
const responseFoldable = computed(() => lineCount(responseText.value) > EXAMPLE_FOLD_LINES)

const requestShown = computed(() => clamp(requestText.value, requestExpanded.value))
const responseShown = computed(() => clamp(responseText.value, responseExpanded.value))

const consumers = computed(() => props.contract.consumers ?? [])

function forwardThread(threadId: string, allThreadIds: string[]): void {
  emit('thread-click', threadId, allThreadIds)
}
</script>

<template>
  <div
    :id="`api-${contract.id}`"
    class="card space-y-3 p-4"
    data-testid="blueprint-api-card"
    :data-direction="contract.direction"
    :data-contract-id="contract.id"
  >
    <div class="flex flex-wrap items-center gap-2">
      <Badge v-if="directionMeta" :variant="directionMeta.variant">
        {{ t(`knowledge.blueprints.api.${directionMeta.labelKey}`) }}
      </Badge>
      <Badge v-else variant="outline">
        {{ contract.direction }}
      </Badge>

      <Badge variant="outline" class="font-mono lowercase">
        {{ contract.kind }}
      </Badge>

      <!-- method 单色 mono（⛔ 不按动词分色） -->
      <span v-if="contract.method" class="rounded-md border border-border bg-muted/60 px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">
        {{ contract.method }}
      </span>

      <span v-if="contract.path" class="min-w-0 flex-1 truncate font-mono text-xs">{{ contract.path }}</span>
      <span v-else class="min-w-0 flex-1 truncate text-sm font-semibold">{{ contract.name }}</span>

      <span v-if="repoName || contract.repository_id" class="shrink-0 text-[11px] text-muted-foreground">
        {{ repoName || contract.repository_id }}
      </span>
    </div>

    <div v-if="descriptionBlocks.length" data-field="description">
      <BlueprintBlockList
        :blocks="descriptionBlocks"
        :section-path="`api_contracts[${contract.id}].description`"
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

    <!-- 请求 / 响应示例：JSON.stringify 进 <pre>（禁任何原始 HTML 注入指令） -->
    <div v-if="requestText || responseText" class="grid grid-cols-1 gap-3 lg:grid-cols-2">
      <div v-if="requestText" data-field="request-example">
        <p class="mb-1 text-xs font-medium text-muted-foreground">
          {{ t('knowledge.blueprints.api.request') }}
        </p>
        <pre class="overflow-auto rounded-lg bg-muted/40 p-2 font-mono text-xs" data-testid="blueprint-api-request">{{ requestShown }}</pre>
        <button
          v-if="requestFoldable"
          type="button"
          class="mt-1 text-xs text-primary hover:underline"
          data-testid="blueprint-api-request-toggle"
          @click="requestExpanded = !requestExpanded"
        >
          {{ requestExpanded ? t('knowledge.blueprints.block.collapse') : t('knowledge.blueprints.block.expandAll') }}
        </button>
      </div>

      <div v-if="responseText" data-field="response-example">
        <p class="mb-1 text-xs font-medium text-muted-foreground">
          {{ t('knowledge.blueprints.api.response') }}
        </p>
        <pre class="overflow-auto rounded-lg bg-muted/40 p-2 font-mono text-xs" data-testid="blueprint-api-response">{{ responseShown }}</pre>
        <button
          v-if="responseFoldable"
          type="button"
          class="mt-1 text-xs text-primary hover:underline"
          data-testid="blueprint-api-response-toggle"
          @click="responseExpanded = !responseExpanded"
        >
          {{ responseExpanded ? t('knowledge.blueprints.block.collapse') : t('knowledge.blueprints.block.expandAll') }}
        </button>
      </div>
    </div>

    <!-- 数据来源分区（consumed 专属） -->
    <div v-if="hasDataSource" class="space-y-2 rounded-lg border border-border/60 p-3" data-field="data-source" data-testid="blueprint-api-data-source">
      <p class="text-xs font-medium text-muted-foreground">
        {{ t('knowledge.blueprints.api.dataSource') }}
      </p>

      <p v-if="dataSource?.from_service || dataSource?.from_api" class="font-mono text-[11px] text-muted-foreground">
        {{ t('knowledge.blueprints.api.dataSourceFrom', { name: dataSource?.from_service || dataSource?.from_api }) }}
      </p>

      <div v-if="fieldsNeeded.length" class="flex flex-wrap items-center gap-1">
        <span class="text-[11px] text-muted-foreground">{{ t('knowledge.blueprints.api.fieldsNeeded') }}</span>
        <span
          v-for="field in fieldsNeeded"
          :key="field"
          class="rounded-md border border-border bg-muted/60 px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground"
        >{{ field }}</span>
      </div>

      <div class="flex flex-wrap items-center gap-2">
        <Badge
          v-if="availabilityMeta"
          :variant="availabilityMeta.variant"
          :data-availability="availabilityMeta.state"
          data-testid="blueprint-api-availability"
        >
          {{ t(`knowledge.blueprints.api.${availabilityMeta.labelKey}`) }}
        </Badge>
        <Badge
          v-else
          variant="muted"
          data-availability="unknown"
          data-testid="blueprint-api-availability"
        >
          {{ t('knowledge.blueprints.quality.noData') }}
        </Badge>

        <RouterLink
          v-if="availabilityMeta?.state === 'needs_support' && supportRepositoryId"
          :to="`/repositories/${supportRepositoryId}`"
          class="inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-primary"
          data-testid="blueprint-api-support-repo"
        >
          <span class="icon-[lucide--external-link]" aria-hidden="true" />
          <span>{{ supportRepoName || supportRepositoryId }}</span>
        </RouterLink>
      </div>

      <BlueprintBlockList
        v-if="dataSourceNotes.length"
        :blocks="dataSourceNotes"
        :section-path="`api_contracts[${contract.id}].data_source.notes`"
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

    <div v-if="consumers.length" class="flex flex-wrap items-center gap-1">
      <span class="text-[11px] text-muted-foreground">{{ t('knowledge.blueprints.api.consumers') }}</span>
      <span
        v-for="consumer in consumers"
        :key="consumer"
        class="rounded-md border border-border bg-muted/60 px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground"
      >{{ consumer }}</span>
    </div>
  </div>
</template>
