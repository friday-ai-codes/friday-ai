<script setup lang="ts">
/**
 * 按仓调研明细抽屉：左选仓、右看「结论 + agent 过程」。
 *
 * 补的是 v0.21.0 LIVE-01/LIVE-03 的缺口 —— 事件流只有阶段级标量（`findings_count` /
 * `verdict`），看不到「哪个仓、得出什么结论、agent 一步步调了哪些工具读了哪些代码」。
 *
 * ⭐ **按需取数，⛔ 不进 5s 轮询**：载荷比事件流重一个量级（每仓每次运行最多 400 条
 * 日志正文），跟着 `useBlueprintLive` 轮询会把带宽和渲染都拖垮。`enabled` 绑定 `open`。
 *
 * 安全：所有正文一律 mustache / `<pre>` 插值，⛔ 不使用任何原始 HTML 注入指令；服务端
 * 已过 `redact_secrets_in_text`（工具结果里可能夹带被读文件中的凭证），前端只读直出。
 */
import type { BlueprintResearchRepo, BlueprintResearchRun, BlueprintRunLog } from '~/types/blueprint'
import { useQuery } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { getBlueprintResearchDetail } from '~/api/blueprints'
import { Badge } from '~/components/ui/badge'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '~/components/ui/sheet'
import { Skeleton } from '~/components/ui/skeleton'
import { extractErrorMessage } from '~/composables/useErrorHandler'

const props = defineProps<{
  open: boolean
  artifactId: string
  /** 打开时默认选中的仓；缺省选第一个。 */
  initialRepositoryId?: string
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
}>()

const { t } = useI18n()

const query = useQuery({
  queryKey: computed(() => ['blueprint', 'research-detail', props.artifactId]),
  queryFn: () => getBlueprintResearchDetail(props.artifactId),
  enabled: computed(() => props.open && !!props.artifactId),
  staleTime: 30_000,
})

const repositories = computed<BlueprintResearchRepo[]>(
  () => query.data.value?.repositories ?? [],
)

const activeRepoId = ref('')

/** 打开时定位到调用方指定的仓；该仓不在结果里（或没指定）则退到第一个。 */
watch(
  [() => props.open, repositories],
  ([open, repos]) => {
    if (!open || !repos.length)
      return
    const wanted = props.initialRepositoryId
    const hit = wanted && repos.some(repo => repo.repository_id === wanted) ? wanted : ''
    if (!activeRepoId.value || !repos.some(repo => repo.repository_id === activeRepoId.value))
      activeRepoId.value = hit || repos[0].repository_id
  },
  { immediate: true },
)

const activeRepo = computed<BlueprintResearchRepo | null>(
  () => repositories.value.find(repo => repo.repository_id === activeRepoId.value) ?? null,
)

/**
 * 结论里的 findings。`conclusion` 是 `PartialPlan.content`，键由产出侧自定、schema 层
 * 零保证 ⇒ 逐层 `Array.isArray` 防御，⛔ 不直接下标。
 */
const findings = computed<Array<Record<string, unknown>>>(() => {
  const raw = activeRepo.value?.conclusion?.findings
  return Array.isArray(raw) ? (raw as Array<Record<string, unknown>>) : []
})

const verdict = computed(() => {
  const fitness = activeRepo.value?.conclusion?.fitness
  if (!fitness || typeof fitness !== 'object')
    return ''
  return String((fitness as Record<string, unknown>).verdict ?? '')
})

const roleSuggestion = computed(() => String(activeRepo.value?.conclusion?.role_suggestion ?? ''))

const researchSummary = computed(() => String(activeRepo.value?.conclusion?.research_summary ?? ''))

/**
 * 阶段二分仓方案（RepoPlan）：`conclusion.repo_plan`。仅在 `repo_plan` 阶段跑过后才有；
 * 键由产出侧自定、schema 层零保证 ⇒ 逐层 `Array.isArray` / `typeof` 防御，⛔ 不直接下标。
 */
const repoPlan = computed<Record<string, unknown> | null>(() => {
  const raw = activeRepo.value?.conclusion?.repo_plan
  return raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : null
})

const implItems = computed<Array<Record<string, unknown>>>(() => {
  const raw = repoPlan.value?.impl_items
  return Array.isArray(raw) ? (raw as Array<Record<string, unknown>>) : []
})

const apisProvided = computed<Array<Record<string, unknown>>>(() => {
  const raw = repoPlan.value?.apis_provided
  return Array.isArray(raw) ? (raw as Array<Record<string, unknown>>) : []
})

