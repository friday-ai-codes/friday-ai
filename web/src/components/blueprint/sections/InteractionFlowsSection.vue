<script setup lang="ts">
/**
 * 交互流程段（Phase 115-05，UI-SPEC §6.1 段 6 / §6.8）。
 *
 * **职责**：每条 flow 一张卡 —— 卡头（`name` + `trigger`）→ 时序图 → 步骤表 → 备选路径。
 * `steps[].note` 是 Block[]，交给 `BlueprintBlockList`；⛔ 段组件内不自行处理批注与引用。
 *
 * ⭐ **时序图经「前端合成块」交给 `BlueprintBlockList` 渲染，⛔ 本段不直接引入图表组件**：
 * 115-03 的 `BlueprintBlock` 已经把三条契约实现好了（prop 名、空源码由调用方判空、预览弹层内
 * 退化为源码）。这里再直接接一次图表组件，就会出现第二套失败回退与主题逻辑。
 * ⚠️ 合成块的 `block_id` 由 `flow.id` 派生（`flow-<flow.id>-mermaid`）—— 它是**前端合成的**，
 * 后端 `iter_blocks` 不走查 `interaction_flows[].mermaid`，**不会有线程挂到它上面** ⇒
 * `threads` 恒传空数组，⛔ 不要把段级 threads 透给它（那会让批注按 block_id 错配）。
 * `flow.mermaid` 为空 ⇒ 不合成、不渲染该块（只显示步骤表）。
 *
 * ⭐ **跨段跳转一律 emit 给页面**：`api_ref` chip 点击 emit `goto-anchor('api-<契约 id>')`，
 * 落点是 `ApiContractCard` 根元素的 `id="api-<契约 id>"`；⛔ 段内不自行调用任何滚动 API。
 *
 * **分工边界（P-4）**：`<section id="interaction_flows">` 容器与导航项由页面无条件渲染。
 *
 * ⚠️ **i18n 缺口（按 §13.2 回报而不自补）**：`actor` 四档中文名与 `api_ref` 列头无键 ⇒ actor
 * 徽标渲染 schema 原样 token（颜色承载语义），`api_ref` 列头复用 `section.apiContracts`。
 */

import type { SelectionPayload } from '../BlueprintBlockList.vue'
import type {
  BlueprintBlock as BlueprintBlockModel,
  BlueprintFlowStep,
  BlueprintInteractionFlow,
  BlueprintThreadDetail,
  Citation,
} from '~/types/blueprint'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'
import { Badge } from '~/components/ui/badge'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '~/components/ui/collapsible'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '~/components/ui/table'
import BlueprintBlockList from '../BlueprintBlockList.vue'

const props = withDefaults(defineProps<{
  flows?: BlueprintInteractionFlow[]
  /** —— 以下五项是 blockCtx，原样透传给 `BlueprintBlockList` —— */
  threads?: BlueprintThreadDetail[]
  citations?: Record<string, Citation>
  readonly?: boolean
  activeThreadId?: string | null
  showClosed?: boolean
}>(), {
  flows: () => [],
  threads: () => [],
  citations: () => ({}),
  readonly: false,
  activeThreadId: null,
  showClosed: false,
})

const emit = defineEmits<{
  'goto-anchor': [domId: string]
  'thread-click': [threadId: string, allThreadIds: string[]]
  'citation-click': [citationId: string]
  'selection-comment': [payload: SelectionPayload]
  'cross-block-selection': []
}>()

const { t } = useI18n()

/** 步骤表列数（备注展开行 `colspan` 用）。 */
const STEP_COLUMN_COUNT = 7

/** `actor` 四档 → 徽标 variant；`service:*` 归 `outline`，未知值同样退 `outline`。 */
const ACTOR_VARIANT: Record<string, 'default' | 'info' | 'secondary'> = {
  user: 'default',
  frontend: 'info',
  backend: 'secondary',
}

interface NormalizedAlternativePath {
  key: string
  condition: string
  steps: BlueprintFlowStep[]
}

const items = computed(() => props.flows ?? [])

function actorVariant(actor: string): 'default' | 'info' | 'secondary' | 'outline' {
  return ACTOR_VARIANT[actor] ?? 'outline'
}

