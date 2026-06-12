<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Badge } from '~/components/ui/badge'

const props = defineProps<{
  kind: string
}>()

const { t } = useI18n()

const kindClass: Record<string, string> = {
  work_item: 'bg-slate-500/10 text-slate-700 border-slate-200',
  tech_plan: 'bg-primary/10 text-primary border-primary/20',
  code_change: 'bg-emerald-500/10 text-emerald-700 border-emerald-200',
}

const kindLabel: Record<string, string> = {
  work_item: 'knowledge.entity.kind.workItem',
  tech_plan: 'knowledge.entity.kind.techPlan',
  code_change: 'knowledge.entity.kind.codeChange',
}

const labelKey = computed(() => kindLabel[props.kind] ?? props.kind)
const badgeClass = computed(() => kindClass[props.kind] ?? kindClass.work_item)
</script>

<template>
  <Badge variant="outline" :class="badgeClass" data-testid="entity-kind-badge">
    {{ t(labelKey) }}
  </Badge>
</template>
