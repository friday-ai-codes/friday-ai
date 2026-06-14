<script setup lang="ts">
import type { ValidationIssue } from '~/stores/useWorkflowValidationStore'
import { AlertCircle, AlertTriangle, ChevronDown } from 'lucide-vue-next'
import { storeToRefs } from 'pinia'
import { computed, inject, ref } from 'vue'
import { Badge } from '~/components/ui/badge'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '~/components/ui/collapsible'
import { WorkflowFocusKey } from '~/components/workflow/workflowFocus'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
import { useWorkflowValidationStore } from '~/stores/useWorkflowValidationStore'

const validationStore = useWorkflowValidationStore()
const workflowStore = useWorkflowsStore()
const { issuesList, hasIssues, hasErrors, errorCount, warningCount } = storeToRefs(validationStore)

// 整体面板视觉：含 error 用红色系，否则 amber
const tone = computed(() => (hasErrors.value
  ? {
      container: 'bg-destructive/10 border-destructive/30',
      hover: 'hover:bg-destructive/5',
      iconWrap: 'bg-destructive/20',
      icon: 'text-destructive',
    }
  : {
      container: 'bg-amber-500/10 border-amber-500/30',
      hover: 'hover:bg-amber-500/5',
      iconWrap: 'bg-amber-500/20',
      icon: 'text-amber-600',
    }),
)

// Get node name by ID using store getter
function getNodeName(nodeId: string): string {
  const node = workflowStore.getNodeById(nodeId)
  return node?.name || nodeId.slice(0, 8)
}

// 单条问题的定位描述：edge 级显示 nodeId/fieldPath，否则展示 reason/fieldPath
function describeLocation(issue: ValidationIssue): string {
  if (issue.nodeId)
    return issue.fieldPath ? `${getNodeName(issue.nodeId)} · ${issue.fieldPath}` : getNodeName(issue.nodeId)
  if (issue.edgeId)
    return issue.fieldPath || issue.edgeId
  return issue.fieldPath || issue.reason
}

// 画布聚焦：由 WorkflowCanvas（VueFlow 上下文内）经共同祖先 provide 的持有器注入。
// 注入不可用 / 尚未注册时安全降级（no-op，不报错）。
const workflowFocus = inject(WorkflowFocusKey, null)

// 点击问题 → 定位到画布对应节点并居中。
// issue 有 nodeId → 直接聚焦；仅有 edgeId → 取该边的 target（优先）/ source 节点再聚焦。
function handleIssueClick(issue: ValidationIssue) {
  const focus = workflowFocus?.focusNode
  if (!focus)
    return

  let nodeId = issue.nodeId
  if (!nodeId && issue.edgeId) {
    const edge = workflowStore.edges.find(e => e.id === issue.edgeId)
    nodeId = edge?.target || edge?.source
  }
  if (nodeId)
    focus(nodeId)
}

// Panel open state - auto-open when issues exist
const isOpen = ref(true)
</script>

<template>
  <Collapsible
    v-if="hasIssues"
    v-model:open="isOpen"
    class="rounded-xl border overflow-hidden"
    :class="tone.container"
  >
    <CollapsibleTrigger class="w-full">
      <div class="flex items-center justify-between p-3 transition-colors" :class="tone.hover">
        <div class="flex items-center gap-2">
          <div class="p-1.5 rounded-lg" :class="tone.iconWrap">
            <component :is="hasErrors ? AlertCircle : AlertTriangle" class="w-4 h-4" :class="tone.icon" />
          </div>
          <span class="text-sm font-medium">问题</span>
          <Badge v-if="errorCount > 0" variant="destructive">
            {{ errorCount }} 错误
          </Badge>
          <Badge v-if="warningCount > 0" variant="warning">
            {{ warningCount }} 警告
          </Badge>
        </div>
        <ChevronDown
          class="w-4 h-4 text-muted-foreground transition-transform"
          :class="{ 'rotate-180': isOpen }"
        />
      </div>
    </CollapsibleTrigger>

    <CollapsibleContent>
      <div class="px-3 pb-3 space-y-2">
        <button
          v-for="issue in issuesList"
          :key="issue.id"
          class="w-full text-left p-2.5 rounded-lg bg-background/50 hover:bg-background/80 transition-colors group"
          @click="handleIssueClick(issue)"
        >
          <div class="flex items-start gap-2">
            <AlertCircle
              v-if="issue.severity === 'error'"
              class="w-4 h-4 text-destructive mt-0.5 flex-shrink-0"
            />
            <AlertTriangle
              v-else
              class="w-4 h-4 text-amber-500 mt-0.5 flex-shrink-0"
            />
            <div class="flex-1 min-w-0">
              <p class="text-sm font-medium truncate">
                {{ issue.message }}
              </p>
              <p class="text-xs text-muted-foreground mt-0.5">
                {{ describeLocation(issue) }}
              </p>
            </div>
          </div>
        </button>
      </div>
    </CollapsibleContent>
  </Collapsible>
</template>
