<script setup lang="ts">
import type { StepStatus } from '~/api/ingest'
import type { ReleaseBitableRow } from '~/api/releaseBitable'
import { useMutation, useQuery } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ingestApi } from '~/api/ingest'
import { releaseBitableApi } from '~/api/releaseBitable'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'
import { Button } from '~/components/ui/button'
import { Checkbox } from '~/components/ui/checkbox'
import { Skeleton } from '~/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '~/components/ui/table'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

const { t } = useI18n()
const { handleError } = useErrorHandler()
const { success } = useToast()

const PAGE_SIZE = 50

// ==================== 预览（分页累积） ====================
const rows = ref<ReleaseBitableRow[]>([])
const pageToken = ref<string | null>(null)
const hasMore = ref(false)
const total = ref<number | null>(null)
const hasLoaded = ref(false)
const loading = ref(false)
const loadError = ref<string | null>(null)

async function loadPage(reset = false) {
  loading.value = true
  loadError.value = null
  try {
    const res = await releaseBitableApi.preview({
      page_token: reset ? undefined : pageToken.value ?? undefined,
      page_size: PAGE_SIZE,
    })
    if (reset)
      rows.value = []
    rows.value.push(...res.rows)
    pageToken.value = res.page_token
    hasMore.value = res.has_more
    total.value = res.total
    hasLoaded.value = true
  }
  catch (e: any) {
    loadError.value = e?.detail || e?.message || t('release.loadError')
  }
  finally {
    loading.value = false
  }
}

// ==================== 勾选（跨页保持，按 record_id） ====================
const selectedIds = ref<Set<string>>(new Set())

function isSelectable(row: ReleaseBitableRow): boolean {
  return Boolean(row.mr_url)
}

function isSelected(id: string): boolean {
  return selectedIds.value.has(id)
}

function toggleRow(row: ReleaseBitableRow, val: boolean) {
  const next = new Set(selectedIds.value)
  if (val)
    next.add(row.record_id)
  else next.delete(row.record_id)
  selectedIds.value = next
}

const selectableRows = computed(() => rows.value.filter(isSelectable))
const allPageSelected = computed(() =>
  selectableRows.value.length > 0
  && selectableRows.value.every(r => selectedIds.value.has(r.record_id)),
)
const selectedCount = computed(() => selectedIds.value.size)

function toggleAll(val: boolean) {
  const next = new Set(selectedIds.value)
  for (const r of selectableRows.value) {
    if (val)
      next.add(r.record_id)
    else next.delete(r.record_id)
  }
  selectedIds.value = next
}

function clearSelection() {
  selectedIds.value = new Set()
}

