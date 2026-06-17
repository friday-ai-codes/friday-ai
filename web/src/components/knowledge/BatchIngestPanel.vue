<script setup lang="ts">
import type { IngestBatchRun, StepStatus } from '~/api/ingest'
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

// ==================== 多组表单态 ====================
interface RowForm {
  boardUrl: string
  mrUrl: string
  boardError: string
  mrError: string
}

function emptyRow(): RowForm {
  return { boardUrl: '', mrUrl: '', boardError: '', mrError: '' }
}

// 默认一组；用户可增删（批量摄取 = 1..N 组）
const rows = ref<RowForm[]>([emptyRow()])

const MAX_ROWS = 50

function addRow() {
  if (rows.value.length >= MAX_ROWS)
    return
  rows.value.push(emptyRow())
}

function removeRow(index: number) {
  if (rows.value.length <= 1)
    return
  rows.value.splice(index, 1)
}

/** 仅作 http(s) 字符串校验，真实解析交后端（前端不直连飞书/git）。 */
function validateUrl(value: string): string {
  const trimmed = value.trim()
  if (!trimmed)
    return t('ingest.form.errorRequired')
  if (!/^https?:\/\//i.test(trimmed))
    return t('ingest.form.errorInvalidUrl')
  return ''
}

// ==================== 轮询态 ====================
const batchId = ref<string | null>(null)
const POLL_TIMEOUT_MS = 5 * 60 * 1000
const pollStartedAt = ref<number | null>(null)
const isPollTimeout = ref(false)

// ==================== 派发（POST /delivery/ingest/batch/） ====================
const dispatchMutation = useMutation({
  mutationFn: (items: { board_url: string, mr_url: string }[]) =>
    ingestApi.dispatchBatch(items),
})
const isDispatching = computed(() => dispatchMutation.isPending.value)

async function onSubmit() {
  // 逐组校验，全部通过才派发（任一组非法 → 聚焦反馈，不派发）
  let firstInvalid: number | null = null
  rows.value.forEach((row, idx) => {
    row.boardError = validateUrl(row.boardUrl)
    row.mrError = validateUrl(row.mrUrl)
    if ((row.boardError || row.mrError) && firstInvalid === null)
      firstInvalid = idx
  })
  if (firstInvalid !== null)
    return

  const items = rows.value.map(r => ({
    board_url: r.boardUrl.trim(),
    mr_url: r.mrUrl.trim(),
  }))

  try {
    const res = await dispatchMutation.mutateAsync(items)
    isPollTimeout.value = false
    pollStartedAt.value = Date.now()
    batchId.value = res.batch_id
    success(t('ingest.batch.dispatchSuccess', { count: items.length }))
  }
  catch (e) {
    handleError(e, t('ingest.batch.dispatchFailed'))
  }
}

// ==================== 状态回流（GET /delivery/ingest/batch/{batch_id}/） ====================
const batchQuery = useQuery({
  queryKey: computed(() => ['ingest-batch', batchId.value]),
  queryFn: () => ingestApi.getBatch(batchId.value as string),
  enabled: computed(() => !!batchId.value),
  refetchInterval: (query) => {
    if (query.state.data?.status !== 'running')
      return false
    if (pollStartedAt.value !== null && Date.now() - pollStartedAt.value > POLL_TIMEOUT_MS) {
      isPollTimeout.value = true
      return false
    }
    return 2500
  },
})

const batch = computed(() => batchQuery.data.value ?? null)
const isBatchError = computed(() => batchQuery.isError.value)

/** 固定三步顺序：工作项 → 文档 → MR diff。 */
function stepRows(run: IngestBatchRun) {
  return [
    { key: 'work_item', label: t('ingest.steps.workItem'), step: run.steps?.work_item },
    { key: 'document', label: t('ingest.steps.document'), step: run.steps?.document },
    { key: 'mr_diff', label: t('ingest.steps.mrDiff'), step: run.steps?.mr_diff },
  ] as const
}

function runIsAllOk(run: IngestBatchRun): boolean {
  return run.status === 'completed'
    && (['work_item', 'document', 'mr_diff'] as const).every(k => run.steps?.[k]?.status === 'ok')
}

function runIsPartial(run: IngestBatchRun): boolean {
  return run.status === 'completed' && !runIsAllOk(run)
}

function statusLabel(status?: StepStatus): string {
  return t(`ingest.status.${status ?? 'pending'}`)
}

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

function statusIconClass(status?: StepStatus): string {
  switch (status) {
    case 'ok':
      return 'icon-[lucide--check-circle-2] text-emerald-600 dark:text-emerald-400'
    case 'failed':
      return 'icon-[lucide--alert-circle] text-destructive'
    case 'skipped':
      return 'icon-[lucide--minus-circle] text-amber-700 dark:text-amber-400'
    default:
      return 'icon-[lucide--circle-dashed] text-muted-foreground'
  }
}

function showError(status?: StepStatus, error?: string): boolean {
  return !!error && (status === 'failed' || status === 'skipped')
}

// ==================== 汇总计数 ====================
const okCount = computed(() => batch.value?.runs.filter(runIsAllOk).length ?? 0)
const totalCount = computed(() => batch.value?.runs.length ?? 0)
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
        <div
          v-for="(row, index) in rows"
          :key="index"
          class="rounded-lg border border-border/50 p-4 space-y-3 relative"
          :data-testid="`batch-ingest-row-${index}`"
        >
          <div class="flex items-center justify-between">
            <span class="text-xs font-medium text-muted-foreground">
              {{ t('ingest.batch.rowLabel', { n: index + 1 }) }}
            </span>
            <button
              v-if="rows.length > 1"
              type="button"
              class="p-1 rounded-lg hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors"
              :title="t('ingest.batch.removeRow')"
              @click="removeRow(index)"
            >
              <span class="icon-[lucide--trash-2] text-sm" />
            </button>
          </div>

          <div class="space-y-1.5">
            <Label :for="`batch-board-url-${index}`">{{ t('ingest.form.boardUrlLabel') }}</Label>
            <Input
              :id="`batch-board-url-${index}`"
              v-model="row.boardUrl"
              :data-testid="`batch-board-url-${index}`"
              :placeholder="t('ingest.form.boardUrlPlaceholder')"
              :aria-invalid="!!row.boardError"
            />
            <p v-if="row.boardError" class="text-xs text-destructive">
              {{ row.boardError }}
            </p>
          </div>

          <div class="space-y-1.5">
            <Label :for="`batch-mr-url-${index}`">{{ t('ingest.form.mrUrlLabel') }}</Label>
            <Input
              :id="`batch-mr-url-${index}`"
              v-model="row.mrUrl"
              :data-testid="`batch-mr-url-${index}`"
              :placeholder="t('ingest.form.mrUrlPlaceholder')"
              :aria-invalid="!!row.mrError"
            />
            <p v-if="row.mrError" class="text-xs text-destructive">
              {{ row.mrError }}
            </p>
          </div>
        </div>

        <div class="flex items-center gap-3 flex-wrap">
          <Button
            type="button"
            variant="outline"
            class="w-full sm:w-auto"
            data-testid="batch-add-row"
            :disabled="rows.length >= MAX_ROWS"
            @click="addRow"
          >
            <span class="icon-[lucide--plus] mr-1.5" />
            {{ t('ingest.batch.addRow') }}
          </Button>

          <Button
            type="submit"
            class="w-full sm:w-auto"
            data-testid="batch-ingest-submit"
            :disabled="isDispatching"
          >
            <span v-if="isDispatching" class="icon-[lucide--loader-circle] animate-spin mr-1.5" />
            {{ isDispatching ? t('ingest.batch.submitting') : t('ingest.batch.submit') }}
          </Button>
        </div>
      </form>
    </div>

    <!-- ==================== 结果区 / 空态 ==================== -->
    <div aria-live="polite">
      <p v-if="isBatchError" class="text-xs text-destructive mb-3" data-testid="batch-ingest-load-error">
        {{ t('ingest.batch.loadError') }}
      </p>

      <CompactEmptyState
        v-if="!batchId"
        icon="lucide--inbox"
        :title="t('ingest.batch.empty.title')"
        :description="t('ingest.batch.empty.body')"
      />

      <div v-else-if="batch" class="space-y-4" data-testid="batch-ingest-results">
        <!-- 批量总状态行 -->
        <div class="flex items-center gap-2 text-sm font-medium">
          <span v-if="batch.status === 'running' && isPollTimeout" class="icon-[lucide--alert-circle] text-destructive" aria-hidden="true" />
          <span v-else-if="batch.status === 'running'" class="icon-[lucide--loader-circle] animate-spin text-primary" aria-hidden="true" />
          <span v-else class="icon-[lucide--check-circle-2] text-emerald-600 dark:text-emerald-400" aria-hidden="true" />
          <span :class="{ 'text-destructive': batch.status === 'running' && isPollTimeout }">
            <template v-if="batch.status === 'running' && isPollTimeout">{{ t('ingest.run.timeout') }}</template>
            <template v-else-if="batch.status === 'running'">{{ t('ingest.batch.runningOverall', { ok: okCount, total: totalCount }) }}</template>
            <template v-else>{{ t('ingest.batch.completedOverall', { ok: okCount, total: totalCount }) }}</template>
          </span>
        </div>

        <!-- 每组结果卡片 -->
        <div
          v-for="(run, idx) in batch.runs"
          :key="run.run_id"
          class="card p-4 space-y-3"
          :data-testid="`batch-run-${idx}`"
        >
          <div class="flex items-center gap-2 text-sm font-medium">
            <span v-if="run.status === 'running'" class="icon-[lucide--loader-circle] animate-spin text-primary" aria-hidden="true" />
            <span v-else-if="runIsAllOk(run)" class="icon-[lucide--check-circle-2] text-emerald-600 dark:text-emerald-400" aria-hidden="true" />
            <span v-else-if="run.status === 'failed'" class="icon-[lucide--alert-circle] text-destructive" aria-hidden="true" />
            <span v-else-if="runIsPartial(run)" class="icon-[lucide--alert-triangle] text-amber-700 dark:text-amber-400" aria-hidden="true" />
            <span>{{ t('ingest.batch.rowLabel', { n: idx + 1 }) }}</span>
          </div>

          <code class="block text-xs font-mono break-all text-muted-foreground">{{ run.board_url }}</code>
          <code class="block text-xs font-mono break-all text-muted-foreground">{{ run.mr_url }}</code>

          <ul class="space-y-2.5 pt-1">
            <li
              v-for="srow in stepRows(run)"
              :key="srow.key"
              class="flex items-start gap-2 flex-wrap"
            >
              <span class="mt-0.5 shrink-0" :class="statusIconClass(srow.step?.status)" />
              <div class="min-w-0 space-y-0.5">
                <div class="flex items-center gap-2 flex-wrap">
                  <span class="text-sm">{{ srow.label }}</span>
                  <span class="text-xs" :class="statusTextClass(srow.step?.status)">
                    {{ statusLabel(srow.step?.status) }}
                  </span>
                </div>
                <a
                  v-if="srow.step?.link"
                  :href="srow.step.link"
                  target="_blank"
                  rel="noopener"
                  class="inline-flex items-center gap-1 text-xs text-primary hover:underline"
                >
                  <span class="icon-[lucide--external-link]" />
                  {{ t('ingest.run.viewLink') }}
                </a>
                <p v-if="showError(srow.step?.status, srow.step?.error)" class="text-xs text-destructive break-words">
                  {{ srow.step?.error }}
                </p>
              </div>
            </li>
          </ul>
        </div>
      </div>

      <!-- 派发成功但首轮状态未到：running 占位 -->
      <div
        v-else-if="!isBatchError"
        class="card p-5 flex items-center gap-2 text-sm font-medium"
        data-testid="batch-ingest-running-placeholder"
      >
        <span class="icon-[lucide--loader-circle] animate-spin text-primary" aria-hidden="true" />
        <span>{{ t('ingest.run.running') }}</span>
      </div>
    </div>
  </div>
</template>
