<script setup lang="ts">
import type { ContextRetrievalConfig } from '~/types/workflow'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { Separator } from '~/components/ui/separator'
import { SliderSingle } from '~/components/ui/slider'
import { Switch } from '~/components/ui/switch'
import { Textarea } from '~/components/ui/textarea'
import VariablePicker from '~/components/workflow/VariablePicker.vue'
import { useConfigModel } from '~/composables/useConfigModel'
import { contextRetrievalConfigSchema } from '~/types/workflow'
// ============================================================================
// Props & Emits
// ============================================================================
interface Props {
 config: ContextRetrievalConfig
}
const props = defineProps<Props>
const emit = defineEmits<{
 (e: 'update:config', value: ContextRetrievalConfig): void
}>
// ============================================================================
// Config Model
// ============================================================================
const { field } = useConfigModel({
 config: => props.config,
 emit: v => emit('update:config', v),
 schema: contextRetrievalConfigSchema,
})
const query = field('query', '')
const repositoryId = field('repository_id', '')
const topK = field('top_k', 10)
const scoreThreshold = field('score_threshold', 0.5)
const languageFilter = field('language_filter', '')
const includeContent = field('include_content', true)
const formatAsMarkdown = field('format_as_markdown', true)
// ============================================================================
// 语言选项
// ============================================================================
const languageOptions = [
 { value: '', label: '全部语言' },
 { value: 'python', label: 'Python' },
 { value: 'typescript', label: 'TypeScript' },
 { value: 'javascript', label: 'JavaScript' },
 { value: 'go', label: 'Go' },
 { value: 'java', label: 'Java' },
 { value: 'rust', label: 'Rust' },
 { value: 'vue', label: 'Vue' },
]
</script>
<template>
 <div class="space-y-4">
 <!-- 仓库 ID -->
 <div class="space-y-2">
 <Label class="flex items-center gap-1">
 仓库 ID
 <span class="text-destructive">*</span>
 </Label>
 <div class="flex gap-2">
 <Input
 v-model="repositoryId"
 placeholder="仓库 UUID 或 {{ context.repository_id }}"
 class="font-mono text-sm flex-1"
 />
 <VariablePicker @select="v => repositoryId = v" />
 </div>
 <p class="text-xs text-muted-foreground">
 指定要检索的代码仓库，支持模板变量
 </p>
 </div>
 <Separator />
 <!-- 检索查询 -->
 <div class="space-y-2">
 <Label class="flex items-center gap-1">
 检索查询
 <span class="text-destructive">*</span>
 </Label>
 <div class="flex gap-2">
 <Textarea
 v-model="query"
 placeholder="输入检索文本，如 {{ global.requirement_text }}"
 rows="3"
 class="font-mono text-sm flex-1"
 />
 </div>
 <div class="flex items-center justify-between">
 <p class="text-xs text-muted-foreground">
 根据此文本检索相关代码，支持模板变量
 </p>
 <VariablePicker @select="v => query += v" />
 </div>
 </div>
 <Separator />
 <!-- 检索参数 -->
 <div class="space-y-4">
 <Label>检索参数</Label>
 <!-- Top K -->
 <div class="space-y-2">
 <div class="flex items-center justify-between">
 <span class="text-sm">返回数量</span>
 <span class="text-sm font-mono bg-secondary px-2 py-0.5 rounded">{{ topK }}</span>
 </div>
 <SliderSingle
 v-model="topK":min="1":max="50":step="1"
 />
 <p class="text-xs text-muted-foreground">
 返回最相关的代码片段数量
 </p>
 </div>
 <!-- 相似度阈值 -->
 <div class="space-y-2">
 <div class="flex items-center justify-between">
 <span class="text-sm">相似度阈值</span>
 <span class="text-sm font-mono bg-secondary px-2 py-0.5 rounded">{{ scoreThreshold.toFixed(2) }}</span>
 </div>
 <SliderSingle:model-value="scoreThreshold * 100":min="0":max="100":step="5"
 @update:model-value="v => scoreThreshold = v / 100"
 />
 <p class="text-xs text-muted-foreground">
 过滤低于此分数的结果，0 表示不过滤
 </p>
 </div>
 <!-- 语言过滤 -->
 <div class="space-y-2">
 <Label>语言过滤</Label>
 <select
 v-model="languageFilter"
 class="w-full rounded-md border border-input bg-background px-3 text-sm"
 >
 <option v-for="opt in languageOptions":key="opt.value":value="opt.value">
 {{ opt.label }}
 </option>
 </select>
 <p class="text-xs text-muted-foreground">
 可选，仅检索指定编程语言的代码
 </p>
 </div>
 </div>
 <Separator />
 <!-- 输出选项 -->
 <div class="space-y-3">
 <Label>输出选项</Label>
 <div class="flex items-center justify-between">
 <div>
 <span class="text-sm">包含代码内容</span>
 <p class="text-xs text-muted-foreground">
 在结果中包含完整代码片段
 </p>
 </div>
 <Switch v-model:checked="includeContent" />
 </div>
 <div class="flex items-center justify-between">
 <div>
 <span class="text-sm">格式化为 Markdown</span>
 <p class="text-xs text-muted-foreground">
 输出带语法高亮的代码块
 </p>
 </div>
 <Switch v-model:checked="formatAsMarkdown" />
 </div>
 </div>
 <!-- 使用提示 -->
 <div class="rounded-lg bg-muted/50 space-y-2">
 <p class="text-xs text-muted-foreground">
 <span class="icon-[lucide--info] mr-1" />
 输出变量说明：
 </p>
 <ul class="text-xs text-muted-foreground space-y-1 ml-4">
 <li>
 <code v-pre class="bg-background px-1 rounded">{{ nodes.[id].formatted_context }}</code>
 - 格式化的 Markdown 文本
 </li>
 <li>
 <code v-pre class="bg-background px-1 rounded">{{ nodes.[id].contexts }}</code>
 - 原始检索结果数组
 </li>
 <li>
 <code v-pre class="bg-background px-1 rounded">{{ nodes.[id].total }}</code>
 - 结果数量
 </li>
 </ul>
 </div>
 </div>
</template>
