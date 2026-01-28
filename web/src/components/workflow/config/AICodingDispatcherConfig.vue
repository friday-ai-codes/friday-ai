<script setup lang="ts">
import type { AICodingDispatcherConfig } from '~/types/workflow'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from '~/components/ui/select'
import { Switch } from '~/components/ui/switch'
import { useConfigModel } from '~/composables/useConfigModel'
import {
 AI_MODELS,
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
const analysisModel = field('analysis_model', 'claude-3-5-sonnet-20241022')
const maxTasks = field('max_tasks', 5)
const taskGranularity = field('task_granularity', 'medium')
const includeTests = field('include_tests', true)
const autoAssignRepos = field('auto_assign_repos', true)
</script>
<template>
 <div class="space-y-4">
 <!-- 分析模型 -->
 <div class="space-y-2">
 <Label>分析模型</Label>
 <Select v-model="analysisModel">
 <SelectTrigger>
 <SelectValue placeholder="选择模型" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem
 v-for="option in AI_MODELS":key="option.value":value="option.value"
 >
 {{ option.label }}
 </SelectItem>
 </SelectContent>
 </Select>
 <p class="text-xs text-muted-foreground">
 用于分析需求文档并生成编码任务
 </p>
 </div>
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
 <div class="text-xs text-muted-foreground">{{ option.description }}</div>
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
 <Switch v-model:checked="includeTests" />
 </div>
 <div class="flex items-center justify-between">
 <div>
 <Label>自动分配仓库</Label>
 <p class="text-xs text-muted-foreground">
 根据需求自动判断应修改哪些仓库
 </p>
 </div>
 <Switch v-model:checked="autoAssignRepos" />
 </div>
 </div>
 <!-- 说明 -->
 <div class="mt-4 bg-secondary/50 rounded-md text-sm space-y-1">
 <p class="font-medium">此节点将：</p>
 <ul class="text-xs text-muted-foreground space-y-1 list-disc list-inside">
 <li>从全局参数读取需求文档 URL 和描述</li>
 <li>抓取需求文档内容进行分析</li>
 <li>生成编码任务并分配到对应仓库</li>
 <li>创建 CodingTask 记录供后续处理</li>
 </ul>
 </div>
 </div>
</template>
