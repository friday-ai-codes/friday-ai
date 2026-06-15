<script setup lang="ts">
import type { IngestStep, StepStatus } from '~/api/ingest'
import { useMutation, useQuery } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ingestApi } from '~/api/ingest'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

const { t } = useI18n()
const { handleError } = useErrorHandler()
const { success } = useToast()

// ==================== 表单态（输入值与校验错误分离） ====================
const boardUrl = ref('')
const mrUrl = ref('')
const boardError = ref('')
const mrError = ref('')

/** 仅作 http(s) 字符串校验，真实解析交后端（前端不直连飞书/git）。 */
function validateUrl(value: string): string {
  const trimmed = value.trim()
  if (!trimmed)
    return t('ingest.form.errorRequired')
  if (!/^https?:\/\//i.test(trimmed))
    return t('ingest.form.errorInvalidUrl')
  return ''
}

function focusField(id: string) {
  const el = document.getElementById(id) as HTMLInputElement | null
  el?.focus()
}

// ==================== 轮询态 ====================
const runId = ref<string | null>(null)

// 后台派发 worker 若在置终态前夭折，run 会永驻 running → 轮询无限不停（IN-02）。
// 客户端兜底：自派发起累计轮询时长超上限即停轮并提示 timeout（reuse 错误渲染）。
const POLL_TIMEOUT_MS = 2 * 60 * 1000
const pollStartedAt = ref<number | null>(null)
const isPollTimeout = ref(false)

// ==================== 派发（POST /delivery/ingest/） ====================
const dispatchMutation = useMutation({
  mutationFn: () => ingestApi.dispatch(boardUrl.value.trim(), mrUrl.value.trim()),
})
const isDispatching = computed(() => dispatchMutation.isPending.value)

async function onSubmit() {
  boardError.value = validateUrl(boardUrl.value)
  mrError.value = validateUrl(mrUrl.value)
  if (boardError.value) {
    focusField('ingest-board-url')
    return
  }
  if (mrError.value) {
    focusField('ingest-mr-url')
    return
  }

  try {
    const res = await dispatchMutation.mutateAsync()
    isPollTimeout.value = false
    pollStartedAt.value = Date.now()
    runId.value = res.run_id
    success(t('ingest.dispatch.success'))
  }
  catch (e) {
    handleError(e, t('ingest.dispatch.failed'))
  }
}

// ==================== 状态回流（GET /delivery/ingest/{run_id}/） ====================
const runQuery = useQuery({
  queryKey: computed(() => ['ingest-run', runId.value]),
  queryFn: () => ingestApi.getRun(runId.value as string),
  enabled: computed(() => !!runId.value),
  // running 持续轮询；completed/failed 停轮（沿用 reconcile 范式）。
  // IN-02：running 但超出 POLL_TIMEOUT_MS（worker 夭折永驻 running）→ 停轮 + 置 timeout。
  refetchInterval: (query) => {
    if (query.state.data?.status !== 'running')
      return false
    if (pollStartedAt.value !== null && Date.now() - pollStartedAt.value > POLL_TIMEOUT_MS) {
      isPollTimeout.value = true
      return false
    }
    return 2000
  },
})

const run = computed(() => runQuery.data.value ?? null)
const isRunError = computed(() => runQuery.isError.value)

/** 固定三步顺序：工作项 → 文档 → MR diff（始终渲染，保证可预期布局）。 */
const stepRows = computed(() => {
  const steps = run.value?.steps
  return [
    { key: 'work_item', label: t('ingest.steps.workItem'), step: steps?.work_item },
    { key: 'document', label: t('ingest.steps.document'), step: steps?.document },
    { key: 'mr_diff', label: t('ingest.steps.mrDiff'), step: steps?.mr_diff },
  ] as const
})

const isCompleted = computed(() => run.value?.status === 'completed')
const allOk = computed(() =>
  isCompleted.value
  && stepRows.value.every(r => r.step?.status === 'ok'),
)
const isPartial = computed(() =>
  isCompleted.value
  && stepRows.value.some(r => r.step && r.step.status !== 'ok'),
)

/** 单步状态文案（i18n `ingest.status.*`）；pending 兜底。 */
function statusLabel(status?: StepStatus): string {
  return t(`ingest.status.${status ?? 'pending'}`)
}

/** 状态语义色文字类（状态不仅靠颜色——并列有文字，WCAG 1.4.1）。 */
function statusTextClass(status?: StepStatus): string {
  switch (status) {
    case 'ok':
      return 'text-emerald-600 dark:text-emerald-400'
    case 'failed':
      return 'text-destructive'
    case 'skipped':
      return 'text-amber-700 dark:text-amber-400'
    default:
      return 'text-muted-foreground'
  }
}

/** 状态图标类（装饰性，语义由相邻文本承载）。 */
function statusIconClass(status?: StepStatus): string {
  switch (status) {
    case 'ok':
      return 'icon-[lucide--check-circle-2] text-emerald-600 dark:text-emerald-400'
    case 'failed':
      return 'icon-[lucide--alert-circle] text-destructive'
    case 'skipped':
      return 'icon-[lucide--minus-circle] text-amber-700 dark:text-amber-400'
    case 'pending':
    default:
      return 'icon-[lucide--circle-dashed] text-muted-foreground'
  }
}

/** failed/skipped 且有 error 时展示原因。 */
function showError(step?: IngestStep): boolean {
  return !!step?.error && (step.status === 'failed' || step.status === 'skipped')
}
</script>

<template>
  <div class="space-y-8">
    <!-- ==================== 表单卡片 ==================== -->
    <div class="card">
      <div class="px-5 py-3.5 border-b border-border/50">
        <div class="flex items-center gap-2">
          <span class="icon-[lucide--download] text-primary" />
          <h3 class="text-sm font-semibold">
            {{ t('ingest.title') }}
          </h3>
        </div>
        <p class="text-xs text-muted-foreground mt-0.5">
          {{ t('ingest.subtitle') }}
        </p>
      </div>

      <form class="p-5 space-y-4" @submit.prevent="onSubmit">
        <div class="space-y-1.5">
          <Label for="ingest-board-url">{{ t('ingest.form.boardUrlLabel') }}</Label>
          <Input
            id="ingest-board-url"
            v-model="boardUrl"
            data-testid="ingest-board-url"
            :placeholder="t('ingest.form.boardUrlPlaceholder')"
            :aria-invalid="!!boardError"
          />
          <p v-if="boardError" class="text-xs text-destructive">
            {{ boardError }}
          </p>
        </div>

        <div class="space-y-1.5">
          <Label for="ingest-mr-url">{{ t('ingest.form.mrUrlLabel') }}</Label>
          <Input
            id="ingest-mr-url"
            v-model="mrUrl"
            data-testid="ingest-mr-url"
            :placeholder="t('ingest.form.mrUrlPlaceholder')"
            :aria-invalid="!!mrError"
          />
          <p v-if="mrError" class="text-xs text-destructive">
            {{ mrError }}
          </p>
        </div>

        <Button
          type="submit"
          class="w-full sm:w-auto"
          data-testid="ingest-submit"
          :disabled="isDispatching"
        >
          <span v-if="isDispatching" class="icon-[lucide--loader-circle] animate-spin mr-1.5" />
          {{ isDispatching ? t('ingest.form.submitting') : t('ingest.form.submit') }}
        </Button>
      </form>
    </div>

    <!-- ==================== 结果区 / 空态 ==================== -->
    <div aria-live="polite">
      <!-- getRun 失败：错误行，不清空已有结果 -->
      <p v-if="isRunError" class="text-xs text-destructive mb-3" data-testid="ingest-load-error">
        {{ t('ingest.run.loadError') }}
      </p>

      <!-- 无 run：空态 -->
      <CompactEmptyState
        v-if="!runId"
        icon="lucide--inbox"
        :title="t('ingest.empty.title')"
        :description="t('ingest.empty.body')"
      />

      <!-- 有 run：结果卡片 -->
      <div v-else-if="run" class="card p-5 space-y-4" data-testid="ingest-results">
        <!-- 顶部 run 状态行 -->
        <div class="space-y-1.5">
          <div class="flex items-center gap-2 text-sm font-medium">
            <span v-if="run.status === 'running' && isPollTimeout" class="icon-[lucide--alert-circle] text-destructive" aria-hidden="true" />
            <span v-else-if="run.status === 'running'" class="icon-[lucide--loader-circle] animate-spin text-primary" aria-hidden="true" />
            <span v-else-if="allOk" class="icon-[lucide--check-circle-2] text-emerald-600 dark:text-emerald-400" aria-hidden="true" />
            <span v-else-if="run.status === 'failed'" class="icon-[lucide--alert-circle] text-destructive" aria-hidden="true" />
            <span v-else class="icon-[lucide--alert-triangle] text-amber-700 dark:text-amber-400" aria-hidden="true" />
            <span :class="{ 'text-destructive': run.status === 'running' && isPollTimeout }">
              <template v-if="run.status === 'running' && isPollTimeout">{{ t('ingest.run.timeout') }}</template>
              <template v-else-if="run.status === 'running'">{{ t('ingest.run.running') }}</template>
              <template v-else-if="allOk">{{ t('ingest.run.completed') }}</template>
              <template v-else-if="isPartial">{{ t('ingest.run.partial') }}</template>
              <template v-else-if="run.status === 'failed'">{{ t('ingest.run.failed') }}</template>
            </span>
          </div>
        </div>

        <!-- 固定三步结果 -->
        <ul class="space-y-3">
          <li
            v-for="row in stepRows"
            :key="row.key"
            class="flex items-start gap-2 flex-wrap"
            :data-testid="`ingest-step-${row.key}`"
          >
            <span class="mt-0.5 shrink-0" :class="statusIconClass(row.step?.status)" />
            <div class="min-w-0 space-y-0.5">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="text-sm font-medium">{{ row.label }}</span>
                <span class="text-xs" :class="statusTextClass(row.step?.status)">
                  {{ statusLabel(row.step?.status) }}
                </span>
              </div>
              <code v-if="row.step?.identifier" class="block text-xs font-mono break-all text-muted-foreground">
                {{ row.step.identifier }}
              </code>
              <a
                v-if="row.step?.link"
                :href="row.step.link"
                target="_blank"
                rel="noopener"
                class="inline-flex items-center gap-1 text-xs text-primary hover:underline"
              >
                <span class="icon-[lucide--external-link]" />
                {{ t('ingest.run.viewLink') }}
              </a>
              <p v-if="showError(row.step)" class="text-xs text-destructive break-words">
                {{ row.step?.error }}
              </p>
            </div>
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>
