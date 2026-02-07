<script setup lang="ts">
import type { WorkflowEdge, WorkflowNode } from '~/types/workflow/store'
import type { AIPromptConfig } from '~/types/workflow'
import { computed } from 'vue'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from '~/components/ui/select'
import { Separator } from '~/components/ui/separator'
import { Slider } from '~/components/ui/slider'
import AIModelConfig from '~/components/workflow/config/AIModelConfig.vue'
import { SmartTextarea } from '~/components/workflow/smart-input'
import { useConfigModel } from '~/composables/useConfigModel'
import {
 aiPromptConfigSchema,
 OUTPUT_FORMATS,
} from '~/types/workflow'
// ============================================================================
// Props & Emits
// ============================================================================
interface Props {
 config: AIPromptConfig
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
 (e: 'update:config', value: AIPromptConfig): void
}>
// ============================================================================
// Config Model
// ============================================================================
const { field } = useConfigModel({
 config: => props.config,
 emit: v => emit('update:config', v),
 schema: aiPromptConfigSchema,
})
// API 配置
const useCustomApi = computed({
 get: => props.config.use_custom_api ?? false,
 set: v => emit('update:config', { ...props.config, use_custom_api: v }),
})
const apiBaseUrl = field('api_base_url', '')
const apiKey = field('api_key', '')
const model = field('model', 'claude-sonnet-4-20250514')
// 提示词配置
const systemPrompt = field('system_prompt', '')
const userPrompt = field('user_prompt', '')
const maxTokens = field('max_tokens', 4096)
const outputFormat = field('output_format', 'text')
// Slider 需要数组格式的特殊处理
const temperature = computed({
 get: => [props.config.temperature ?? 0.7],
 set: v => emit('update:config', { ...props.config, temperature: v[0] }),
})
</script>
<template>
 <div class="space-y-4">
 <!-- AI 模型配置（通用组件） -->
 <AIModelConfig
 v-model:use-custom-api="useCustomApi"
 v-model:api-base-url="apiBaseUrl"
 v-model:api-key="apiKey"
 v-model:model="model"
 />
 <Separator />
 <!-- System Prompt -->
 <div class="space-y-2">
 <Label>系统提示词</Label>
 <SmartTextarea
 v-model="systemPrompt":workflow-nodes="workflowNodes":workflow-edges="workflowEdges":current-node-id="currentNodeId"
 placeholder="设定 AI 的角色和行为规范...":min-rows="3"
 />
 <p class="text-xs text-muted-foreground">
 定义 AI 的角色、能力范围和输出要求
 </p>
 </div>
 <!-- User Prompt -->
 <div class="space-y-2">
 <Label class="flex items-center gap-2">
 用户提示词
 <span class="text-destructive">*</span>
 </Label>
 <SmartTextarea
 v-model="userPrompt":workflow-nodes="workflowNodes":workflow-edges="workflowEdges":current-node-id="currentNodeId"
 placeholder="输入 {{ 触发变量自动补全...":min-rows="4"
 />
 <p class="text-xs text-muted-foreground">
 输入 <code v-pre class="bg-muted px-1 py-0.5 rounded text-primary">{{</code> 触发变量自动补全
 </p>
 </div>
 <!-- 温度 -->
 <div class="space-y-2">
 <div class="flex items-center justify-between">
 <Label>温度 (Temperature)</Label>
 <span class="text-sm text-muted-foreground font-mono">
 {{ temperature[0].toFixed(1) }}
 </span>
 </div>
 <Slider
 v-model="temperature":min="0":max="2":step="0.1"
 class="w-full"
 />
 <p class="text-xs text-muted-foreground">
 较低值输出更确定，较高值更有创造性
 </p>
 </div>
 <!-- 最大 Token -->
 <div class="space-y-2">
 <Label>最大 Token 数</Label>
 <Input
 v-model="maxTokens"
 type="number":min="100":max="100000"
 />
 </div>
 <!-- 输出格式 -->
 <div class="space-y-2">
 <Label>输出格式</Label>
 <Select v-model="outputFormat">
 <SelectTrigger>
 <SelectValue placeholder="选择输出格式" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem
 v-for="option in OUTPUT_FORMATS":key="option.value":value="option.value"
 >
 {{ option.label }}
 </SelectItem>
 </SelectContent>
 </Select>
 <p class="text-xs text-muted-foreground">
 JSON 格式会自动解析为对象，便于后续节点使用
 </p>
 </div>
 </div>
</template>
