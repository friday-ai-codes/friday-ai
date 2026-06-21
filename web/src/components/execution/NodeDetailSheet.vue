<script setup lang="ts">
import type { NodeExecution, WorkflowDefinition } from '~/stores/useExecutionsStore'
/**
 * NodeDetailSheet -- 节点详情右侧抽屉面板
 *
 * 从右侧滑出的抽屉面板，包含三个基础 Tab：概览、数据、配置。
 * AI 节点额外显示「AI 透视」Tab（ReAct 步骤流 + 节点成本）。
 * 根据节点类型和状态，在概览 Tab 底部条件渲染 AI/审批/调试面板。
 */
import { computed, ref, watch } from 'vue'
import { Button } from '~/components/ui/button'
import { ScrollArea } from '~/components/ui/scroll-area'
import { Separator } from '~/components/ui/separator'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '~/components/ui/sheet'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '~/components/ui/tabs'
import AICodingPanel from './AICodingPanel.vue'
import AIInsightTab from './AIInsightTab.vue'
import ExecutionLogPanel from './ExecutionLogPanel.vue'
import HumanApprovalPanel from './HumanApprovalPanel.vue'
import NodeConfigTab from './NodeConfigTab.vue'
import NodeDataTab from './NodeDataTab.vue'
import NodeDebugPanel from './NodeDebugPanel.vue'
import NodeOverviewTab from './NodeOverviewTab.vue'
import PlanApprovalPanel from './PlanApprovalPanel.vue'
import SubStepDetailTab from './SubStepDetailTab.vue'

/** UX-02 D-09 — AI 节点 Provider 快照类型 */
interface NodeSnapshot {
  provider_type: 'anthropic' | 'openai_responses' | 'openai_chat' | 'gemini' | 'ollama'
  model: string
  source: 'node' | 'conversation' | 'project' | 'system'
  credential_id: string | null
}

const props = defineProps<{
  open: boolean
  nodeExecution: NodeExecution | null
  nodeConfig: Record<string, unknown>
  bottleneckInfo?: { level: string, rank: number, durationPercent: number } | null
  executionId: string
  /** 是否可以从失败节点继续 */
  canResume?: boolean
  /** 子步骤聚焦 ID（从 DAG 时间线点击跳转，） */
  focusSubStepId?: string
  /** : 当前节点是否处于调试暂停状态 */
  isDebugPaused?: boolean
  /** : 工作流定义（用于下游变量检查） */
  workflowDefinition?: WorkflowDefinition | null
  /** UX-02 D-09：当前节点的 Provider 快照；undefined=非 AI 节点，null=miss */
  providerSnapshot?: NodeSnapshot | null
  /** UX-02 D-09：是否允许基于快照 Replay（由页面根据 execution.status 计算） */
  canReplaySnapshot?: boolean
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  'actionComplete': []
  /** : 从此节点继续执行 */
  'resumeFromNode': [nodeId: string]
  /** UX-02 D-09：基于快照 Replay */
  'replaySnapshot': [nodeId: string]
}>()

/** 当前 Tab 状态（受控模式，切换节点时重置） */
const activeTab = ref('overview')

/** 当前节点类型 */
const nodeType = computed(() => props.nodeExecution?.node_type ?? '')
/** 当前节点状态 */
const nodeStatus = computed(() => props.nodeExecution?.status ?? '')

/** AI 节点类型判断 */
const AI_NODE_TYPES = [
  'ai_prompt',
  'ai_coding',
  'ai_plan_generation',
  'ai_coding_dispatcher',
] as const

const isAINode = computed(() =>
  AI_NODE_TYPES.includes(nodeType.value as typeof AI_NODE_TYPES[number]),
)

/** 是否有子步骤可查看（AI 节点 + 有进度数据） */
const hasSubSteps = computed(() =>
  isAINode.value && props.nodeExecution?.sub_step_progress != null,
)

