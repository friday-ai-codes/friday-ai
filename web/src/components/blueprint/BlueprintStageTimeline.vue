<script setup lang="ts">
/**
 * 蓝图编排的八节点阶段时间线（Phase 115-06，UI-SPEC §8.4）。
 *
 * 视觉范式对齐 `~/components/repository/IndexProgressTimeline.vue`（`.card` → `px-5 py-3.5` 头
 * → `p-5` 体 → 分组 → 行内空态）。八个节点的顺序取自 115-02 的 `BLUEPRINT_STAGES`，
 * 事件到节点的归属取自同一模块的 `stageForEvent` —— ⛔ 本组件不另写一份映射表。
 *
 * ## 两条纪律
 *
 * 1. ⭐ **`payload` 只渲染标量**：它是自由 JSON 字段，schema 层**零保证**（P-8）。因此
 *    只渲染 `typeof` 为 `string` / `number` / `boolean` 的键值；对象与数组只列键名不展开，
 *    ⛔ 不把整包序列化糊到界面上（那既不可读，又可能把半可信长文本原样倒出来），
 *    ⛔ 也不因为缺任何一个键而抛错。
 * 2. ⛔ **不呈现「人审驳回导致的会话复位」**：该动作**当前没有对应的事件常量**
 *    （114-REVIEW 的可再议项）。凭空画一个节点等于谎报后端产出了它并不产出的事件；
 *    同步点 2 之后与 v0.19.0 的时间线契约一并定。
 */

import type { BlueprintEvent } from '~/types/blueprint'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Badge } from '~/components/ui/badge'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '~/components/ui/collapsible'
import { BLUEPRINT_STAGES, progressKeyForEvent, stageForEvent } from '~/utils/blueprintBlocks'

const props = withDefaults(defineProps<{
  events?: BlueprintEvent[]
  /** `blueprint/events/` 的 `current_stage`；用于在无事件时点亮当前节点。 */
  currentStage?: string
  /** 一律以人审快照的 `current_status` 为准。 */
  currentStatus?: string
}>(), {
  events: () => [],
  currentStage: '',
  currentStatus: '',
})

const { t, te } = useI18n()

type StageState = 'idle' | 'running' | 'done' | 'failed'

const STATE_VARIANT: Record<StageState, 'muted' | 'info' | 'success' | 'destructive'> = {
  idle: 'muted',
  running: 'info',
  done: 'success',
  failed: 'destructive',
}

interface ScalarField {
  key: string
  value: string
}

interface EventRow {
  id: string
  event: string
  label: string
  ts: string
  fields: ScalarField[]
  /** 被跳过的对象 / 数组键，只列键名。 */
  skippedKeys: string[]
}

interface StageNode {
  stage: string
  state: StageState
  label: string
  stateLabel: string
  events: EventRow[]
}

/** 四态 → i18n 键尾段（⛔ 不在模板里拼键名）。 */
const STATE_LABEL_KEY: Record<StageState, string> = {
  idle: 'stateIdle',
  running: 'stateRunning',
  done: 'stateDone',
  failed: 'stateFailed',
}

/** 事件中文名：带插值的进度键优先取它的无参兜底，缺映射时回落事件原名。 */
function eventLabel(event: BlueprintEvent): string {
  const key = progressKeyForEvent(event.event)
  if (!key)
    return event.event
  const generic = `${key}Generic`
  if (te(generic))
    return t(generic)
  return te(key) ? t(key, (event.payload ?? {}) as Record<string, unknown>) : event.event
}

/** ⭐ 只留标量：`typeof` 三档之外一律不渲染值。 */
function splitPayload(payload: Record<string, unknown> | undefined): {
  fields: ScalarField[]
  skippedKeys: string[]
} {
  const fields: ScalarField[] = []
  const skippedKeys: string[] = []
  for (const [key, value] of Object.entries(payload ?? {})) {
    const kind = typeof value
    if (kind === 'string' || kind === 'number' || kind === 'boolean')
      fields.push({ key, value: String(value) })
    else if (value !== null && value !== undefined)
      skippedKeys.push(key)
  }
  return { fields, skippedKeys }
}

function formatTime(raw: string): string {
  if (!raw)
    return ''
  const date = new Date(raw)
  return Number.isNaN(date.getTime()) ? raw : date.toLocaleString('zh-CN', { hour12: false })
}

