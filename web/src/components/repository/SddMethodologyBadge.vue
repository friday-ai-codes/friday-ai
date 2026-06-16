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
    class="inline-flex shrink-0 items-center rounded border border-emerald-200 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700 dark:border-emerald-400/30 dark:text-emerald-300"
  >
    {{ t('repositories.tree.sddBadge') }}
  </span>
</template>
