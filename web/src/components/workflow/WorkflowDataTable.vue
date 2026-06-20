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
import { getNodeDefinition } from '~/types/workflow/registry'

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
    const def = getNodeDefinition(type)
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

function hasNodes(workflow: Workflow): boolean {
  return (((workflow as any).node_summary as unknown[] | undefined)?.length ?? 0) > 0
}
</script>

<template>
  <TooltipProvider>
    <!-- Loading State -->
    <div v-if="loading" class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      <div v-for="i in 6" :key="i" class="flex min-h-[220px] flex-col overflow-hidden rounded-lg border border-border/70 bg-card">
        <div class="flex flex-1 flex-col gap-3 p-4">
          <div class="flex items-start gap-3">
            <Skeleton class="size-9 rounded-lg" />
            <div class="flex-1 space-y-1.5">
              <Skeleton class="h-4 w-3/4" />
              <Skeleton class="h-3.5 w-1/2" />
            </div>
            <Skeleton class="h-5 w-8 rounded-full" />
          </div>
          <Skeleton class="h-20 w-full rounded-lg" />
          <div class="flex gap-1.5">
            <Skeleton v-for="chip in 3" :key="chip" class="h-6 w-20 rounded-md" />
          </div>
        </div>
        <div class="flex items-center justify-between border-t border-border/60 bg-muted/20 px-4 py-2.5">
          <Skeleton class="h-4 w-16" />
          <Skeleton class="h-7 w-20 rounded-md" />
        </div>
      </div>
    </div>

    <!-- Workflow Cards -->
    <div v-else class="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
      <article
        v-for="workflow in workflows"
        :key="workflow.id"
        class="workflow-card workflow-card-shell group relative flex min-h-[220px] cursor-pointer flex-col overflow-hidden rounded-2xl border bg-card transition-all duration-200"
        :class="[workflow.is_active
          ? 'border-border/70 shadow-[0_1px_2px_rgba(15,23,42,0.06)] hover:-translate-y-1 hover:border-primary/40 hover:shadow-[0_18px_40px_rgba(15,23,42,0.10)]'
          : 'border-dashed border-border/70 hover:-translate-y-0.5 hover:border-border']"
        @click="onCardClick(workflow)"
      >
        <!-- 顶部品牌色高亮条（hover 时点亮，启用态常驻） -->
        <div
          class="absolute inset-x-0 top-0 h-1 transition-opacity duration-200"
          :class="[workflow.is_active
            ? 'gradient-primary opacity-70 group-hover:opacity-100'
            : 'bg-muted-foreground/20 opacity-0 group-hover:opacity-60']"
        />

        <!-- Content -->
        <div class="workflow-card-content flex flex-1 flex-col gap-3 p-4 pt-5">
          <!-- Header: Icon + Name + Toggle -->
          <div class="flex items-start gap-3">
            <div
              class="mt-0.5 flex size-10 shrink-0 items-center justify-center rounded-xl ring-1 transition-colors"
              :class="[workflow.is_active ? 'bg-primary/10 text-primary ring-primary/15' : 'bg-muted/60 text-muted-foreground ring-border/50']"
            >
              <span class="icon-[lucide--workflow] text-lg" />
            </div>

            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2">
                <h3
                  class="truncate text-base font-semibold leading-6 transition-colors"
                  :class="[workflow.is_active ? 'text-foreground group-hover:text-primary' : 'text-foreground/80']"
                >
                  {{ workflow.name }}
                </h3>
                <!-- 状态徽章：颜色 + 文字双重表达，不只靠透明度（a11y: color-not-only） -->
                <span
                  class="inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium leading-none"
                  :class="[workflow.is_active
                    ? 'bg-emerald-500/12 text-emerald-600'
                    : 'bg-muted text-muted-foreground']"
                >
                  <span
                    class="size-1.5 rounded-full"
                    :class="[workflow.is_active ? 'bg-emerald-500' : 'bg-muted-foreground/60']"
                  />
                  {{ workflow.is_active ? '已启用' : '已禁用' }}
                </span>
              </div>
              <p class="workflow-card-description mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
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

          <!-- Mini Map Preview（仅在有节点时展示） -->
          <div
            v-if="hasNodes(workflow)"
            class="workflow-preview relative h-20 w-full shrink-0 overflow-hidden rounded-lg border transition-colors"
            :class="[workflow.is_active ? 'border-border/50 bg-background' : 'border-border/30 bg-muted/20']"
          >
            <WorkflowMiniMap
              :nodes="(workflow as any).node_summary || []"
              :edges="(workflow as any).edge_summary || []"
              :width="400"
              :height="80"
              class="h-full w-full"
            />
            <div class="absolute right-2 top-2 inline-flex items-center gap-1 rounded-full border border-border/70 bg-background/90 px-2 py-0.5 text-[10px] font-medium text-muted-foreground shadow-sm">
              <span class="icon-[lucide--shapes] text-[10px]" />
              {{ (workflow as any).node_count ?? 0 }} 节点
            </div>
          </div>

          <!-- Node Type Tags -->
          <div v-if="getVisibleNodeTypeCounts(workflow).length" class="workflow-node-chip-row flex flex-wrap gap-1.5">
            <span
              v-for="nt in getVisibleNodeTypeCounts(workflow)"
              :key="nt.type"
              class="workflow-node-chip inline-flex h-6 max-w-full items-center gap-1 truncate rounded-md border border-border/60 bg-muted/35 px-2 text-[11px] font-medium text-muted-foreground"
            >
              <span :class="nt.icon" class="shrink-0 text-xs" />
              <span class="truncate">{{ nt.name }}</span>
              <template v-if="nt.count > 1">&times;{{ nt.count }}</template>
            </span>
            <span
              v-if="getHiddenNodeTypeCount(workflow) > 0"
              class="workflow-node-overflow inline-flex h-6 items-center rounded-md border border-primary/15 bg-primary/10 px-2 text-[11px] font-semibold text-primary"
            >
              +{{ getHiddenNodeTypeCount(workflow) }}
            </span>
          </div>

          <!-- 空工作流提示 -->
          <div v-else class="flex items-center gap-1.5 text-xs text-muted-foreground/70">
            <span class="icon-[lucide--shapes]" />
            暂无节点，点击进入编辑器开始编排
          </div>
        </div>

        <!-- 底部操作栏 -->
        <div class="workflow-card-actions mt-auto flex items-center justify-between border-t border-border/60 bg-muted/25 px-4 py-2.5">
          <span class="inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground transition-colors group-hover:text-primary">
            编辑流程
            <span class="icon-[lucide--arrow-right] transition-transform group-hover:translate-x-0.5" />
          </span>

          <div class="flex items-center gap-1">
            <Tooltip>
              <TooltipTrigger as-child>
                <!-- 禁用态用「明确的灰色禁用样式」而非微弱的半透明主色，确保按钮始终可见 -->
                <Button
                  variant="ghost"
                  size="sm"
                  class="workflow-execute-button h-7 gap-1 px-2.5 text-xs font-medium disabled:!opacity-100"
                  :class="workflow.is_active
                    ? 'text-primary hover:bg-primary/10 hover:text-primary'
                    : 'cursor-not-allowed text-muted-foreground/70 hover:bg-transparent'"
                  :disabled="!workflow.is_active"
                  @click="onExecuteClick($event, workflow)"
                >
                  <span class="icon-[lucide--play]" />
                  执行
                </Button>
              </TooltipTrigger>
              <TooltipContent v-if="!workflow.is_active" side="top">
                <p>工作流已禁用，启用后可执行</p>
              </TooltipContent>
            </Tooltip>

            <Button
              variant="ghost"
              size="icon"
              class="size-7 shrink-0 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
              title="删除工作流"
              @click.stop.prevent="onDeleteClick($event, workflow)"
            >
              <span class="icon-[lucide--trash-2] text-sm" />
            </Button>
          </div>
        </div>
      </article>
    </div>
  </TooltipProvider>
</template>
