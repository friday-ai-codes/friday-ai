<script setup lang="ts">
import type { SddSpecStatus } from '~/api/specs'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps<{
  status: SddSpecStatus
}>()

const { t } = useI18n()

// 5 态色彩映射（50-UI-SPEC「状态徽标色彩映射」D-50-6）。color 不单独承载语义——
// 徽标含文字 + title（可达性）。draft 与 archived 同灰调，靠饱和度/强调度区分。
const STATUS_CLASS: Record<SddSpecStatus, string> = {
  draft: 'bg-gray-500/10 text-gray-600 border-gray-200 dark:text-gray-300 dark:border-gray-600/40',
  in_review: 'bg-amber-500/10 text-amber-700 border-amber-200 dark:text-amber-300 dark:border-amber-400/30',
  approved: 'bg-emerald-500/10 text-emerald-700 border-emerald-200 dark:text-emerald-300 dark:border-emerald-400/30',
  implemented: 'bg-blue-500/10 text-blue-700 border-blue-200 dark:text-blue-300 dark:border-blue-400/30',
  archived: 'bg-muted text-muted-foreground border-border/40',
}

const label = computed(() => t(`specs.status.${props.status}`))
const badgeClass = computed(() => STATUS_CLASS[props.status])
</script>

<template>
  <span
    data-testid="spec-status-badge"
    :title="label"
    class="inline-flex shrink-0 items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-medium"
    :class="badgeClass"
  >
    <span v-if="status === 'archived'" class="icon-[lucide--archive] size-3" aria-hidden="true" />
    {{ label }}
  </span>
</template>
