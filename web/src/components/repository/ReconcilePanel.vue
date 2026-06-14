<script setup lang="ts">
import type { CleanupMode } from '~/api/reconcile'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { reconcileApi } from '~/api/reconcile'
import { useConfirmDialog } from '~/composables/useConfirmDialog'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

const props = defineProps<{
  repositoryId: string
}>()

const { t } = useI18n()
const { confirm } = useConfirmDialog()
const { handleError } = useErrorHandler()
const { success } = useToast()
const queryClient = useQueryClient()

const reconcileKey = computed(() => ['repository-reconcile', props.repositoryId])
const statusKey = computed(() => ['repository-cleanup-status', props.repositoryId])

// ==================== 对账（GET /reconcile/） ====================
const { data: report, isLoading, isError } = useQuery({
  queryKey: reconcileKey,
  queryFn: () => reconcileApi.getReconcile(props.repositoryId),
})

// degraded：匹配器构造失败 → 对账不可信（W3）。此时不渲染空态/已一致，且禁用清理。
const degraded = computed(() => report.value?.degraded === true)
const matchCount = computed(() => report.value?.match_count ?? 0)
const excludedPaths = computed(() => report.value?.excluded_paths ?? [])
// 仅当「非 degraded 且 match_count==0」才视为差异归零空态。
const showEmpty = computed(() => !degraded.value && matchCount.value === 0)
const hasDiff = computed(() => !degraded.value && matchCount.value > 0)

// 列表只展示前若干条，其余折叠计数（避免大仓刷屏）。
const MAX_PATHS = 50
const visiblePaths = computed(() => excludedPaths.value.slice(0, MAX_PATHS))
const hiddenPathCount = computed(() => Math.max(0, excludedPaths.value.length - MAX_PATHS))

// ==================== 清理派发（POST /reconcile/） ====================
// 派发后开启状态轮询：清理后台异步执行，前端经 status 端点拉取真实结果（W1/W2）。
const statusEnabled = ref(false)

const cleanupMutation = useMutation({
  mutationFn: (mode: CleanupMode) => reconcileApi.cleanup(props.repositoryId, mode),
})
const isCleaning = computed(() => cleanupMutation.isPending.value)
const cleanupDisabled = computed(() => degraded.value || isCleaning.value)

// ==================== 清理状态回显（GET /reconcile/status/） ====================
const { data: cleanupRun, isError: isStatusError } = useQuery({
  queryKey: statusKey,
  queryFn: () => reconcileApi.getCleanupStatus(props.repositoryId),
  enabled: statusEnabled,
  // status=running 持续轮询；完成/失败/无记录停止。
  refetchInterval: query => (query.state.data?.status === 'running' ? 2000 : false),
})

const cleanupStatus = computed(() => cleanupRun.value?.status ?? 'none')
const showStatus = computed(() => statusEnabled.value && cleanupStatus.value !== 'none')
// 敏感清理结果：哪些面已清/未清(unscrubbed) + caveat，来自后端真实结果（非静态文案，W1/W2）。
const sensitiveResult = computed(() => cleanupRun.value?.sensitive ?? null)
const unscrubbedPlanes = computed(() => sensitiveResult.value?.unscrubbed ?? [])
const caveat = computed(() => sensitiveResult.value?.caveat ?? '')
const cleanupFailures = computed(() => cleanupRun.value?.failures ?? [])

async function runCleanup(mode: CleanupMode) {
  // degraded 时对账不可信，不应据此清理（W3）。
  if (degraded.value)
    return

  const opts = mode === 'sensitive'
    ? {
        title: t('reconcile.sensitiveConfirm.title'),
        description: t('reconcile.sensitiveConfirm.description'),
        confirmText: t('reconcile.sensitiveConfirm.confirmText'),
        variant: 'destructive' as const,
      }
    : {
        title: t('reconcile.normalConfirm.title'),
        description: t('reconcile.normalConfirm.description'),
        confirmText: t('reconcile.normalConfirm.confirmText'),
        variant: 'destructive' as const,
      }

  const ok = await confirm(opts)
  if (!ok)
    return

  try {
    await cleanupMutation.mutateAsync(mode)
    success(t('reconcile.dispatched'))
    // 开启状态轮询 + 重查对账（派发后差异最终归零）。
    statusEnabled.value = true
    queryClient.invalidateQueries({ queryKey: statusKey.value })
    queryClient.invalidateQueries({ queryKey: reconcileKey.value })
  }
  catch (e) {
    handleError(e, t('reconcile.status.failed'))
  }
}
</script>