const nodes = computed<StageNode[]>(() => {
  const buckets = new Map<string, BlueprintEvent[]>()
  for (const event of props.events ?? []) {
    const stage = stageForEvent(event.event)
    if (!stage)
      continue
    const list = buckets.get(stage) ?? []
    list.push(event)
    buckets.set(stage, list)
  }

  return BLUEPRINT_STAGES.map((stage) => {
    const list = [...(buckets.get(stage) ?? [])].sort((a, b) =>
      String(a.ts).localeCompare(String(b.ts)))
    const latest = list.at(-1)
    let state: StageState = 'idle'
    if (latest) {
      if (latest.event.endsWith('.failed'))
        state = 'failed'
      else if (latest.event.endsWith('.completed') || latest.event.endsWith('.locked'))
        state = 'done'
      else state = 'running'
    }
    else if (stage === props.currentStage) {
      state = 'running'
    }
    return {
      stage,
      state,
      label: t(`knowledge.blueprints.stage.${stage}`),
      stateLabel: t(`knowledge.blueprints.stage.${STATE_LABEL_KEY[state]}`),
      events: list.map((event) => {
        const { fields, skippedKeys } = splitPayload(event.payload)
        return {
          id: event.id,
          event: event.event,
          label: eventLabel(event),
          ts: formatTime(event.ts),
          fields,
          skippedKeys,
        }
      }),
    }
  })
})

const hasAnyEvent = computed(() => nodes.value.some(node => node.events.length > 0))
</script>

<template>
  <div class="card" data-testid="blueprint-stage-timeline">
    <div class="flex items-center gap-2 border-b border-border/50 px-5 py-3.5">
      <span class="icon-[lucide--git-commit-horizontal] text-primary" />
      <h3 class="text-sm font-semibold">
        {{ t('knowledge.blueprints.stage.title') }}
      </h3>
    </div>

    <div class="p-5">
      <p v-if="!hasAnyEvent" class="flex items-center gap-2 text-sm text-muted-foreground">
        <span class="icon-[lucide--info]" />
        {{ t('knowledge.blueprints.stage.empty') }}
      </p>

      <ol v-else class="space-y-2">
        <li v-for="node in nodes" :key="node.stage" :data-stage="node.stage" :data-state="node.state">
          <Collapsible :disabled="node.events.length === 0">
            <CollapsibleTrigger
              class="flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-muted/40 disabled:cursor-default disabled:hover:bg-transparent"
              :disabled="node.events.length === 0"
            >
              <span
                v-if="node.state === 'running'"
                class="icon-[lucide--loader-2] shrink-0 animate-spin text-base"
              />
              <span v-else-if="node.state === 'done'" class="icon-[lucide--check-circle] shrink-0 text-base" />
              <span v-else-if="node.state === 'failed'" class="icon-[lucide--x-circle] shrink-0 text-base" />
              <span v-else class="icon-[lucide--circle] shrink-0 text-base opacity-40" />
              <span class="min-w-0 flex-1 truncate text-sm">{{ node.label }}</span>
              <Badge :variant="STATE_VARIANT[node.state]">
                {{ node.stateLabel }}
              </Badge>
              <span
                v-if="node.events.length"
                class="icon-[lucide--chevron-down] shrink-0 text-muted-foreground"
              />
            </CollapsibleTrigger>

            <CollapsibleContent>
              <ul class="mt-1 space-y-1.5 border-l border-border/60 pl-5">
                <li
                  v-for="row in node.events"
                  :key="row.id"
                  class="text-xs"
                  data-testid="blueprint-stage-event"
                  :data-event="row.event"
                >
                  <div class="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                    <span class="font-medium text-foreground">{{ row.label }}</span>
                    <span class="tabular-nums text-muted-foreground">{{ row.ts }}</span>
                  </div>
                  <dl v-if="row.fields.length" class="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-muted-foreground">
                    <div v-for="field in row.fields" :key="field.key" class="inline-flex gap-1">
                      <dt class="font-mono">
                        {{ field.key }}
                      </dt>
                      <dd class="break-all">
                        {{ field.value }}
                      </dd>
                    </div>
                  </dl>
                  <p v-if="row.skippedKeys.length" class="mt-0.5 font-mono text-[11px] text-muted-foreground/70">
                    {{ row.skippedKeys.join(' · ') }}
                  </p>
                </li>
              </ul>
            </CollapsibleContent>
          </Collapsible>
        </li>
      </ol>
    </div>
  </div>
</template>
