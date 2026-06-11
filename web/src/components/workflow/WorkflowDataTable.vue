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

const MAX_VISIBLE_NODE_CHIPS = 4

interface NodeTypeCount {
  type: string
  name: string
  icon: string
  count: number
}

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

function getNodeTypeCounts(workflow: Workflow): NodeTypeCount[] {
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

function getVisibleNodeTypeCounts(workflow: Workflow): NodeTypeCount[] {
  return getNodeTypeCounts(workflow).slice(0, MAX_VISIBLE_NODE_CHIPS)
}

function getHiddenNodeTypeCount(workflow: Workflow): number {
  return Math.max(getNodeTypeCounts(workflow).length - MAX_VISIBLE_NODE_CHIPS, 0)
}
</script>

<template>
  <TooltipProvider>
    <!-- Loading State -->
    <div v-if="loading" class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      <div v-for="i in 6" :key="i" class="flex h-[380px] flex-col overflow-hidden rounded-lg border border-border/70 bg-card">
        <Skeleton class="h-28 w-full rounded-none" />
        <div class="flex flex-1 flex-col p-4 pb-3">
          <div class="mb-3 flex items-start gap-3">
            <Skeleton class="h-9 w-9 rounded-lg" />
            <div class="flex-1">
              <Skeleton class="mb-1.5 h-4 w-3/4" />
              <Skeleton class="h-9 w-full" />
            </div>
            <Skeleton class="h-5 w-8 rounded-full" />
          </div>
          <div class="mb-3 grid min-h-[64px] grid-cols-2 gap-1.5">
            <Skeleton v-for="chip in 4" :key="chip" class="h-7 rounded-md" />
          </div>
          <div class="mt-auto flex items-center gap-2 border-t border-border/60 pt-3">
            <Skeleton class="h-8 flex-1 rounded-md" />
            <Skeleton class="h-8 w-8 rounded-md" />
          </div>
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
          class="workflow-card-shell relative flex h-[380px] flex-col overflow-hidden rounded-lg border transition-all duration-200"
          :class="[workflow.is_active ? 'bg-card border-border/70 shadow-[0_1px_2px_rgba(15,23,42,0.06)] group-hover:-translate-y-0.5 group-hover:border-primary/30 group-hover:shadow-[0_12px_28px_rgba(15,23,42,0.08)]' : 'bg-muted/25 border-border/50 opacity-80']"
        >
          <!-- Mini Map Preview -->
          <div
            class="workflow-preview relative h-28 w-full shrink-0 border-b transition-colors"
            :class="[workflow.is_active ? 'bg-background border-border/50' : 'bg-muted/20 border-border/30']"
          >
            <WorkflowMiniMap
              :nodes="(workflow as any).node_summary || []"
              :edges="(workflow as any).edge_summary || []"
              :width="400"
              :height="112"
              class="h-full w-full"
            />

            <!-- Node count badge -->
            <div class="absolute right-3 top-3 inline-flex items-center gap-1 rounded-full border border-border/70 bg-background/90 px-2 py-0.5 text-[10px] font-medium text-muted-foreground shadow-sm">
              <span class="icon-[lucide--shapes] text-[10px]" />
              {{ (workflow as any).node_count ?? 0 }} 节点
            </div>
          </div>

          <!-- Content -->
          <div class="workflow-card-content flex flex-1 flex-col p-4 pb-3">
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
                <p class="workflow-card-description mt-0.5 line-clamp-2 min-h-10 text-sm leading-5 text-muted-foreground">
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
            <div class="workflow-node-chip-row mb-3 flex min-h-[64px] flex-wrap content-start gap-1.5 overflow-hidden">
              <span
                v-for="nt in getVisibleNodeTypeCounts(workflow)"
                :key="nt.type"
                class="workflow-node-chip inline-flex h-7 max-w-full items-center gap-1 truncate rounded-md border border-border/60 bg-muted/35 px-2 text-[11px] font-medium text-muted-foreground"
              >
                <span :class="nt.icon" class="shrink-0 text-xs" />
                <span class="truncate">{{ nt.name }}</span>
                <template v-if="nt.count > 1">&times;{{ nt.count }}</template>
              </span>
              <span
                v-if="getHiddenNodeTypeCount(workflow) > 0"
                class="workflow-node-overflow inline-flex h-7 items-center rounded-md border border-primary/15 bg-primary/10 px-2 text-[11px] font-semibold text-primary"
              >
                +{{ getHiddenNodeTypeCount(workflow) }}
              </span>
            </div>

            <!-- Actions Row -->
            <div class="workflow-card-actions mt-auto flex shrink-0 items-center gap-2 border-t border-border/60 pt-3">
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
