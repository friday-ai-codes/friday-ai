<script setup lang="ts">
import type { Workflow } from '~/stores/useWorkflowsStore'
import { Button } from '~/components/ui/button'
import { Skeleton } from '~/components/ui/skeleton'
import { Switch } from '~/components/ui/switch'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '~/components/ui/tooltip'
import WorkflowMiniMap from '~/components/workflow/WorkflowMiniMap.vue'
import { NODE_REGISTRY } from '~/types/workflow/registry'

defineProps<{
  workflows: Workflow[]
  loading?: boolean
}>()

const emit = defineEmits<{
  (e: 'click', workflow: Workflow): void
  (e: 'execute', workflow: Workflow): void
  (e: 'requestDelete', workflow: Workflow): void
  (e: 'toggleActive', workflow: Workflow, isActive: boolean): void
}>()

function onCardClick(workflow: Workflow) {
  emit('click', workflow)
}

function onExecuteClick(e: Event, workflow: Workflow) {
  e.stopPropagation()
  if (!workflow.is_active)
    return
  emit('execute', workflow)
}

function onDeleteClick(e: Event, workflow: Workflow) {
  e.stopPropagation()
  emit('requestDelete', workflow)
}

function onToggleActive(checked: boolean, workflow: Workflow) {
  emit('toggleActive', workflow, checked)
}

function getNodeTypeCounts(workflow: Workflow): { type: string, name: string, icon: string, count: number }[] {
  const summary = (workflow as any).node_summary as { node_type: string }[] | undefined
  if (!summary?.length)
    return []

  const countMap = new Map<string, number>()
  for (const n of summary) {
    countMap.set(n.node_type, (countMap.get(n.node_type) || 0) + 1)
  }

  return Array.from(countMap.entries()).map(([type, count]) => {
    const def = NODE_REGISTRY[type as keyof typeof NODE_REGISTRY]
    return {
      type,
      name: def?.displayName ?? type,
      icon: def?.icon ?? 'icon-[lucide--circle]',
      count,
    }
  })
}
</script>

<template>
  <TooltipProvider>
    <!-- Loading State -->
    <div v-if="loading" class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      <div v-for="i in 6" :key="i" class="rounded-lg border border-border/70 bg-card p-4">
        <div class="flex items-center gap-3 mb-3">
          <Skeleton class="h-9 w-9 rounded-lg" />
          <div class="flex-1">
            <Skeleton class="h-4 w-3/4 mb-1.5" />
            <Skeleton class="h-3 w-1/2" />
          </div>
        </div>
        <Skeleton class="h-20 w-full rounded-lg mb-3" />
        <div class="flex items-center justify-between">
          <Skeleton class="h-5 w-16" />
          <Skeleton class="h-7 w-20" />
        </div>
      </div>
    </div>

    <!-- Workflow Cards -->
    <div v-else class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      <div
        v-for="workflow in workflows"
        :key="workflow.id"
        class="workflow-card group relative cursor-pointer"
        @click="onCardClick(workflow)"
      >
        <!-- Card body -->
        <div
          class="relative overflow-hidden rounded-lg border transition-all duration-200"
          :class="[workflow.is_active ? 'bg-card border-border/70 shadow-[0_1px_2px_rgba(15,23,42,0.06)] group-hover:-translate-y-0.5 group-hover:border-primary/30 group-hover:shadow-[0_12px_28px_rgba(15,23,42,0.08)]' : 'bg-muted/25 border-border/50 opacity-80']"
        >
          <!-- Mini Map Preview -->
          <div
            class="workflow-preview relative w-full border-b transition-colors"
            :class="[workflow.is_active ? 'bg-background border-border/50' : 'bg-muted/20 border-border/30']"
          >
            <WorkflowMiniMap
              :nodes="(workflow as any).node_summary || []"
              :edges="(workflow as any).edge_summary || []"
              :width="400"
              :height="100"
              class="w-full h-auto"
            />

            <!-- Node count badge -->
            <div class="absolute right-3 top-3 inline-flex items-center gap-1 rounded-full border border-border/70 bg-background/90 px-2 py-0.5 text-[10px] font-medium text-muted-foreground shadow-sm">
              <span class="icon-[lucide--shapes] text-[10px]" />
              {{ (workflow as any).node_count ?? 0 }} 节点
            </div>
          </div>

          <!-- Content -->
          <div class="p-4 pb-3">
            <!-- Header: Icon + Name + Toggle -->
            <div class="mb-3 flex items-start gap-3">
              <!-- Icon -->
              <div
                class="flex size-9 shrink-0 items-center justify-center rounded-lg ring-1"
                :class="[workflow.is_active ? 'bg-primary/10 text-primary ring-primary/10' : 'bg-muted/50 text-muted-foreground ring-border/40']"
              >
                <span
                  class="icon-[lucide--workflow] text-lg"
                />
              </div>

              <!-- Name & Description -->
              <div class="min-w-0 flex-1">
                <h3
                  class="truncate text-base font-semibold leading-6 transition-colors"
                  :class="[workflow.is_active ? 'group-hover:text-primary' : 'text-muted-foreground']"
                >
                  {{ workflow.name }}
                </h3>
                <p class="mt-0.5 truncate text-sm text-muted-foreground">
                  {{ workflow.description || '暂无描述' }}
                </p>
              </div>

              <!-- Toggle Switch -->
              <div @click.stop>
                <Tooltip>
                  <TooltipTrigger as-child>
                    <Switch
                      :checked="workflow.is_active"
                      class="scale-75 origin-right"
                      @update:checked="onToggleActive($event, workflow)"
                    />
                  </TooltipTrigger>
                  <TooltipContent side="top">
                    <p>{{ workflow.is_active ? '点击禁用' : '点击启用' }}</p>
                  </TooltipContent>
                </Tooltip>
              </div>
            </div>

            <!-- Node Type Tags -->
            <div v-if="getNodeTypeCounts(workflow).length" class="mb-3 flex flex-wrap gap-1.5">
              <span
                v-for="nt in getNodeTypeCounts(workflow)"
                :key="nt.type"
                class="workflow-node-chip inline-flex items-center gap-1 rounded-md border border-border/60 bg-muted/35 px-2 py-1 text-[11px] font-medium text-muted-foreground"
              >
                <span :class="nt.icon" class="text-xs" />
                {{ nt.name }}<template v-if="nt.count > 1">&times;{{ nt.count }}</template>
              </span>
            </div>

            <!-- Actions Row -->
            <div class="workflow-card-actions flex items-center gap-2 border-t border-border/60 pt-3">
              <!-- Execute Button -->
              <Tooltip>
                <TooltipTrigger as-child>
                  <Button
                    size="sm"
                    class="workflow-execute-button h-8 flex-1 text-sm shadow-none"
                    :disabled="!workflow.is_active"
                    @click="onExecuteClick($event, workflow)"
                  >
                    <span class="icon-[lucide--play] mr-1" />
                    执行
                  </Button>
                </TooltipTrigger>
                <TooltipContent v-if="!workflow.is_active" side="top">
                  <p>工作流已禁用</p>
                </TooltipContent>
              </Tooltip>

              <!-- Delete Button -->
              <Button
                variant="ghost"
                size="icon"
                class="h-8 w-8 shrink-0 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                title="删除工作流"
                @click.stop.prevent="onDeleteClick($event, workflow)"
              >
                <span class="icon-[lucide--trash-2] text-sm" />
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </TooltipProvider>
</template>
