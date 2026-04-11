<script setup lang="ts">
import type { PromptDetail } from '~/types/prompts'
/**
 * PromptMetadataForm — Prompt 基础信息表单
 *
 * 职责:
 * 在 Sheet「基础信息」Tab 中承载可写字段(title / description)的
 * vee-validate + zod 校验,并将只读字段(slug / category / scope /
 * is_builtin / updated_at)以徽章或本地化时间戳的形式呈现。
 *
 * 校验契约(与 交付的 PromptUpdateInputSchema 对齐):
 * - title 非空 + max 200
 * - description max 1000 + 默认空串
 *
 * 表单值变化通过 update:values 事件向上冒泡给 PromptEditor 容器( 整合)。
 *
 * 只读字段 Label / 徽章文案严格对齐 work-item item.md §Copywriting §Color 表。
 */
import { toTypedSchema } from '@vee-validate/zod'
import { useForm } from 'vee-validate'
import { watch } from 'vue'
import * as z from 'zod'
import { Badge } from '~/components/ui/badge'
import {
 FormControl,
 FormField,
 FormItem,
 FormLabel,
 FormMessage,
} from '~/components/ui/form'
import { Input } from '~/components/ui/input'
import { Textarea } from '~/components/ui/textarea'
const props = defineProps<{
 prompt: PromptDetail | null
 mode: 'edit' | 'create'
}>
const emit = defineEmits<{
 'update:values': [values: { title: string, description: string }]
}>
// 表单 schema —— 与 PromptUpdateInputSchema 字段语义对齐,错误消息中文化
// zod v4 兼容性说明:
// 1. `.default('')` 禁用 —— @vee-validate/zod 的 resolveInitialValues 会调用
// 旧版 `_def.defaultValue` API 触发 TypeError。改用外层 initialValues 注入空串。
// 2. `required_error` option 在 zod v4 已废除,min(1) 返回的错误文案兜底覆盖
// 空串必填场景。
const formSchema = toTypedSchema(z.object({
 title: z
 .string
 .min(1, '请输入标题')
 .max(200, '标题最长 200 字符'),
 description: z
 .string
 .max(1000, '描述最长 1000 字符'),
}))
const { values, setFieldValue } = useForm({
 validationSchema: formSchema,
 initialValues: {
 title: props.prompt?.title ?? '',
 description: props.prompt?.description ?? '',
 },
})
// 父组件切换到其他 Prompt 时同步初值
watch( => props.prompt, (p) => {
 if (p) {
 setFieldValue('title', p.title)
 setFieldValue('description', p.description)
 }
}, { immediate: false })
// 表单值变化向上冒泡
watch(values, (v) => {
 emit('update:values', {
 title: v.title ?? '',
 description: v.description ?? '',
 })
}, { deep: true })
// ============================================================================
// 只读字段展示映射(与 work-item item.md §Color 徽章表严格对齐)
// ============================================================================
interface CategoryLabelEntry { label: string, variant: 'default' | 'secondary' }
const CATEGORY_LABEL: Record<string, CategoryLabelEntry> = {
 chat_agent: { label: '对话', variant: 'default' },
 ai_node: { label: 'AI 节点', variant: 'secondary' },
 aux_model: { label: '辅助小模型', variant: 'secondary' },
 feishu_bot: { label: '飞书群聊', variant: 'secondary' },
 repo_summary: { label: '仓库描述', variant: 'secondary' },
}
const SCOPE_LABEL: Record<string, string> = {
 system: '系统级',
 project: '项目级',
}
</script>
<template>
 <form class="space-y-4">
 <!-- 只读元信息区 -->
 <div v-if="prompt" class="card space-y-3">
 <div class="flex items-center justify-between">
 <span class="text-xs text-muted-foreground">Slug</span>
 <code class="text-xs font-mono text-foreground">{{ prompt.slug }}</code>
 </div>
 <div class="flex items-center justify-between">
 <span class="text-xs text-muted-foreground">分类</span>
 <Badge:variant="CATEGORY_LABEL[prompt.category]?.variant ?? 'secondary'">
 {{ CATEGORY_LABEL[prompt.category]?.label ?? prompt.category }}
 </Badge>
 </div>
 <div class="flex items-center justify-between">
 <span class="text-xs text-muted-foreground">范围</span>
 <Badge variant="outline">
 {{ SCOPE_LABEL[prompt.scope] ?? prompt.scope }}
 </Badge>
 </div>
 <div v-if="prompt.is_builtin" class="flex items-center justify-between">
 <span class="text-xs text-muted-foreground">系统内置</span>
 <Badge variant="secondary">
 系统内置
 </Badge>
 </div>
 <div class="flex items-center justify-between">
 <span class="text-xs text-muted-foreground">最后更新</span>
 <span class="text-xs text-foreground">
 {{ new Date(prompt.updated_at).toLocaleString('zh-CN') }}
 </span>
 </div>
 </div>
 <!-- 可写字段 -->
 <FormField v-slot="{ componentField }" name="title">
 <FormItem>
 <FormLabel>标题</FormLabel>
 <FormControl>
 <Input v-bind="componentField" placeholder="请输入 Prompt 标题" />
 </FormControl>
 <FormMessage />
 </FormItem>
 </FormField>
 <FormField v-slot="{ componentField }" name="description">
 <FormItem>
 <FormLabel>描述</FormLabel>
 <FormControl>
 <Textarea
 v-bind="componentField":rows="3"
 placeholder="可选:用一两句话描述此 Prompt 的用途"
 />
 </FormControl>
 <FormMessage />
 </FormItem>
 </FormField>
 </form>
</template>
