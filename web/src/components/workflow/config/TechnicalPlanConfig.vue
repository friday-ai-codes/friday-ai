<script setup lang="ts">
import type { TechnicalPlanNodeConfig } from '~/types/workflow/schemas'
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
import { Switch } from '~/components/ui/switch'
import { Textarea } from '~/components/ui/textarea'
import AIModelConfig from '~/components/workflow/config/AIModelConfig.vue'
import VariablePicker from '~/components/workflow/VariablePicker.vue'
import { useConfigModel } from '~/composables/useConfigModel'
import { technicalPlanNodeConfigSchema } from '~/types/workflow/schemas'
// ============================================================================
// Props & Emits
// ============================================================================
interface Props {
 config: TechnicalPlanNodeConfig
}
const props = defineProps<Props>
const emit = defineEmits<{
 (e: 'update:config', value: TechnicalPlanNodeConfig): void
}>
// ============================================================================
// Config Model
// ============================================================================
const { field } = useConfigModel({
 config: => props.config,
 emit: v => emit('update:config', v),
 schema: technicalPlanNodeConfigSchema,
})
// API 配置
const useCustomApi = computed({
 get: => props.config.use_custom_api ?? false,
 set: v => emit('update:config', { ...props.config, use_custom_api: v }),
})
const apiBaseUrl = field('api_base_url', '')
const apiKey = field('api_key', '')
const model = field('model', '')
// Context input
const codebaseContext = field('codebase_context', '')
// 生成配置
const generationMode = field('generation_mode', 'outline_first')
const includeFileDetails = field('include_file_details', true)
const maxTasks = field('max_tasks', 20)
const maxRetries = field('max_retries', 3)
// Slider 需要数组格式的特殊处理
const temperature = computed({
 get: => [props.config.temperature ?? 0.3],
 set: v => emit('update:config', { ...props.config, temperature: v[0] }),
})
// 飞书回写配置
const feishuFieldKey = field('feishu_field_key', '')
const autoTransitionStatus = field('auto_transition_status', true)
const targetStatus = field('target_status', '待审核')
// 生成模式选项
const GENERATION_MODE_OPTIONS = [
 { value: 'outline_first', label: '先生成大纲', description: '先生成大纲，确认后生成详细内容' },
 { value: 'full', label: '完整生成', description: '直接生成完整技术方案' },
] as const
</script>
<template>
 <div class="space-y-4">
 <!-- AI 模型配置（通用组件） -->
 <AIModelConfig
 v-model:use-custom-api="useCustomApi"
 v-model:api-base-url="apiBaseUrl"
 v-model:api-key="apiKey"
 v-model:model="model"
 model-label="生成模型"
 model-description="用于生成技术方案的 AI 模型"
 />
 <Separator />
 <!-- 代码库上下文 -->
 <div class="space-y-2">
 <Label>代码库上下文</Label>
 <Textarea
 v-model="codebaseContext"
 placeholder="从上下文召回节点获取，如 {{ nodes.context_retrieval.formatted_context }}"
 rows="4"
 class="font-mono text-sm"
 />
 <div class="flex items-center justify-between">
 <p class="text-xs text-muted-foreground">
 相关代码上下文，辅助 AI 生成更准确的技术方案
 </p>
 <VariablePicker @select="v => codebaseContext += v" />
 </div>
 </div>
 <Separator />
 <!-- 生成配置 -->
 <div class="space-y-4">
 <h4 class="text-sm font-medium">
 生成配置
 </h4>
 <!-- 生成模式 -->
 <div class="space-y-2">
 <Label>生成模式</Label>
 <Select v-model="generationMode">
 <SelectTrigger>
 <SelectValue placeholder="选择生成模式" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem
 v-for="option in GENERATION_MODE_OPTIONS":key="option.value":value="option.value"
 >
 <div>
 <div>{{ option.label }}</div>
 <div class="text-xs text-muted-foreground">
 {{ option.description }}
 </div>
 </div>
 </SelectItem>
 </SelectContent>
 </Select>
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
 v-model="temperature":min="0":max="1":step="0.1"
 class="w-full"
 />
 <p class="text-xs text-muted-foreground">
 较低值输出更确定，较高值更有创造性（建议 0.2-0.4）
 </p>
 </div>
 <!-- 最大任务数 -->
 <div class="space-y-2">
 <Label>最大任务数</Label>
 <Input
 v-model="maxTasks"
 type="number":min="1":max="50"
 />
 <p class="text-xs text-muted-foreground">
 技术方案中最多包含的任务数量
 </p>
 </div>
 <!-- 最大重试次数 -->
 <div class="space-y-2">
 <Label>最大重试次数</Label>
 <Input
 v-model="maxRetries"
 type="number":min="1":max="5"
 />
 <p class="text-xs text-muted-foreground">
 生成失败时的重试次数
 </p>
 </div>
 <!-- 开关选项 -->
 <div class="flex items-center justify-between">
 <div>
 <Label>包含文件详情</Label>
 <p class="text-xs text-muted-foreground">
 在方案中包含具体的文件修改建议
 </p>
 </div>
 <Switch v-model="includeFileDetails" />
 </div>
 </div>
 <Separator />
 <!-- 飞书回写配置 -->
 <div class="space-y-4">
 <h4 class="text-sm font-medium">
 飞书回写配置
 </h4>
 <!-- 目标字段 -->
 <div class="space-y-2">
 <Label>目标字段 Key</Label>
 <Input
 v-model="feishuFieldKey"
 placeholder="field_xxx"
 />
 <p class="text-xs text-muted-foreground">
 技术方案将写入此飞书字段（留空则不回写）
 </p>
 </div>
 <!-- 自动流转状态 -->
 <div class="flex items-center justify-between">
 <div>
 <Label>自动流转状态</Label>
 <p class="text-xs text-muted-foreground">
 生成完成后自动更新工作项状态
 </p>
 </div>
 <Switch v-model="autoTransitionStatus" />
 </div>
 <!-- 目标状态 -->
 <div v-if="autoTransitionStatus" class="space-y-2">
 <Label>目标状态</Label>
 <Input
 v-model="targetStatus"
 placeholder="待审核"
 />
 <p class="text-xs text-muted-foreground">
 生成完成后将工作项流转到此状态
 </p>
 </div>
 </div>
 <!-- 说明 -->
 <div class="mt-4 bg-secondary/50 rounded-md text-sm space-y-1">
 <p class="font-medium">
 此节点将：
 </p>
 <ul class="text-xs text-muted-foreground space-y-1 list-disc list-inside">
 <li>从全局参数读取需求描述和相关上下文</li>
 <li>使用 AI 模型生成技术方案</li>
 <li>将方案写入飞书工作项指定字段</li>
 <li>可选择自动流转工作项状态</li>
 </ul>
 </div>
 </div>
</template>
