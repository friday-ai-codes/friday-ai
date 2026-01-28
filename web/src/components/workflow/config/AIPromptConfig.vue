<script setup lang="ts">
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
import { Slider } from '~/components/ui/slider'
import { Textarea } from '~/components/ui/textarea'
import { useConfigModel } from '~/composables/useConfigModel'
import {
 AI_MODELS,
 aiPromptConfigSchema,
 OUTPUT_FORMATS,
} from '~/types/workflow'
// ============================================================================
// Props & Emits
// ============================================================================
interface Props {
 config: AIPromptConfig
}
const props = defineProps<Props>
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
// 简单字段使用 field 一行搞定
const systemPrompt = field('system_prompt', '')
const userPrompt = field('user_prompt', '')
const model = field('model', 'claude-3-5-sonnet-20241022')
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
 <!-- System Prompt -->
 <div class="space-y-2">
 <Label>系统提示词</Label>
 <Textarea
 v-model="systemPrompt"
 placeholder="设定 AI 的角色和行为规范..."
 rows="3"
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
 <Textarea
 v-model="userPrompt"
 placeholder="{{global.description}}"
 rows="4"
 class="font-mono text-sm"
 />
 <p class="text-xs text-muted-foreground">
 支持模板变量：<code class="bg-secondary px-1 rounded">{{ '\{\{ global.xxx \}\}' }}</code>、
 <code class="bg-secondary px-1 rounded">{{ '\{\{ input.xxx \}\}' }}</code>、
 <code class="bg-secondary px-1 rounded">{{ '\{\{ nodes.nodeId.xxx \}\}' }}</code>
 </p>
 </div>
 <!-- 模型选择 -->
 <div class="space-y-2">
 <Label>模型</Label>
 <Select v-model="model">
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
