<script setup lang="ts">
import type { AICodingDispatcherConfig } from '~/types/workflow'
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
import { Switch } from '~/components/ui/switch'
import AIModelConfig from '~/components/workflow/config/AIModelConfig.vue'
import { useConfigModel } from '~/composables/useConfigModel'
import {
 aiCodingDispatcherConfigSchema,
 TASK_GRANULARITY_OPTIONS,
} from '~/types/workflow'
// ============================================================================
// Props & Emits
// ============================================================================
interface Props {
 config: AICodingDispatcherConfig
}
const props = defineProps<Props>
const emit = defineEmits<{
 (e: 'update:config', value: AICodingDispatcherConfig): void
}>
// ============================================================================
// Config Model
// ============================================================================
const { field } = useConfigModel({
 config: => props.config,
 emit: v => emit('update:config', v),
 schema: aiCodingDispatcherConfigSchema,
})
// API 配置
const useCustomApi = computed({
 get: => props.config.use_custom_api ?? false,
 set: v => emit('update:config', { ...props.config, use_custom_api: v }),
})
const apiBaseUrl = field('api_base_url', '')
const apiKey = field('api_key', '')
const analysisModel = field('analysis_model', 'claude-sonnet-4-20250514')
// 任务配置
const maxTasks = field('max_tasks', 5)
const taskGranularity = field('task_granularity', 'medium')
const includeTests = field('include_tests', true)
const autoAssignRepos = field('auto_assign_repos', true)
</script>
<template>
 <div class="space-y-4">
 <!-- AI 模型配置（通用组件） -->
 <AIModelConfig
 v-model:use-custom-api="useCustomApi"
 v-model:api-base-url="apiBaseUrl"
 v-model:api-key="apiKey"
 v-model:model="analysisModel"
 model-label="分析模型"
 model-description="用于分析需求文档并生成编码任务"
 />
 <Separator />
 <!-- 最大任务数 -->
 <div class="space-y-2">
 <Label>最大任务数</Label>
 <Input
 v-model="maxTasks"
 type="number":min="1":max="20"
 />
 <p class="text-xs text-muted-foreground">
 单次执行最多生成的编码任务数量
 </p>
 </div>
 <!-- 任务粒度 -->
 <div class="space-y-2">
 <Label>任务粒度</Label>
 <Select v-model="taskGranularity">
 <SelectTrigger>
 <SelectValue placeholder="选择粒度" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem
 v-for="option in TASK_GRANULARITY_OPTIONS":key="option.value":value="option.value"
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
 <!-- 开关选项 -->
 <div class="space-y-3 pt-2">
 <div class="flex items-center justify-between">
 <div>
 <Label>包含测试任务</Label>
 <p class="text-xs text-muted-foreground">
 为每个编码任务生成对应的测试任务
 </p>
 </div>
 <Switch v-model="includeTests" />
 </div>
 <div class="flex items-center justify-between">
 <div>
 <Label>自动分配仓库</Label>
 <p class="text-xs text-muted-foreground">
 根据需求自动判断应修改哪些仓库
 </p>
 </div>
 <Switch v-model="autoAssignRepos" />
 </div>
 </div>
 <!-- 说明 -->
 <div class="mt-4 bg-secondary/50 rounded-md text-sm space-y-1">
 <p class="font-medium">
 此节点将：
 </p>
 <ul class="text-xs text-muted-foreground space-y-1 list-disc list-inside">
 <li>从全局参数读取需求文档 URL 和描述</li>
 <li>抓取需求文档内容进行分析</li>
 <li>生成编码任务并分配到对应仓库</li>
 <li>创建 CodingTask 记录供后续处理</li>
 </ul>
 </div>
 </div>
</template>
