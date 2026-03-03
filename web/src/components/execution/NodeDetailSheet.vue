<script setup lang="ts">
/**
 * NodeDetailSheet -- 节点详情右侧抽屉面板
 *
 * 从右侧滑出的抽屉面板，包含三个 Tab：概览、数据、配置。
 * 根据节点类型和状态，在概览 Tab 底部条件渲染 AI/审批/调试面板。
 */
import { computed } from 'vue'
import type { NodeExecution } from '~/stores/useExecutionsStore'
import {
 Sheet,
 SheetContent,
 SheetDescription,
 SheetHeader,
 SheetTitle,
} from '~/components/ui/sheet'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '~/components/ui/tabs'
import { ScrollArea } from '~/components/ui/scroll-area'
import { Separator } from '~/components/ui/separator'
import NodeOverviewTab from './NodeOverviewTab.vue'
import NodeDataTab from './NodeDataTab.vue'
import NodeConfigTab from './NodeConfigTab.vue'
import PlanApprovalPanel from './PlanApprovalPanel.vue'
import AICodingPanel from './AICodingPanel.vue'
import AICodeReviewPanel from './AICodeReviewPanel.vue'
import NodeDebugPanel from './NodeDebugPanel.vue'
const props = defineProps<{
 open: boolean
 nodeExecution: NodeExecution | null
 nodeConfig: Record<string, unknown>
 bottleneckInfo?: { level: string; rank: number; durationPercent: number } | null
 executionId: string
}>
const emit = defineEmits<{
 'update:open': [value: boolean]
 'action-complete':
}>
/** 当前节点类型 */
const nodeType = computed( => props.nodeExecution?.node_type ?? '')
/** 当前节点状态 */
const nodeStatus = computed( => props.nodeExecution?.status ?? '')
/** 是否显示 PlanApprovalPanel：ai_plan_approval + waiting_event/completed */
const showPlanApproval = computed( =>
 nodeType.value === 'ai_plan_approval'
 && ['waiting_event', 'completed'].includes(nodeStatus.value),
)
/** 是否显示 AICodingPanel：ai_coding + running/waiting_event/completed */
const showAICoding = computed( =>
 nodeType.value === 'ai_coding'
 && ['running', 'waiting_event', 'completed'].includes(nodeStatus.value),
)
/** 是否显示 AICodeReviewPanel：ai_code_review + running/completed/failed */
const showAICodeReview = computed( =>
 nodeType.value === 'ai_code_review'
 && ['running', 'completed', 'failed'].includes(nodeStatus.value),
)
/** 是否显示 NodeDebugPanel：所有 running/waiting_event/completed/failed 状态 */
const showDebugPanel = computed( =>
 ['running', 'waiting_event', 'completed', 'failed'].includes(nodeStatus.value),
)
/** 是否有任何附加面板需要显示 */
const hasExtraPanels = computed( =>
 showPlanApproval.value || showAICoding.value || showAICodeReview.value || showDebugPanel.value,
)
function handleOpenChange(value: boolean) {
 emit('update:open', value)
}
function handleActionComplete {
 emit('action-complete')
}
</script>
<template>
 <Sheet:open="open" @update:open="handleOpenChange">
 <SheetContent side="right" class="w-[450px] sm:max-w-[450px] flex flex-col">
 <!-- Header -->
 <SheetHeader class="px-6 pt-6 pb-4 border-b border-border/50 shrink-0">
 <SheetTitle class="text-base">
 {{ nodeExecution?.node_name ?? '节点详情' }}
 </SheetTitle>
 <SheetDescription>
 {{ nodeExecution?.node_type ?? '' }}
 </SheetDescription>
 </SheetHeader>
 <!-- Tabs 内容区域 -->
 <div v-if="nodeExecution" class="flex-1 min-">
 <Tabs default-value="overview" class="h-full flex flex-col">
 <TabsList class="w-full shrink-0 mx-6 mt-4" style="width: calc(100% - 3rem)">
 <TabsTrigger value="overview" class="flex-1">
 概览
 </TabsTrigger>
 <TabsTrigger value="data" class="flex-1">
 数据
 </TabsTrigger>
 <TabsTrigger value="config" class="flex-1">
 配置
 </TabsTrigger>
 </TabsList>
 <!-- 概览 Tab -->
 <TabsContent value="overview" class="flex-1 min- mt-0">
 <ScrollArea class="h-full">
 <div class="px-6 py-4 space-y-4">
 <NodeOverviewTab:node-execution="nodeExecution":bottleneck-info="bottleneckInfo"
 />
 <!-- 条件渲染：AI / 审批 / 调试面板 -->
 <template v-if="hasExtraPanels">
 <Separator />
 <!-- AI 方案审批面板 -->
 <PlanApprovalPanel
 v-if="showPlanApproval":node-execution="nodeExecution"
 @action-complete="handleActionComplete"
 />
 <!-- AI 编码面板 -->
 <AICodingPanel
 v-if="showAICoding":node-execution="nodeExecution"
 />
 <!-- AI 代码审查面板 -->
 <AICodeReviewPanel
 v-if="showAICodeReview":node-execution="nodeExecution"
 />
 <!-- 调试交互面板 -->
 <NodeDebugPanel
 v-if="showDebugPanel":node-execution-id="nodeExecution.id":output-data="nodeExecution.output_data":node-status="nodeExecution.status"
 @answered="handleActionComplete"
 />
 </template>
 </div>
 </ScrollArea>
 </TabsContent>
 <!-- 数据 Tab -->
 <TabsContent value="data" class="flex-1 min- mt-0">
 <ScrollArea class="h-full">
 <div class="px-6 py-4">
 <NodeDataTab:node-execution="nodeExecution" />
 </div>
 </ScrollArea>
 </TabsContent>
 <!-- 配置 Tab -->
 <TabsContent value="config" class="flex-1 min- mt-0">
 <ScrollArea class="h-full">
 <div class="px-6 py-4">
 <NodeConfigTab:config="nodeConfig" />
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
