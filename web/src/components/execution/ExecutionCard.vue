<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

import ExecutionStatusBadge from './ExecutionStatusBadge.vue'

const props = defineProps<{
  execution: {
    id: string
    workflow: string
    workflow_name: string
    status: string
    trigger_type: string
    triggered_by_name: string | null
    total_nodes: number
    completed_nodes: number
    progress: number
    duration: number | null
    created_at: string
    started_at: string | null
    completed_at: string | null
  }
}>()

const triggerTypeLabel = computed(() => {
  const labels: Record<string, string> = {
    manual: '手动触发',
    webhook: 'Webhook',
    schedule: '定时触发',
    event: '事件触发',
  }
  return labels[props.execution.trigger_type] || props.execution.trigger_type
})

const formattedDuration = computed(() => {
  if (!props.execution.duration)
    return '-'
  const seconds = Math.floor(props.execution.duration)
  if (seconds < 60)
    return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = seconds % 60
  if (minutes < 60)
    return `${minutes}m ${remainingSeconds}s`
  const hours = Math.floor(minutes / 60)
  const remainingMinutes = minutes % 60
  return `${hours}h ${remainingMinutes}m`
})

const formattedTime = computed(() => {
  return new Date(props.execution.created_at).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
})

const isActive = computed(() => {
  return ['running', 'pending', 'paused', 'waiting_approval'].includes(props.execution.status)
})
</script>

<template>
  <RouterLink
    :to="`/executions/${execution.id}`"
    class="group relative block"
  >
    <!-- Hover glow effect -->
    <div
      class="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-500 rounded-2xl blur-xl -z-10"
    />

    <!-- Card -->
    <div
      class="relative p-4 rounded-2xl bg-card/70 backdrop-blur-sm border border-border/50 group-hover:border-primary/30 group-hover:shadow-lg group-hover:shadow-primary/5 transition-all duration-300"
    >
      <div class="flex items-center justify-between gap-4">
        <!-- Left: Workflow info -->
        <div class="flex items-center gap-3 min-w-0 flex-1">
          <div class="p-2 rounded-xl bg-primary/10">
            <span class="icon-[lucide--workflow] text-xl text-primary" />
          </div>
          <div class="min-w-0">
            <h3 class="font-medium truncate group-hover:text-primary transition-colors">
              {{ execution.workflow_name }}
            </h3>
            <div class="flex items-center gap-2 text-xs text-muted-foreground mt-0.5">
              <span class="flex items-center gap-1">
                <span class="icon-[lucide--zap] text-xs" />
                {{ triggerTypeLabel }}
              </span>
              <span v-if="execution.triggered_by_name" class="flex items-center gap-1">
                <span class="icon-[lucide--user] text-xs" />
                {{ execution.triggered_by_name }}
              </span>
            </div>
          </div>
        </div>

        <!-- Center: Progress (for active executions) -->
        <div v-if="isActive && execution.total_nodes > 0" class="hidden sm:flex items-center gap-2 min-w-[120px]">
          <div class="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
            <div
              class="h-full bg-primary transition-all duration-300"
              :style="{ width: `${execution.progress}%` }"
            />
          </div>
          <span class="text-xs text-muted-foreground whitespace-nowrap">
            {{ execution.completed_nodes }}/{{ execution.total_nodes }}
          </span>
        </div>

        <!-- Right: Status & Time -->
        <div class="flex items-center gap-4">
          <div class="hidden sm:flex flex-col items-end text-xs text-muted-foreground">
            <span>{{ formattedTime }}</span>
            <span v-if="execution.duration" class="flex items-center gap-1">
              <span class="icon-[lucide--timer] text-xs" />
              {{ formattedDuration }}
            </span>
          </div>
          <ExecutionStatusBadge :status="execution.status" />
          <span class="icon-[lucide--chevron-right] text-muted-foreground group-hover:text-primary group-hover:translate-x-1 transition-all" />
        </div>
      </div>
    </div>
  </RouterLink>
</template>
