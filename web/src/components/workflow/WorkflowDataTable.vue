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
    <div v-if="loading" class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      <div v-for="i in 6" :key="i" class="p-5 rounded-2xl bg-card/80 border border-border/50">
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
    <div v-else class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      <div
        v-for="workflow in workflows"
        :key="workflow.id"
        class="group relative cursor-pointer"
        @click="onCardClick(workflow)"
      >
        <!-- Card body -->
        <div
          class="relative rounded-2xl backdrop-blur-sm border transition-all duration-300 overflow-hidden"
          :class="[workflow.is_active ? 'bg-card/80 border-border/50 group-hover:border-primary/30 group-hover:shadow-card-hover group-hover:-translate-y-0.5' : 'bg-muted/30 border-border/30']"
        >
          <!-- Mini Map Preview -->
          <div
            class="relative w-full border-b transition-colors"
            :class="[workflow.is_active ? 'bg-linear-to-b from-background/20 to-background/60 border-border/30' : 'bg-muted/20 border-border/20']"
          >
            <WorkflowMiniMap
              :nodes="(workflow as any).node_summary || []"
              :edges="(workflow as any).edge_summary || []"
              :width="400"
              :height="100"
              class="w-full h-auto"
            />

            <!-- Node count badge -->
            <div class="absolute top-2 right-2 flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-background/70 backdrop-blur-sm text-[10px] text-muted-foreground">
              <span class="icon-[lucide--shapes] text-[10px]" />
              {{ (workflow as any).node_count ?? 0 }} 节点
            </div>
          </div>

          <!-- Content -->
          <div class="p-4">
            <!-- Header: Icon + Name + Toggle -->
            <div class="flex items-start gap-3 mb-2.5">
              <!-- Icon -->
              <div
                class="p-1.5 rounded-lg shrink-0"
                :class="[workflow.is_active ? 'bg-linear-to-br from-teal-500/10 to-cyan-500/10' : 'bg-muted/50']"
              >
                <span
                  class="text-base"
                  :class="[workflow.is_active ? 'icon-[lucide--workflow] text-teal-500' : 'icon-[lucide--workflow] text-muted-foreground']"
                />
              </div>

              <!-- Name & Description -->
              <div class="flex-1 min-w-0">
                <h3
                  class="text-sm font-medium leading-tight truncate transition-colors"
                  :class="[workflow.is_active ? 'group-hover:text-primary' : 'text-muted-foreground']"
                >
                  {{ workflow.name }}
                </h3>
                <p class="text-xs text-muted-foreground truncate mt-0.5">
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
            <div v-if="getNodeTypeCounts(workflow).length" class="flex flex-wrap gap-1 mb-3">
              <span
                v-for="nt in getNodeTypeCounts(workflow)"
                :key="nt.type"
                class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-muted/50 text-[10px] text-muted-foreground"
              >
                <span :class="nt.icon" class="text-[10px]" />
                {{ nt.name }}<template v-if="nt.count > 1">&times;{{ nt.count }}</template>
              </span>
            </div>

            <!-- Actions Row -->
            <div class="flex items-center gap-2 pt-2.5 border-t border-border/50">
              <!-- Execute Button -->
              <Tooltip>
                <TooltipTrigger as-child>
                  <Button
                    size="sm"
                    class="flex-1 h-7 text-xs"
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
                class="h-7 w-7 shrink-0 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
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
