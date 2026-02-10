<script setup lang="ts">
import type { WorkflowEdge, WorkflowNode } from '~/types/workflow/store'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { useConfigModel } from '~/composables/useConfigModel'
/**
 * AIPlanApprovalConfig - 方案审批节点配置面板
 *
 * 配置项：
 * - chat_id: 飞书群聊 ID，用于发送审批卡片
 */
interface AIPlanApprovalConfig {
 chat_id: string
}
interface Props {
 config: AIPlanApprovalConfig
 workflowNodes?: WorkflowNode
 workflowEdges?: WorkflowEdge
 currentNodeId?: string
}
const props = withDefaults(defineProps<Props>, {
 workflowNodes: =>,
 workflowEdges: =>,
 currentNodeId: '',
})
const emit = defineEmits<{
 (e: 'update:config', value: AIPlanApprovalConfig): void
}>
const { field } = useConfigModel({
 config: => props.config as unknown as Record<string, unknown>,
 emit: v => emit('update:config', v as unknown as AIPlanApprovalConfig),
})
const chatId = field('chat_id', '') as import('vue').WritableComputedRef<string>
</script>
<template>
 <div class="space-y-4">
 <!-- Introduction -->
 <div class="rounded-xl bg-gradient-to-br from-amber-500/10 to-orange-400/5 border border-amber-500/20 ">
 <div class="flex items-start gap-2">
 <span class="icon-[lucide--check-circle] text-amber-500 text-lg shrink-0 mt-0.5" />
 <div class="space-y-1.5">
 <h4 class="text-sm font-medium">
 方案审批
 </h4>
 <p class="text-xs text-muted-foreground leading-relaxed">
 等待用户审批技术方案。支持
 <span class="text-emerald-600 font-medium">通过</span>
 和
 <span class="text-red-600 font-medium">驳回</span>
 两个分支输出。
 </p>
 <!-- Workflow Visual -->
 <div class="flex items-center gap-1 text-[10px] py-1.5 px-2 rounded-lg bg-muted/50">
 <span class="px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-600 font-medium">接收方案</span>
 <span class="icon-[lucide--arrow-right] text-muted-foreground" />
 <span class="px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-600 font-medium">飞书卡片</span>
 <span class="icon-[lucide--arrow-right] text-muted-foreground" />
 <span class="px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-600 font-medium">审批结果</span>
 </div>
 </div>
 </div>
 </div>
 <!-- Chat ID -->
 <div class="space-y-2">
 <Label class="flex items-center gap-1.5">
 <span class="icon-[lucide--message-circle] text-blue-500" />
 飞书群 ID
 </Label>
 <Input
 v-model="chatId"
 placeholder="输入飞书群 ID，用于发送审批卡片"
 class="bg-background/50"
 />
 <p class="text-xs text-muted-foreground">
 审批卡片将发送到此群，群内用户可直接审批。留空则使用上游节点传递的 chat_id。
 </p>
 </div>
 </div>
</template>