const apisConsumed = computed<Array<Record<string, unknown>>>(() => {
  const raw = repoPlan.value?.apis_consumed
  return Array.isArray(raw) ? (raw as Array<Record<string, unknown>>) : []
})

const hasRepoPlan = computed(
  () => implItems.value.length > 0 || apisProvided.value.length > 0 || apisConsumed.value.length > 0,
)

/** 变更类型 → 中文标签；未知类型原样透出（⛔ 不隐藏）。 */
const CHANGE_LABELS: Record<string, string> = {
  create: '新建',
  modify: '改动',
  remove: '删除',
  indirect_refine: '间接完善',
}

function changeLabel(value: unknown): string {
  const key = String(value ?? '')
  return CHANGE_LABELS[key] ?? key
}

/** RepoPlan how 字段是 block[] 或字符串；取首块可读文本，拆不出返空串。 */
function implHow(item: Record<string, unknown>): string {
  const how = item.how
  if (typeof how === 'string')
    return how
  if (Array.isArray(how)) {
    const first = how.find(block => block && typeof block === 'object') as Record<string, unknown> | undefined
    const text = first?.text
    if (typeof text === 'string')
      return text
    if (Array.isArray(text))
      return text.map(String).join('；')
  }
  return ''
}

function endpointOf(api: Record<string, unknown>): string {
  return `${String(api.method ?? '')} ${String(api.path ?? api.name ?? '')}`.trim()
}

function consumedSource(api: Record<string, unknown>): string {
  const ds = api.data_source
  if (!ds || typeof ds !== 'object')
    return ''
  const source = String((ds as Record<string, unknown>).from_service ?? '')
  const availability = String((ds as Record<string, unknown>).availability ?? '')
  return [source, availability].filter(Boolean).join(' · ')
}

/** 只渲染有日志的运行：0 条的那些是派发后立刻失败的重试，列出来只有噪音。 */
const runs = computed<BlueprintResearchRun[]>(
  () => (activeRepo.value?.runs ?? []).filter(run => run.logs.length > 0),
)

/** 日志类型 → 徽标样式。未知类型落 `muted`（⛔ 不隐藏，新类型要能透出来）。 */
const LOG_VARIANT: Record<string, 'info' | 'warning' | 'destructive' | 'secondary' | 'muted'> = {
  tool_call: 'info',
  tool_result: 'secondary',
  error: 'destructive',
  result: 'warning',
}

function logVariant(type: string): 'info' | 'warning' | 'destructive' | 'secondary' | 'muted' {
  return LOG_VARIANT[type] ?? 'muted'
}

function logLabel(type: string): string {
  const key = `knowledge.blueprints.research.logType.${type}`
  const label = t(key)
  return label === key ? type : label
}

function stageLabel(stage: string): string {
  const key = `knowledge.blueprints.research.stage.${stage}`
  const label = t(key)
  return label === key ? stage : label
}

/**
 * finding 有**两种形态**且都在线上：阶段一 `PartialPlan` 存的是 `{title, detail, citations}`，
 * 分仓阶段投影到正文的 `current_state_analysis` 用的是 `{id, kind, topic, text}`。
 * ⛔ 只认一种会让另一种整条渲染成空白（实测阶段一那批就是这么空掉的）。
 */
function findingTitle(finding: Record<string, unknown>): string {
  return String(finding.title ?? finding.topic ?? finding.id ?? '')
}

function findingText(finding: Record<string, unknown>): string {
  return String(finding.detail ?? finding.text ?? finding.summary ?? '')
}

function formatTime(iso: string): string {
  if (!iso)
    return ''
  const date = new Date(iso)
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleTimeString('zh-CN', { hour12: false })
}

/**
 * 工具调用行拆成「工具名 + 入参」。容器侧格式是 `工具名({json})`；拆不开就整行当正文，
 * ⛔ 不吞。
 */
function splitToolCall(log: BlueprintRunLog): { name: string, args: string } {
  const match = /^([\w-]+)\((.*)\)$/s.exec(log.content)
  return match ? { name: match[1], args: match[2] } : { name: '', args: log.content }
}

function findingCountOf(repo: BlueprintResearchRepo): number {
  const raw = repo.conclusion?.findings
  return Array.isArray(raw) ? raw.length : 0
}

function setOpen(value: boolean): void {
  emit('update:open', value)
}
</script>