/** `actor` 四档 → 中文名；`service:*` 与未知值回落 schema 原样 token。 */
const ACTOR_LABEL_KEY: Record<string, string> = {
  user: 'actorUser',
  frontend: 'actorFrontend',
  backend: 'actorBackend',
  service: 'actorService',
}

function actorLabel(actor: string): string {
  const suffix = ACTOR_LABEL_KEY[actor]
  return suffix ? t(`knowledge.blueprints.flow.${suffix}`) : String(actor ?? '')
}

/**
 * ⭐ 前端合成的 mermaid 块（后端不会往它上面挂线程 ⇒ 调用点必须传空 `threads`）。
 * 空源码返回 `null`，由模板 `v-if` 判掉。
 */
function mermaidBlocks(flow: BlueprintInteractionFlow): BlueprintBlockModel[] {
  const source = typeof flow.mermaid === 'string' ? flow.mermaid.trim() : ''
  if (!source)
    return []
  return [{ block_id: `flow-${flow.id}-mermaid`, type: 'mermaid', text: source }]
}

/** `alternative_paths` 条目形状零约束 ⇒ 逐键收窄，缺键渲染「—」。 */
function alternativePaths(flow: BlueprintInteractionFlow): NormalizedAlternativePath[] {
  const list = flow.alternative_paths
  if (!Array.isArray(list))
    return []
  return list.map((raw, index) => {
    const item = (raw ?? {}) as Record<string, unknown>
    const steps = Array.isArray(item.steps) ? (item.steps as BlueprintFlowStep[]) : []
    return {
      key: `${flow.id}-alt-${index}`,
      condition: typeof item.condition === 'string' && item.condition ? item.condition : '—',
      steps,
    }
  })
}

function forwardThread(threadId: string, allThreadIds: string[]): void {
  emit('thread-click', threadId, allThreadIds)
}
</script>