<template>
  <div class="card">
    <div class="px-5 py-3.5 border-b border-border/50">
      <div class="flex items-center gap-2">
        <span class="icon-[lucide--scale] text-primary" />
        <h3 class="text-sm font-semibold">
          {{ t('reconcile.title') }}
        </h3>
      </div>
      <p class="text-xs text-muted-foreground mt-0.5">
        {{ t('reconcile.subtitle') }}
      </p>
    </div>

    <div class="p-5 space-y-5">
      <div v-if="isLoading" class="text-xs text-muted-foreground">
        <span class="icon-[lucide--loader-circle] animate-spin mr-1.5" />
        {{ t('reconcile.loading') }}
      </div>
      <div v-else-if="isError" class="text-xs text-destructive">
        {{ t('reconcile.loadError') }}
      </div>

      <template v-else>
        <!-- degraded：对账不可信显式警示（W3，不渲染空态/已一致） -->
        <div
          v-if="degraded"
          class="flex items-start gap-2 text-xs text-destructive bg-destructive/10 border border-destructive/30 rounded-lg px-3 py-2.5"
        >
          <span class="icon-[lucide--shield-x] mt-0.5 shrink-0" />
          <span>{{ t('reconcile.degradedWarning') }}</span>
        </div>

        <!-- 对账差异（仅非 degraded 时） -->
        <template v-else>
          <!-- 空态：差异归零 -->
          <div v-if="showEmpty" class="flex items-center gap-2 text-xs text-emerald-600 dark:text-emerald-400">
            <span class="icon-[lucide--check-circle-2] shrink-0" />
            {{ t('reconcile.diff.empty') }}
          </div>

          <!-- 有差异：命中数 + 排除规则列表 -->
          <div v-else-if="hasDiff" class="space-y-2">
            <p class="text-sm font-medium text-amber-700 dark:text-amber-400">
              {{ t('reconcile.diff.matchCount', { count: matchCount }) }}
            </p>
            <div v-if="excludedPaths.length" class="space-y-1">
              <p class="text-xs text-muted-foreground">
                {{ t('reconcile.diff.excludedTitle') }}
              </p>
              <ul class="divide-y divide-border/40 rounded-lg border border-border/40 max-h-48 overflow-auto">
                <li
                  v-for="(p, i) in visiblePaths"
                  :key="`${i}:${p}`"
                  class="px-3 py-1.5"
                >
                  <code class="text-xs font-mono break-all">{{ p }}</code>
                </li>
              </ul>
              <p v-if="hiddenPathCount > 0" class="text-[10px] text-muted-foreground">
                {{ t('reconcile.diff.moreFiles', { count: hiddenPathCount }) }}
              </p>
            </div>
          </div>
        </template>

        <!-- 双清理入口（§9.2 不混一个按钮）：degraded 时禁用 -->
        <div class="flex flex-wrap items-center gap-2 pt-1">
          <button
            class="inline-flex items-center gap-1.5 text-xs px-3 py-2 rounded-lg border border-border/50 hover:bg-muted/50 transition-colors disabled:opacity-50 shrink-0"
            :disabled="cleanupDisabled"
            @click="runCleanup('normal')"
          >
            <span v-if="isCleaning" class="icon-[lucide--loader-circle] animate-spin" />
            <span v-else class="icon-[lucide--eraser]" />
            {{ isCleaning ? t('reconcile.actions.cleaning') : t('reconcile.actions.cleanupNormal') }}
          </button>
          <!-- 敏感清理：视觉更醒目危险色 + 更强确认 -->
          <button
            class="inline-flex items-center gap-1.5 text-xs px-3 py-2 rounded-lg border border-destructive/40 text-destructive hover:bg-destructive/10 transition-colors disabled:opacity-50 shrink-0"
            :disabled="cleanupDisabled"
            @click="runCleanup('sensitive')"
          >
            <span class="icon-[lucide--shield-alert]" />
            {{ t('reconcile.actions.cleanupSensitive') }}
          </button>
        </div>

        <!-- 清理结果回显（派发后经 status 端点拉取真实 CleanupRun，W1/W2） -->
        <div v-if="showStatus" class="space-y-2 rounded-lg border border-border/40 px-3 py-3">
          <div class="flex items-center gap-2 text-sm font-medium">
            <span v-if="cleanupStatus === 'running'" class="icon-[lucide--loader-circle] animate-spin text-primary" />
            <span v-else-if="cleanupStatus === 'completed'" class="icon-[lucide--check-circle-2] text-emerald-500" />
            <span v-else-if="cleanupStatus === 'failed'" class="icon-[lucide--alert-circle] text-destructive" />
            <span>{{ t('reconcile.status.title') }}</span>
          </div>
          <p class="text-xs" :class="cleanupStatus === 'failed' ? 'text-destructive' : 'text-muted-foreground'">
            <template v-if="cleanupStatus === 'running'">
              {{ t('reconcile.status.running') }}
            </template>
            <template v-else-if="cleanupStatus === 'completed'">
              {{ t('reconcile.status.completed') }}
            </template>
            <template v-else-if="cleanupStatus === 'failed'">
              {{ t('reconcile.status.failed') }}
            </template>
          </p>
          <p v-if="typeof cleanupRun?.match_count === 'number'" class="text-xs text-muted-foreground">
            {{ t('reconcile.status.matchCount', { count: cleanupRun.match_count }) }}
          </p>
          <p v-if="cleanupFailures.length" class="text-xs text-destructive">
            {{ t('reconcile.status.failures', { count: cleanupFailures.length }) }}
          </p>

          <!-- 敏感清理未清面（unscrubbed）+ caveat：来自后端真实结果，非静态文案 -->
          <div v-if="unscrubbedPlanes.length" class="space-y-1 pt-1">
            <p class="text-xs font-medium text-amber-700 dark:text-amber-400">
              {{ t('reconcile.status.unscrubbedTitle') }}
            </p>
            <ul class="list-disc list-inside text-xs text-muted-foreground">
              <li v-for="plane in unscrubbedPlanes" :key="plane">
                <code class="font-mono">{{ plane }}</code>
              </li>
            </ul>
          </div>
          <div v-if="caveat" class="flex items-start gap-2 text-xs text-amber-700 dark:text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">
            <span class="icon-[lucide--shield-alert] mt-0.5 shrink-0" />
            <span><span class="font-medium">{{ t('reconcile.status.caveatLabel') }}：</span>{{ caveat }}</span>
          </div>
          <p v-if="isStatusError" class="text-xs text-destructive">
            {{ t('reconcile.status.loadError') }}
          </p>
        </div>
      </template>
    </div>
  </div>
</template>