/** 是否有执行日志可查看 */
const hasLogs = computed(() =>
  (props.nodeExecution?.logs?.length ?? 0) > 0,
)

/** 切换节点时重置 Tab */
watch(() => props.nodeExecution, () => {
  activeTab.value = 'overview'
})

/** 从 DAG 时间线点击子步骤时自动切换到子步骤 Tab */
watch(() => props.focusSubStepId, (id) => {
  if (id)
    activeTab.value = 'sub-steps'
})

/** 是否显示 PlanApprovalPanel：ai_plan_approval + waiting_event/completed */
const showPlanApproval = computed(() =>
  nodeType.value === 'ai_plan_approval'
  && ['waiting_event', 'completed'].includes(nodeStatus.value),
)

const showHumanApproval = computed(() =>
  nodeType.value === 'human_approval'
  && ['waiting_approval', 'completed'].includes(nodeStatus.value),
)

/** 是否显示 AICodingPanel：ai_coding + running/waiting_event/completed */
const showAICoding = computed(() =>
  nodeType.value === 'ai_coding'
  && ['running', 'waiting_event', 'completed'].includes(nodeStatus.value),
)

/** 是否显示 NodeDebugPanel：所有 running/waiting_event/completed/failed 状态 */
const showDebugPanel = computed(() =>
  ['running', 'waiting_event', 'completed', 'failed'].includes(nodeStatus.value),
)

/** 是否有任何附加面板需要显示 */
const hasExtraPanels = computed(() =>
  showPlanApproval.value
  || showHumanApproval.value
  || showAICoding.value
  || showDebugPanel.value,
)

function handleOpenChange(value: boolean) {
  emit('update:open', value)
}

function handleActionComplete() {
  emit('actionComplete')
}
</script>

