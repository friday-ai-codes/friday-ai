<script setup lang="ts">
import type { SensitiveSeverity, SensitiveSuggestion } from '~/api/sensitiveSuggestions'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { sensitiveSuggestionsApi } from '~/api/sensitiveSuggestions'
import { useConfirmDialog } from '~/composables/useConfirmDialog'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

const props = defineProps<{
  repoId: string
}>()

const { t } = useI18n()
const { confirm } = useConfirmDialog()
const { handleError } = useErrorHandler()
const { success } = useToast()
const queryClient = useQueryClient()

const queryKey = computed(() => ['repository-sensitive-suggestions', props.repoId])
// 接受会新建 ai_suggested 排除规则，需让排除规则面板即时显现。
const exclusionsKey = computed(() => ['repository-exclusions', props.repoId])

const { data, isLoading, isError } = useQuery({
  queryKey,
  queryFn: () => sensitiveSuggestionsApi.list(props.repoId),
})

// 后端已按 severity（real_secret > likely_sensitive > config_review）+ detected_at desc 排序，前端保序渲染。
const suggestions = computed<SensitiveSuggestion[]>(() => data.value?.suggestions ?? [])
const realSecrets = computed(() => suggestions.value.filter(s => s.severity === 'real_secret'))
const isEmpty = computed(() => suggestions.value.length === 0)

// real_secret 危险色、likely_sensitive 警示色、config_review 中性色。
const SEVERITY_BADGE: Record<SensitiveSeverity, string> = {
  real_secret: 'bg-destructive/10 text-destructive border border-destructive/30',
  likely_sensitive: 'bg-amber-500/10 text-amber-700 dark:text-amber-400 border border-amber-500/20',
  config_review: 'bg-muted text-muted-foreground border border-border/40',
}

function severityBadgeClass(severity: SensitiveSeverity): string {
  return SEVERITY_BADGE[severity] ?? SEVERITY_BADGE.config_review
}

function invalidate() {
  queryClient.invalidateQueries({ queryKey: queryKey.value })
  queryClient.invalidateQueries({ queryKey: exclusionsKey.value })
}

const acceptMutation = useMutation({
  mutationFn: (id: string) => sensitiveSuggestionsApi.accept(props.repoId, id),
})
const dismissMutation = useMutation({
  mutationFn: (id: string) => sensitiveSuggestionsApi.dismiss(props.repoId, id),
})

const isMutating = computed(() => acceptMutation.isPending.value || dismissMutation.isPending.value)

async function acceptSuggestion(id: string) {
  const ok = await confirm({
    title: t('sensitive.acceptConfirm.title'),
    description: t('sensitive.acceptConfirm.description'),
    confirmText: t('sensitive.acceptConfirm.confirmText'),
  })
  if (!ok)
    return
  try {
    await acceptMutation.mutateAsync(id)
    // 接受不触发静默删除：仅建规则，引导用户去清理面板显式清理。
    success(t('sensitive.toast.accepted'))
    invalidate()
  }
  catch (e) {
    handleError(e, t('sensitive.error.accept'))
  }
}

async function dismissSuggestion(id: string) {
  try {
    await dismissMutation.mutateAsync(id)
    success(t('sensitive.toast.dismissed'))
    invalidate()
  }
  catch (e) {
    handleError(e, t('sensitive.error.dismiss'))
  }
}
</script>

<template>
  <div class="card">
    <div class="px-5 py-3.5 border-b border-border/50">
      <div class="flex items-center gap-2">
        <span class="icon-[lucide--shield-alert] text-primary" />
        <h3 class="text-sm font-semibold">
          {{ t('sensitive.title') }}
        </h3>
      </div>
      <p class="text-xs text-muted-foreground mt-0.5">
        {{ t('sensitive.subtitle') }}
      </p>
    </div>

    <div class="p-5 space-y-5">
      <div v-if="isLoading" class="text-xs text-muted-foreground">
        <span class="icon-[lucide--loader-circle] animate-spin mr-1.5" />
        {{ t('sensitive.loading') }}
      </div>
      <div v-else-if="isError" class="text-xs text-destructive">
        {{ t('sensitive.loadError') }}
      </div>

      <!-- 空态：无 pending 建议（不报错、不渲染告警） -->
      <div v-else-if="isEmpty" class="flex items-center gap-2 text-xs text-emerald-600 dark:text-emerald-400">
        <span class="icon-[lucide--check-circle-2] shrink-0" />
        {{ t('sensitive.empty') }}
      </div>

      <template v-else>
        <!-- real_secret 高优先级告警：醒目危险色，确保第一眼可见（T-24-15） -->
        <div
          v-if="realSecrets.length"
          class="flex items-start gap-2 text-xs text-destructive bg-destructive/10 border border-destructive/30 rounded-lg px-3 py-2.5"
          data-testid="real-secret-alert"
        >
          <span class="icon-[lucide--triangle-alert] mt-0.5 shrink-0" />
          <div class="space-y-0.5">
            <p class="font-semibold">
              {{ t('sensitive.realSecretAlertTitle') }}（{{ realSecrets.length }}）
            </p>
            <p>{{ t('sensitive.realSecretAlertDescription') }}</p>
          </div>
        </div>

        <!-- 建议列表（后端已按 severity 排序，前端保序渲染） -->
        <ul class="divide-y divide-border/40 rounded-lg border border-border/40">
          <li
            v-for="s in suggestions"
            :key="s.id"
            class="px-3 py-2.5 space-y-1.5"
            :class="s.severity === 'real_secret' ? 'bg-destructive/5' : ''"
          >
            <div class="flex items-center justify-between gap-3">
              <div class="flex items-center gap-2 min-w-0">
                <span
                  class="text-[10px] px-1.5 py-0.5 rounded shrink-0"
                  :class="severityBadgeClass(s.severity)"
                >
                  {{ t(`sensitive.severity.${s.severity}`) }}
                </span>
                <span class="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground shrink-0">
                  {{ t(`sensitive.detector.${s.detector}`) }}
                </span>
                <code class="text-xs font-mono truncate">{{ s.path }}</code>
              </div>
              <div class="flex items-center gap-1.5 shrink-0">
                <button
                  class="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg border border-border/50 hover:bg-muted/50 transition-colors disabled:opacity-50"
                  :disabled="isMutating"
                  @click="acceptSuggestion(s.id)"
                >
                  <span class="icon-[lucide--shield-check]" />
                  {{ t('sensitive.actions.accept') }}
                </button>
                <button
                  class="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg border border-border/50 text-muted-foreground hover:bg-muted/50 transition-colors disabled:opacity-50"
                  :disabled="isMutating"
                  @click="dismissSuggestion(s.id)"
                >
                  <span class="icon-[lucide--x]" />
                  {{ t('sensitive.actions.dismiss') }}
                </button>
              </div>
            </div>
            <!-- reason 已脱敏（仅命中类型 + 行号，不回显密钥本体，T-24-11） -->
            <p class="text-xs text-muted-foreground">
              <span class="font-medium">{{ t('sensitive.reasonLabel') }}：</span>{{ s.reason }}
            </p>
          </li>
        </ul>
      </template>
    </div>
  </div>
</template>
