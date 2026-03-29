<script setup lang="ts">
import type { FetchWorkItemConfig, WorkflowEdgeStore, WorkflowNodeStore } from '~/types/workflow'
import { computed, onMounted } from 'vue'
import { Button } from '~/components/ui/button'
import { Label } from '~/components/ui/label'
import {
 Popover,
 PopoverContent,
 PopoverTrigger,
} from '~/components/ui/popover'
import SmartInput from '~/components/workflow/smart-input/SmartInput.vue'
import { useConfigModel } from '~/composables/useConfigModel'
import { fetchWorkItemConfigSchema } from '~/types/workflow'
// ============================================================================
// Props & Emits
// ============================================================================
interface Props {
 config: FetchWorkItemConfig
 workflowNodes?: WorkflowNodeStore
 workflowEdges?: WorkflowEdgeStore
 currentNodeId?: string
}
const props = withDefaults(defineProps<Props>, {
 workflowNodes: =>,
 workflowEdges: =>,
 currentNodeId: '',
})
const emit = defineEmits<{
 (e: 'update:config', value: FetchWorkItemConfig): void
}>
// ============================================================================
// Config Model
// ============================================================================
const { field } = useConfigModel({
 config: => props.config,
 emit: v => emit('update:config', v),
 schema: fetchWorkItemConfigSchema,
})
const workItemId = field('work_item_id', '')
// ============================================================================
// 自动填充检测
// ============================================================================
// 找到上游的飞书事件触发器节点
const upstreamFeishuTrigger = computed( => {
 // 找到当前节点的所有上游节点
 const upstreamNodeIds = new Set<string>
 function findUpstream(nodeId: string) {
 for (const edge of props.workflowEdges) {
 if (edge.target === nodeId && !upstreamNodeIds.has(edge.source)) {
 upstreamNodeIds.add(edge.source)
 findUpstream(edge.source)
 }
 }
 }
 findUpstream(props.currentNodeId)
 // 返回第一个飞书事件触发器节点
 return props.workflowNodes.find(
 node => upstreamNodeIds.has(node.id) && node.nodeType === 'feishu_event_trigger',
 )
})
// 检测上游是否有飞书事件触发器
const hasFeishuTriggerUpstream = computed( => !!upstreamFeishuTrigger.value)
// 生成变量路径
// 使用 input.work_item_id 因为调度器会自动将上游输出合并到下游 input_data
const triggerWorkItemIdPath = computed( => {
 if (!upstreamFeishuTrigger.value)
 return ''
 return 'input.work_item_id'
})
// 检测是否需要显示自动填充提示
const showAutoFillHint = computed( => {
 return hasFeishuTriggerUpstream.value && !workItemId.value
})
// 检测是否已经填充了触发器变量
const isFilledWithTriggerVar = computed( => {
 if (!triggerWorkItemIdPath.value)
 return false
 return workItemId.value.includes(`{{${triggerWorkItemIdPath.value}}}`)
})
// 自动填充
function autoFill {
 if (triggerWorkItemIdPath.value) {
 workItemId.value = `{{${triggerWorkItemIdPath.value}}}`
 }
}
// 组件挂载时自动填充（如果为空且有上游触发器）
onMounted( => {
 if (showAutoFillHint.value) {
 autoFill
 }
})
// 变量语法示例
const variableSyntaxExamples = [
 { syntax: '{{input.xxx}}', desc: '上游节点输出', color: 'text-primary' },
 { syntax: '{{global.xxx}}', desc: '全局参数', color: 'text-green-500' },
 { syntax: '{{trigger.xxx}}', desc: '触发器数据', color: 'text-amber-500' },
 { syntax: '{{nodes.id.xxx}}', desc: '指定节点输出', color: 'text-purple-500' },
]
</script>
<template>
 <div class="space-y-4">
 <!-- 工作项 ID -->
 <div class="space-y-2">
 <Label class="flex items-center gap-2">
 工作项 ID
 <span class="text-destructive">*</span>
 </Label>
 <!-- 自动填充提示 -->
 <div
 v-if="showAutoFillHint"
 class="flex items-center gap-2 rounded-lg bg-primary/10 border border-primary/20"
 >
 <span class="icon-[lucide--lightbulb] text-primary" />
 <span class="text-xs text-primary flex-1">
 检测到上游有飞书事件触发器
 </span>
 <Button
 variant="ghost"
 size="sm"
 class=" text-xs text-primary hover:text-primary hover:bg-primary/20"
 @click="autoFill"
 >
 自动填充
 </Button>
 </div>
 <!-- 已填充状态 -->
 <div
 v-if="isFilledWithTriggerVar"
 class="flex items-center gap-2 text-xs text-green-600 dark:text-green-400"
 >
 <span class="icon-[lucide--check-circle]" />
 <span>已关联飞书事件触发器的工作项 ID</span>
 </div>
 <SmartInput
 v-model="workItemId":workflow-nodes="workflowNodes":workflow-edges="workflowEdges":current-node-id="currentNodeId"
 placeholder="输入工作项 ID 或输入 {{ 选择变量..."
 />
 <p class="text-xs text-muted-foreground flex items-center gap-1">
 <span>输入 <code class="bg-muted px-1 py-0.5 rounded font-mono">{{ '{{' }}</code> 触发变量联想</span>
 <Popover>
 <PopoverTrigger as-child>
 <button
 type="button"
 class="inline-flex items-center justify-center w-4 rounded-full bg-muted hover:bg-muted/80 transition-colors"
 >
 <span class="icon-[lucide--help-circle] text-xs text-muted-foreground" />
 </button>
 </PopoverTrigger>
 <PopoverContent class="w-80 " align="start">
 <div class="space-y-3">
 <div class="flex items-center gap-2 text-sm font-medium">
 <span class="icon-[lucide--variable] text-primary" />
 变量语法说明
 </div>
 <div class="text-xs text-muted-foreground space-y-2">
 <p>在配置中使用变量引用动态值：</p>
 <div class="space-y-1.5 font-mono text-[11px]">
 <div
 v-for="example in variableSyntaxExamples":key="example.syntax"
 class="flex items-start gap-2"
 >
 <code class="shrink-0":class="example.color">{{ example.syntax }}</code>
 <span class="text-muted-foreground">{{ example.desc }}</span>
 </div>
 </div>
 <p class="pt-1 border-t border-border/50 text-muted-foreground/80">
 输入 <code class="bg-muted px-1 rounded">{{ '{{' }}</code> 后会自动弹出可用变量列表
 </p>
 </div>
 </div>
 </PopoverContent>
 </Popover>
 </p>
 </div>
 </div>
</template>