<template>
  <div data-testid="blueprint-interaction-flows" class="space-y-4">
    <CompactEmptyState
      v-if="!items.length"
      icon="lucide--workflow"
      :title="t('knowledge.blueprints.flow.empty')"
    />

    <template v-else>
      <div
        v-for="flow in items"
        :key="flow.id"
        class="card space-y-3 p-4"
        data-testid="blueprint-flow-card"
        :data-flow-id="flow.id"
      >
        <div class="flex flex-wrap items-center gap-2">
          <h4 class="text-base font-semibold">
            {{ flow.name }}
          </h4>
          <span v-if="flow.trigger" class="inline-flex items-center gap-1 text-xs text-muted-foreground">
            <span class="icon-[lucide--mouse-pointer-click]" aria-hidden="true" />
            <span>{{ t('knowledge.blueprints.flow.trigger') }}: {{ flow.trigger }}</span>
          </span>
        </div>

        <!-- ⭐ 时序图：合成块交给 BlueprintBlockList，threads 恒空 -->
        <BlueprintBlockList
          v-if="mermaidBlocks(flow).length"
          :blocks="mermaidBlocks(flow)"
          :section-path="`interaction_flows[${flow.id}].mermaid`"
          :threads="[]"
          :citations="citations"
          :readonly="readonly"
          :active-thread-id="activeThreadId"
          :show-closed="showClosed"
          data-testid="blueprint-flow-diagram"
        />

        <Table v-if="flow.steps?.length">
          <TableHeader>
            <TableRow>
              <TableHead scope="col">
                {{ t('knowledge.blueprints.flow.seq') }}
              </TableHead>
              <TableHead scope="col">
                {{ t('knowledge.blueprints.flow.actor') }}
              </TableHead>
              <TableHead scope="col">
                {{ t('knowledge.blueprints.flow.action') }}
              </TableHead>
              <TableHead scope="col">
                {{ t('knowledge.blueprints.flow.component') }}
              </TableHead>
              <TableHead scope="col">
                {{ t('knowledge.blueprints.section.apiContracts') }}
              </TableHead>
              <TableHead scope="col">
                {{ t('knowledge.blueprints.flow.dataIn') }}
              </TableHead>
              <TableHead scope="col">
                {{ t('knowledge.blueprints.flow.dataOut') }}
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <template v-for="step in flow.steps" :key="`${flow.id}-${step.seq}`">
              <TableRow data-testid="blueprint-flow-step">
                <TableCell class="font-mono text-xs">
                  {{ step.seq }}
                </TableCell>
                <TableCell>
                  <Badge :variant="actorVariant(step.actor)" :data-actor="step.actor">
                    {{ actorLabel(step.actor) }}
                  </Badge>
                </TableCell>
                <TableCell class="text-sm">
                  {{ step.action }}
                </TableCell>
                <TableCell class="text-xs text-muted-foreground">
                  {{ step.component || '—' }}
                </TableCell>
                <TableCell>
                  <button
                    v-if="step.api_ref"
                    type="button"
                    class="rounded-md border border-border bg-muted/60 px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground hover:border-primary/40 hover:text-primary"
                    data-testid="blueprint-api-ref-chip"
                    @click="emit('goto-anchor', `api-${step.api_ref}`)"
                  >
                    {{ step.api_ref }}
                  </button>
                  <span v-else class="text-xs text-muted-foreground">—</span>
                </TableCell>
                <TableCell class="text-xs text-muted-foreground">
                  {{ step.data_in || '—' }}
                </TableCell>
                <TableCell class="text-xs text-muted-foreground">
                  {{ step.data_out || '—' }}
                </TableCell>
              </TableRow>

              <TableRow v-if="step.note?.length" data-testid="blueprint-flow-step-note">
                <TableCell :colspan="STEP_COLUMN_COUNT">
                  <Collapsible>
                    <CollapsibleTrigger class="flex items-center gap-1.5 rounded-lg py-1 text-xs font-medium text-muted-foreground hover:text-foreground">
                      <span class="icon-[lucide--chevron-right]" aria-hidden="true" />
                      <span>{{ t('knowledge.blueprints.flow.note') }}</span>
                    </CollapsibleTrigger>
                    <CollapsibleContent class="pt-1.5">
                      <BlueprintBlockList
                        :blocks="step.note"
                        :section-path="`interaction_flows[${flow.id}].steps[${step.seq}].note`"
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
                    </CollapsibleContent>
                  </Collapsible>
                </TableCell>
              </TableRow>
            </template>
          </TableBody>
        </Table>

        <Collapsible
          v-for="path in alternativePaths(flow)"
          :key="path.key"
          data-testid="blueprint-flow-alternative"
        >
          <CollapsibleTrigger class="flex w-full items-center gap-1.5 rounded-lg py-1 text-left text-xs font-medium text-muted-foreground hover:text-foreground">
            <span class="icon-[lucide--chevron-right]" aria-hidden="true" />
            <span>{{ t('knowledge.blueprints.flow.alternativePaths') }}: {{ path.condition }}</span>
          </CollapsibleTrigger>
          <CollapsibleContent class="pt-1.5">
            <Table v-if="path.steps.length">
              <TableHeader>
                <TableRow>
                  <TableHead scope="col">
                    {{ t('knowledge.blueprints.flow.seq') }}
                  </TableHead>
                  <TableHead scope="col">
                    {{ t('knowledge.blueprints.flow.actor') }}
                  </TableHead>
                  <TableHead scope="col">
                    {{ t('knowledge.blueprints.flow.action') }}
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow
                  v-for="(step, stepIndex) in path.steps"
                  :key="`${path.key}-${stepIndex}`"
                  data-testid="blueprint-flow-alt-step"
                >
                  <TableCell class="font-mono text-xs">
                    {{ step?.seq ?? '—' }}
                  </TableCell>
                  <TableCell>
                    <Badge :variant="actorVariant(step?.actor ?? '')" :data-actor="step?.actor ?? ''">
                      {{ step?.actor ? actorLabel(step.actor) : '—' }}
                    </Badge>
                  </TableCell>
                  <TableCell class="text-sm">
                    {{ step?.action ?? '—' }}
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </CollapsibleContent>
        </Collapsible>
      </div>
    </template>
  </div>
</template>
