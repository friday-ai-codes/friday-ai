<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps<{
  methodology?: string | null
}>()

const { t } = useI18n()

const isSdd = computed(() => props.methodology === 'SDD')
</script>

<template>
  <span
    v-if="isSdd"
    data-testid="sdd-methodology-badge"
    :title="t('repositories.tree.sddBadgeTitle')"
    class="inline-flex shrink-0 items-center gap-1 rounded-md border border-emerald-500/30 bg-emerald-500/15 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-emerald-700 shadow-sm shadow-emerald-500/10 dark:border-emerald-400/40 dark:bg-emerald-400/15 dark:text-emerald-300"
  >
    <span class="icon-[lucide--scroll-text] text-[13px]" aria-hidden="true" />
    {{ t('repositories.tree.sddBadge') }}
  </span>
</template>