function formatDate(ms: number | null): string {
  if (!ms)
    return '—'
  const d = new Date(ms)
  if (Number.isNaN(d.getTime()))
    return '—'
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

// ==================== 批量同步派发 ====================
interface RunMeta { business: string, kanban_id: number | null, mr_url: string }
const batchId = ref<string | null>(null)
const runMeta = ref<Record<string, RunMeta>>({})

const syncMutation = useMutation({
  mutationFn: (chosen: ReleaseBitableRow[]) => releaseBitableApi.sync(chosen),
})
const isSyncing = computed(() => syncMutation.isPending.value)

async function startSync() {
  const chosen = rows.value.filter(r => selectedIds.value.has(r.record_id))
  if (!chosen.length)
    return
  try {
    const res = await syncMutation.mutateAsync(chosen)
    batchId.value = res.batch_id
    runMeta.value = Object.fromEntries(
      res.runs.map(r => [r.run_id, { business: r.business, kanban_id: r.kanban_id, mr_url: r.mr_url }]),
    )
    clearSelection()
    success(t('release.dispatchSuccess', { count: chosen.length }))
  }
  catch (e) {
    handleError(e, t('release.dispatchFailed'))
  }
}

// ==================== 同步进度（复用批量状态端点） ====================
const POLL_TIMEOUT_MS = 10 * 60 * 1000
const pollStartedAt = ref<number | null>(null)
const batchQuery = useQuery({
  queryKey: computed(() => ['release-batch', batchId.value]),
  queryFn: () => ingestApi.getBatch(batchId.value as string),
  enabled: computed(() => !!batchId.value),
  refetchInterval: (query) => {
    if (query.state.data?.status !== 'running')
      return false
    if (pollStartedAt.value !== null && Date.now() - pollStartedAt.value > POLL_TIMEOUT_MS)
      return false
    return 2500
  },
})

// 派发后记录轮询起点
function markPollStart() {
  pollStartedAt.value = Date.now()
}

const batch = computed(() => batchQuery.data.value ?? null)
const progressRuns = computed(() => batch.value?.runs ?? [])
const okCount = computed(() =>
  progressRuns.value.filter((r: any) => r.status === 'completed' && r.steps?.release?.status === 'ok').length,
)

function stepStatus(run: any, key: 'release' | 'mr_diff'): StepStatus {
  return (run.steps?.[key]?.status ?? 'pending') as StepStatus
}

function statusIcon(status: StepStatus): string {
  switch (status) {
    case 'ok': return 'icon-[lucide--check-circle-2] text-emerald-600 dark:text-emerald-400'
    case 'failed': return 'icon-[lucide--alert-circle] text-destructive'
    case 'skipped': return 'icon-[lucide--minus-circle] text-amber-700 dark:text-amber-400'
    default: return 'icon-[lucide--circle-dashed] text-muted-foreground'
  }
}

function statusText(status: StepStatus): string {
  return t(`ingest.status.${status}`)
}

// 监听 batchId 变化设置轮询起点
watch(batchId, (v) => {
  if (v)
    markPollStart()
})
</script>

<template>
  <div class="space-y-5">
    <!-- ==================== 顶部说明 + 加载 ==================== -->
    <div class="card">
      <div class="px-5 py-3.5 border-b border-border/50 flex items-start justify-between gap-3 flex-wrap">
        <div>
          <div class="flex items-center gap-2">
            <span class="icon-[lucide--cloud-download] text-primary" />
            <h3 class="text-sm font-semibold">
              {{ t('release.title') }}
            </h3>
          </div>
          <p class="text-xs text-muted-foreground mt-0.5">
            {{ t('release.subtitle') }}
          </p>
        </div>
        <Button
          v-if="hasLoaded"
          variant="outline"
          size="sm"
          class="h-8 shrink-0"
          :disabled="loading"
          @click="loadPage(true)"
        >
          <span class="icon-[lucide--refresh-cw] mr-1.5" :class="{ 'animate-spin': loading }" />
          {{ t('release.reload') }}
        </Button>
      </div>

      <div class="p-5">
        <!-- 未加载：空态 + 加载按钮 -->
        <div v-if="!hasLoaded && !loading" class="flex min-h-[260px] flex-col items-center justify-center gap-4">
          <CompactEmptyState
            icon="icon-[lucide--table-2]"
            :title="t('release.empty.title')"
            :description="t('release.empty.body')"
          />
          <Button :disabled="loading" @click="loadPage(true)">
            <span class="icon-[lucide--cloud-download] mr-1.5" />
            {{ t('release.load') }}
          </Button>
        </div>

        <!-- 首次加载骨架 -->
        <div v-else-if="!hasLoaded && loading" class="space-y-2">
          <Skeleton v-for="n in 6" :key="n" class="h-10 w-full rounded-lg" />
        </div>

        <!-- 加载失败 -->
        <div v-else-if="loadError && !rows.length" class="flex min-h-[200px] flex-col items-center justify-center gap-3">
          <p class="text-sm text-destructive">
            {{ loadError }}
          </p>
          <Button variant="outline" size="sm" @click="loadPage(true)">
            <span class="icon-[lucide--refresh-cw] mr-1.5" />
            {{ t('release.reload') }}
          </Button>
        </div>

        <!-- 已加载：表格 -->
        <div v-else>
          <CompactEmptyState
            v-if="!rows.length"
            icon="icon-[lucide--file-x]"
            :title="t('release.noRows.title')"
            :description="t('release.noRows.body')"
          />

          <template v-else>
            <!-- skill: 表格用 overflow-x-auto 包裹，避免移动端撑破 -->
            <div class="overflow-x-auto rounded-xl border border-border/50">
              <Table>
                <TableHeader>
                  <TableRow class="bg-muted/40 hover:bg-muted/40">
                    <TableHead class="w-10">
                      <Checkbox
                        :model-value="allPageSelected"
                        :aria-label="t('release.table.selectAll')"
                        @update:model-value="(v: boolean | 'indeterminate') => toggleAll(v === true)"
                      />
                    </TableHead>
                    <TableHead>{{ t('release.table.business') }}</TableHead>
                    <TableHead>{{ t('release.table.mr') }}</TableHead>
                    <TableHead>{{ t('release.table.kanban') }}</TableHead>
                    <TableHead>{{ t('release.table.category') }}</TableHead>
                    <TableHead>{{ t('release.table.date') }}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <TableRow
                    v-for="row in rows"
                    :key="row.record_id"
                    class="transition-colors"
                    :class="isSelected(row.record_id) ? 'bg-primary/5' : ''"
                  >
                    <TableCell>
                      <Checkbox
                        :model-value="isSelected(row.record_id)"
                        :disabled="!isSelectable(row)"
                        :aria-label="row.business"
                        @update:model-value="(v: boolean | 'indeterminate') => toggleRow(row, v === true)"
                      />
                    </TableCell>
                    <TableCell class="font-medium max-w-[220px]">
                      <span class="line-clamp-2">{{ row.business || '—' }}</span>
                    </TableCell>
                    <TableCell class="max-w-[260px]">
                      <div v-if="row.mr_url" class="space-y-1">
                        <a
                          :href="row.mr_url"
                          target="_blank"
                          rel="noopener"
                          class="inline-flex items-center gap-1 text-xs text-primary hover:underline"
                        >
                          <span class="icon-[lucide--git-merge] shrink-0" />
                          <span class="truncate max-w-[200px]">{{ row.repo_name || row.mr_url }}</span>
                        </a>
                        <span
                          v-if="!row.repo_matched"
                          class="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-700 dark:text-amber-400 border border-amber-500/20"
                        >
                          <span class="icon-[lucide--alert-triangle]" />
                          {{ t('release.repoUnmatched') }}
                        </span>
                      </div>
                      <span v-else class="text-xs text-muted-foreground">{{ t('release.noMr') }}</span>
                    </TableCell>
                    <TableCell>
                      <div v-if="row.kanban_id" class="flex flex-col">
                        <span class="font-mono text-xs">{{ row.kanban_id }}</span>
                        <span v-if="row.kanban_source === 'feature分支'" class="text-[10px] text-muted-foreground">{{ t('release.fromBranch') }}</span>
                      </div>
                      <span v-else class="text-xs text-muted-foreground">—</span>
                    </TableCell>
                    <TableCell>
                      <span v-if="row.category" class="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">{{ row.category }}</span>
                      <span v-else class="text-xs text-muted-foreground">—</span>
                    </TableCell>
                    <TableCell class="text-xs text-muted-foreground whitespace-nowrap">
                      {{ formatDate(row.release_date) }}
                    </TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </div>

            <!-- 计数 + 加载更多 -->
            <div class="flex items-center justify-between gap-3 mt-3">
              <p class="text-xs text-muted-foreground">
                {{ t('release.loadedCount', { loaded: rows.length }) }}
                <template v-if="total != null">
                  / {{ t('release.ofTotal', { total }) }}
                </template>
              </p>
              <Button
                v-if="hasMore"
                variant="outline"
                size="sm"
                class="h-8"
                :disabled="loading"
                @click="loadPage(false)"
              >
                <span v-if="loading" class="icon-[lucide--loader-circle] animate-spin mr-1.5" />
                <span v-else class="icon-[lucide--chevron-down] mr-1.5" />
                {{ t('release.loadMore') }}
              </Button>
            </div>
          </template>
        </div>
      </div>
    </div>

    <!-- ==================== 选择操作栏（skill: bulk action bar） ==================== -->
    <Transition
      enter-active-class="transition duration-200 ease-out"
      enter-from-class="opacity-0 translate-y-2"
      leave-active-class="transition duration-150 ease-in"
      leave-to-class="opacity-0 translate-y-2"
    >
      <div
        v-if="selectedCount > 0"
        class="sticky bottom-4 z-10 card border-primary/30 shadow-lg px-4 py-3 flex items-center justify-between gap-3"
      >
        <div class="flex items-center gap-3">
          <span class="text-sm font-medium">{{ t('release.selectedCount', { count: selectedCount }) }}</span>
          <button
            class="text-xs text-muted-foreground hover:text-foreground transition-colors"
            @click="clearSelection"
          >
            {{ t('release.clearSelection') }}
          </button>
        </div>
        <Button :disabled="isSyncing" @click="startSync">
          <span v-if="isSyncing" class="icon-[lucide--loader-circle] animate-spin mr-1.5" />
          <span v-else class="icon-[lucide--play] mr-1.5" />
          {{ isSyncing ? t('release.syncing') : t('release.startSync') }}
        </Button>
      </div>
    </Transition>

    <!-- ==================== 同步进度 ==================== -->
    <div v-if="batch" class="card" data-testid="release-sync-progress">
      <div class="px-5 py-3.5 border-b border-border/50">
        <div class="flex items-center gap-2 text-sm font-medium">
          <span v-if="batch.status === 'running'" class="icon-[lucide--loader-circle] animate-spin text-primary" />
          <span v-else class="icon-[lucide--check-circle-2] text-emerald-600 dark:text-emerald-400" />
          <span>
            <template v-if="batch.status === 'running'">{{ t('release.progress.overall', { ok: okCount, total: progressRuns.length }) }}</template>
            <template v-else>{{ t('release.progress.done', { ok: okCount, total: progressRuns.length }) }}</template>
          </span>
        </div>
      </div>
      <ul class="divide-y divide-border/40">
        <li v-for="run in progressRuns" :key="run.run_id" class="px-5 py-3 space-y-1.5">
          <div class="flex items-center justify-between gap-3 flex-wrap">
            <span class="text-sm font-medium truncate max-w-[60%]">
              {{ runMeta[run.run_id]?.business || run.mr_url }}
            </span>
            <div class="flex items-center gap-4 text-xs">
              <span class="inline-flex items-center gap-1">
                <span :class="statusIcon(stepStatus(run, 'release'))" />
                {{ t('release.progress.ledger') }} · {{ statusText(stepStatus(run, 'release')) }}
              </span>
              <span class="inline-flex items-center gap-1">
                <span :class="statusIcon(stepStatus(run, 'mr_diff'))" />
                {{ t('release.progress.knowledge') }} · {{ statusText(stepStatus(run, 'mr_diff')) }}
              </span>
            </div>
          </div>
        </li>
      </ul>
    </div>
  </div>
</template>