<template>
  <Sheet :open="open" @update:open="setOpen">
    <SheetContent side="right" class="flex w-full flex-col gap-0 p-0 sm:max-w-3xl" data-testid="blueprint-research-drawer">
      <SheetHeader class="border-b border-border/60 p-4">
        <SheetTitle>{{ t('knowledge.blueprints.research.title') }}</SheetTitle>
        <SheetDescription>{{ t('knowledge.blueprints.research.description') }}</SheetDescription>
      </SheetHeader>

      <div v-if="query.isPending.value" class="space-y-2 p-4">
        <Skeleton v-for="i in 4" :key="i" class="h-14 w-full" />
      </div>

      <p
        v-else-if="query.isError.value"
        class="p-4 text-sm text-destructive"
        data-testid="blueprint-research-error"
      >
        {{ extractErrorMessage(query.error.value) }}
      </p>

      <p
        v-else-if="!repositories.length"
        class="p-4 text-sm text-muted-foreground"
        data-testid="blueprint-research-empty"
      >
        {{ t('knowledge.blueprints.research.empty') }}
      </p>

      <div v-else class="flex min-h-0 flex-1">
        <!-- 左：仓库列表（每仓一行，带 findings 计数） -->
        <nav class="w-52 shrink-0 overflow-y-auto border-r border-border/60 p-2" data-testid="blueprint-research-repos">
          <button
            v-for="repo in repositories"
            :key="repo.repository_id"
            type="button"
            class="mb-1 w-full rounded-lg px-2.5 py-2 text-left transition-colors"
            :class="repo.repository_id === activeRepoId ? 'bg-muted text-foreground' : 'text-muted-foreground hover:bg-muted/50'"
            data-testid="blueprint-research-repo"
            :data-repository-id="repo.repository_id"
            @click="activeRepoId = repo.repository_id"
          >
            <span class="block break-all text-[13px] font-medium">{{ repo.repository_name || repo.repository_id }}</span>
            <span class="mt-0.5 block text-[11px] text-muted-foreground">
              {{ t('knowledge.blueprints.research.findingCount', { n: findingCountOf(repo) }) }}
            </span>
          </button>
        </nav>

        <!-- 右：该仓的结论 + 逐次运行的过程 -->
        <div v-if="activeRepo" class="min-w-0 flex-1 space-y-4 overflow-y-auto p-4" data-testid="blueprint-research-detail">
          <section>
            <div class="flex flex-wrap items-center gap-1.5">
              <h3 class="text-sm font-medium text-foreground">
                {{ activeRepo.repository_name || activeRepo.repository_id }}
              </h3>
              <Badge v-if="verdict" variant="info">
                {{ verdict }}
              </Badge>
              <Badge v-if="roleSuggestion" variant="muted">
                {{ roleSuggestion }}
              </Badge>
              <Badge variant="muted">
                {{ activeRepo.status }}
              </Badge>
            </div>
            <p v-if="researchSummary" class="mt-2 whitespace-pre-wrap text-[13px] leading-6 text-foreground/90">
              {{ researchSummary }}
            </p>
          </section>

          <section v-if="findings.length" data-testid="blueprint-research-findings">
            <h4 class="mb-1.5 text-sm font-medium text-muted-foreground">
              {{ t('knowledge.blueprints.research.findingsTitle') }}
            </h4>
            <ul class="space-y-1.5">
              <li
                v-for="(finding, index) in findings"
                :key="String(finding.id ?? index)"
                class="rounded-lg border border-border/60 p-2.5 text-[13px] leading-6"
              >
                <div class="mb-0.5 flex flex-wrap items-baseline gap-1.5">
                  <span v-if="findingTitle(finding)" class="text-[13px] font-medium text-foreground">
                    {{ findingTitle(finding) }}
                  </span>
                  <Badge v-if="finding.kind" variant="muted">
                    {{ finding.kind }}
                  </Badge>
                  <span class="ml-auto text-[11px] text-muted-foreground/60">#{{ index + 1 }}</span>
                </div>
                <p class="whitespace-pre-wrap text-foreground/90">
                  {{ findingText(finding) }}
                </p>
              </li>
            </ul>
          </section>

          <section v-if="hasRepoPlan" data-testid="blueprint-research-repo-plan">
            <h4 class="mb-1.5 text-sm font-medium text-muted-foreground">
              {{ t('knowledge.blueprints.research.repoPlanTitle') }}
            </h4>

            <ul v-if="implItems.length" class="space-y-1.5">
              <li
                v-for="(item, index) in implItems"
                :key="String(item.item_id ?? index)"
                class="rounded-lg border border-border/60 p-2.5 text-[13px] leading-6"
                data-testid="blueprint-research-impl-item"
              >
                <div class="mb-0.5 flex flex-wrap items-baseline gap-1.5">
                  <Badge v-if="item.change_type" variant="info">
                    {{ changeLabel(item.change_type) }}
                  </Badge>
                  <span class="text-[13px] font-medium text-foreground">{{ item.title }}</span>
                  <span class="ml-auto text-[11px] text-muted-foreground/60">#{{ index + 1 }}</span>
                </div>
                <p v-if="implHow(item)" class="whitespace-pre-wrap text-foreground/90">
                  {{ implHow(item) }}
                </p>
                <p
                  v-if="Array.isArray(item.files_touched) && item.files_touched.length"
                  class="mt-0.5 text-[12px] text-muted-foreground"
                >
                  {{ t('knowledge.blueprints.research.filesTouched') }}：{{ (item.files_touched as unknown[]).map(String).join('、') }}
                </p>
              </li>
            </ul>

            <div v-if="apisProvided.length || apisConsumed.length" class="mt-2 space-y-1.5">
              <div
                v-for="(api, index) in apisProvided"
                :key="`p-${index}`"
                class="rounded-md border border-border/50 px-2.5 py-1.5 text-[12px] leading-6"
                data-testid="blueprint-research-api-provided"
              >
                <Badge variant="secondary" class="font-normal">
                  {{ t('knowledge.blueprints.research.apiProvided') }}
                </Badge>
                <code class="ml-1.5 text-[12px] text-foreground">{{ endpointOf(api) }}</code>
              </div>
              <div
                v-for="(api, index) in apisConsumed"
                :key="`c-${index}`"
                class="rounded-md border border-border/50 px-2.5 py-1.5 text-[12px] leading-6"
                data-testid="blueprint-research-api-consumed"
              >
                <Badge variant="muted" class="font-normal">
                  {{ t('knowledge.blueprints.research.apiConsumed') }}
                </Badge>
                <code class="ml-1.5 text-[12px] text-foreground">{{ endpointOf(api) }}</code>
                <span v-if="consumedSource(api)" class="ml-1.5 text-[11px] text-muted-foreground">{{ consumedSource(api) }}</span>
              </div>
            </div>
          </section>

          <section v-for="run in runs" :key="run.session_id" data-testid="blueprint-research-run">
            <div class="mb-1.5 flex flex-wrap items-center gap-1.5">
              <h4 class="text-sm font-medium text-muted-foreground">
                {{ stageLabel(run.stage) }}
              </h4>
              <Badge variant="muted">
                {{ run.status }}
              </Badge>
              <span class="text-[11px] text-muted-foreground/70">{{ formatTime(run.started_at) }}</span>
              <code class="ml-auto text-[11px] text-muted-foreground/60">{{ run.session_id }}</code>
            </div>

            <!-- ⭐ 存量会话只剩尾窗 80 条：不标出来会被误读成「agent 只做了这几步」 -->
            <p
              v-if="run.logs_truncated_tail"
              class="mb-1.5 rounded-md bg-muted/50 px-2 py-1 text-[11px] text-muted-foreground"
              data-testid="blueprint-research-truncated"
            >
              {{ t('knowledge.blueprints.research.truncatedTail') }}
            </p>

            <ol class="space-y-1">
              <li
                v-for="(log, index) in run.logs"
                :key="index"
                class="rounded-md border border-border/50 px-2.5 py-1.5 text-[12px] leading-6"
                data-testid="blueprint-research-log"
                :data-log-type="log.type"
              >
                <div class="flex flex-wrap items-baseline gap-1.5">
                  <Badge :variant="logVariant(log.type)" class="font-normal">
                    {{ logLabel(log.type) }}
                  </Badge>
                  <code v-if="log.type === 'tool_call' && splitToolCall(log).name" class="text-[11px] text-foreground">
                    {{ splitToolCall(log).name }}
                  </code>
                  <span class="ml-auto text-[11px] tabular-nums text-muted-foreground/60">{{ formatTime(log.ts) }}</span>
                </div>
                <pre class="mt-0.5 whitespace-pre-wrap break-words font-mono text-[11px] leading-5 text-muted-foreground">{{ log.type === 'tool_call' ? splitToolCall(log).args : log.content }}</pre>
              </li>
            </ol>
          </section>

          <p v-if="!runs.length" class="text-sm text-muted-foreground" data-testid="blueprint-research-no-runs">
            {{ t('knowledge.blueprints.research.noRuns') }}
          </p>
        </div>
      </div>
    </SheetContent>
  </Sheet>
</template>
