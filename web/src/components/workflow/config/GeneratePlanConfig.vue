<script setup lang="ts">
import type { GeneratePlanConfig } from '~/types/workflow/schemas'
import { computed } from 'vue'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { Separator } from '~/components/ui/separator'
import { Slider } from '~/components/ui/slider'
import { Switch } from '~/components/ui/switch'
import { Textarea } from '~/components/ui/textarea'
import AIModelConfig from '~/components/workflow/config/AIModelConfig.vue'
import RepositoryPicker from '~/components/workflow/RepositoryPicker.vue'
import VariablePicker from '~/components/workflow/VariablePicker.vue'
import { useConfigModel } from '~/composables/useConfigModel'
import { generatePlanConfigSchema } from '~/types/workflow/schemas'
// ============================================================================
// Props & Emits
// ============================================================================
interface Props {
 config: GeneratePlanConfig
 repositories?: Array<{ id: string, name: string }>
}
const props = withDefaults(defineProps<Props>, {
 repositories: =>,
})
const emit = defineEmits<{
 (e: 'update:config', value: GeneratePlanConfig): void
}>
// ============================================================================
// Config Model
// ============================================================================
const { field } = useConfigModel({
 config: => props.config,
 emit: v => emit('update:config', v),
 schema: generatePlanConfigSchema,
})
// Repositories
const repositories = computed({
 get: => props.config.repositories ??,
 set: (val: string) => emit('update:config', { ...props.config, repositories: val }),
})
// Context fields
const codebaseContext = field('codebase_context', '')
const requirementText = field('requirement_text', '')
// AI config
const useCustomApi = computed({
 get: => props.config.use_custom_api ?? false,
 set: v => emit('update:config', { ...props.config, use_custom_api: v }),
})
const apiBaseUrl = field('api_base_url', '')
const apiKey = field('api_key', '')
const model = field('model', 'claude-sonnet-4-20250514')
// Generation settings
const maxTasks = field('max_tasks', 15)
const includeFileDetails = field('include_file_details', true)
// Temperature (slider needs array format)
const temperature = computed({
 get: => [props.config.temperature ?? 0.3],
 set: v => emit('update:config', { ...props.config, temperature: v[0] }),
})
</script>
<template>
 <div class="space-y-4">
 <!-- 目标仓库 -->
 <div class="space-y-2">
 <Label class="flex items-center gap-1">
 目标仓库
 </Label>
 <RepositoryPicker
 v-model="repositories":repositories="props.repositories"
 placeholder="选择相关代码仓库..."
 />
 <p class="text-xs text-muted-foreground">
 选择与方案相关的代码仓库，用于生成更准确的文件修改建议
 </p>
 </div>
 <Separator />
 <!-- 输入内容 -->
 <div class="space-y-4">
 <!-- 需求描述 -->
 <div class="space-y-2">
 <Label class="flex items-center gap-1">
 需求描述
 <span class="text-destructive">*</span>
 </Label>
 <div class="flex gap-2">
 <Textarea
 v-model="requirementText"
 placeholder="需求描述或 {{ global.requirement_text }}"
 rows="3"
 class="flex-1"
 />
 </div>
 <div class="flex items-center justify-between">
 <p class="text-xs text-muted-foreground">
 要生成方案的需求内容，支持模板变量
 </p>
 <VariablePicker @select="v => requirementText += v" />
 </div>
 </div>
 <!-- 代码库上下文 -->
 <div class="space-y-2">
 <Label>代码库上下文</Label>
 <div class="flex gap-2">
 <Textarea
 v-model="codebaseContext"
 placeholder="从上下文召回节点获取，如 {{ nodes.context_retrieval.formatted_context }}"
 rows="4"
 class="font-mono text-sm flex-1"
 />
 </div>
 <div class="flex items-center justify-between">
 <p class="text-xs text-muted-foreground">
 相关代码上下文，辅助 AI 生成更准确的方案
 </p>
 <VariablePicker @select="v => codebaseContext += v" />
 </div>
 </div>
 </div>
 <Separator />
 <!-- AI 模型配置 -->
 <AIModelConfig
 v-model:use-custom-api="useCustomApi"
 v-model:api-base-url="apiBaseUrl"
 v-model:api-key="apiKey"
 v-model:model="model"
 model-label="生成模型"
 model-description="用于生成开发方案的 AI 模型"
 />
 <Separator />
 <!-- 生成配置 -->
 <div class="space-y-4">
 <h4 class="text-sm font-medium">生成配置</h4>
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
 方案中最多包含的任务数量
 </p>
 </div>
 <!-- 包含文件详情 -->
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
 <!-- 输出变量说明 -->
 <div class="rounded-lg bg-muted/50 space-y-2">
 <p class="text-xs font-medium text-muted-foreground flex items-center gap-1">
 <span class="icon-[lucide--code] text-cyan-500" />
 输出变量
 </p>
 <div class="bg-muted rounded-lg space-y-1.5 text-xs">
 <div class="flex gap-2">
 <code class="bg-background px-1.5 py-0.5 rounded min-w-40">$.plan</code>
 <span class="text-muted-foreground">生成的开发方案（Markdown）</span>
 </div>
 <div class="flex gap-2">
 <code class="bg-background px-1.5 py-0.5 rounded min-w-40">$.tasks</code>
 <span class="text-muted-foreground">拆分的任务列表</span>
 </div>
 <div class="flex gap-2">
 <code class="bg-background px-1.5 py-0.5 rounded min-w-40">$.file_changes</code>
 <span class="text-muted-foreground">预计修改的文件列表</span>
 </div>
 </div>
 </div>
 </div>
</template>