<template>
  <Sheet :open="open" @update:open="handleOpenChange">
    <SheetContent
      side="right"
      class="w-[480px] sm:max-w-[480px] p-0 flex flex-col bg-background/80 backdrop-blur-xl border-l border-border/30 shadow-[-8px_0_30px_rgba(0,0,0,0.15)]"
    >
      <!-- Header -->
      <SheetHeader class="px-6 pt-6 pb-4 border-b border-border/30 shrink-0">
        <SheetTitle class="text-base font-semibold">
          {{ nodeExecution?.node_name ?? '节点详情' }}
        </SheetTitle>
        <SheetDescription class="text-xs text-muted-foreground font-mono">
          {{ nodeExecution?.node_type ?? '' }}
        </SheetDescription>
      </SheetHeader>

      <!-- Tabs 内容区域 -->
      <div v-if="nodeExecution" class="flex-1 min-h-0">
        <Tabs v-model="activeTab" class="h-full flex flex-col">
          <TabsList class="w-full shrink-0 mx-6 mt-4" style="width: calc(100% - 3rem)">
            <TabsTrigger value="overview" class="flex-1">
              概览
            </TabsTrigger>
            <TabsTrigger v-if="hasLogs" value="logs" class="flex-1">
              日志
            </TabsTrigger>
            <TabsTrigger value="data" class="flex-1">
              数据
            </TabsTrigger>
            <TabsTrigger value="config" class="flex-1">
              配置
            </TabsTrigger>
            <TabsTrigger v-if="hasSubSteps" value="sub-steps" class="flex-1">
              子步骤
            </TabsTrigger>
            <TabsTrigger v-if="isAINode" value="ai-insight" class="flex-1">
              AI 透视
            </TabsTrigger>
          </TabsList>

          <!-- 概览 Tab -->
          <TabsContent value="overview" class="flex-1 min-h-0 mt-0">
            <ScrollArea class="h-full">
              <div class="px-6 py-4 space-y-4">
                <NodeOverviewTab
                  :node-execution="nodeExecution"
                  :bottleneck-info="bottleneckInfo"
                  :provider-snapshot="providerSnapshot"
                  :can-replay-snapshot="canReplaySnapshot"
                  @replay-snapshot="(nid: string) => emit('replaySnapshot', nid)"
                />

                <!-- : 从此继续执行按钮（仅失败节点） -->
                <div v-if="nodeExecution.status === 'failed'" class="space-y-2">
                  <Separator />
                  <Button
                    :disabled="!canResume"
                    class="w-full"
                    @click="nodeExecution && emit('resumeFromNode', nodeExecution.node)"
                  >
                    <span class="icon-[lucide--play-circle] w-4 h-4 mr-2" />
                    从此继续执行
                  </Button>
                  <p v-if="!canResume" class="text-xs text-muted-foreground text-center">
                    工作流已修改，无法从此继续
                  </p>
                </div>

                <!-- 条件渲染：AI / 审批 / 调试面板 -->
                <template v-if="hasExtraPanels">
                  <Separator />

                  <!-- AI 方案审批面板 -->
                  <PlanApprovalPanel
                    v-if="showPlanApproval"
                    :node-execution="nodeExecution"
                    @action-complete="handleActionComplete"
                  />

                  <HumanApprovalPanel
                    v-if="showHumanApproval"
                    :node-execution="nodeExecution"
                    @action-complete="handleActionComplete"
                  />

                  <!-- AI 编码面板 -->
                  <AICodingPanel
                    v-if="showAICoding"
                    :node-execution="nodeExecution"
                  />

                  <!-- 调试交互面板 -->
                  <NodeDebugPanel
                    v-if="showDebugPanel"
                    :node-execution-id="nodeExecution.id"
                    :output-data="nodeExecution.output_data"
                    :node-status="nodeExecution.status"
                    @answered="handleActionComplete"
                  />
                </template>
              </div>
            </ScrollArea>
          </TabsContent>

          <!-- 数据 Tab -->
          <TabsContent value="data" class="flex-1 min-h-0 mt-0">
            <ScrollArea class="h-full">
              <div class="px-6 py-4">
                <NodeDataTab
                  :node-execution="nodeExecution"
                  :is-debug-paused="isDebugPaused"
                  :workflow-definition="workflowDefinition"
                />
              </div>
            </ScrollArea>
          </TabsContent>

          <!-- 配置 Tab -->
          <TabsContent value="config" class="flex-1 min-h-0 mt-0">
            <ScrollArea class="h-full">
              <div class="px-6 py-4">
                <NodeConfigTab :config="nodeConfig" />
              </div>
            </ScrollArea>
          </TabsContent>

          <!-- 日志 Tab（有日志时显示） -->
          <TabsContent v-if="hasLogs" value="logs" class="flex-1 min-h-0 mt-0">
            <ExecutionLogPanel :logs="nodeExecution.logs!" />
          </TabsContent>

          <!-- 子步骤 Tab（AI 节点有进度时） -->
          <TabsContent v-if="hasSubSteps" value="sub-steps" class="flex-1 min-h-0 mt-0">
            <ScrollArea class="h-full">
              <div class="px-6 py-4">
                <SubStepDetailTab
                  :node-execution-id="nodeExecution!.id"
                  :focus-step-id="focusSubStepId"
                />
              </div>
            </ScrollArea>
          </TabsContent>

          <!-- AI 透视 Tab（仅 AI 节点） -->
          <TabsContent v-if="isAINode" value="ai-insight" class="flex-1 min-h-0 mt-0">
            <ScrollArea class="h-full">
              <div class="px-6 py-4">
                <AIInsightTab
                  :node-execution-id="nodeExecution.id"
                  :execution-id="executionId"
                  :node-id="nodeExecution.node"
                />
              </div>
            </ScrollArea>
          </TabsContent>
        </Tabs>
      </div>

      <!-- 空状态 -->
      <div v-else class="flex-1 flex items-center justify-center text-muted-foreground text-sm">
        请选择一个节点查看详情
      </div>
    </SheetContent>
  </Sheet>
</template>
