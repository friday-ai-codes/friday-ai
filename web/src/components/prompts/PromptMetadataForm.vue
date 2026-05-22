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
 * 对于系统内置 Prompt(is_builtin=true),标题与描述属于代码契约的一部分
 * (见 server/prompts/migrations/0002_seed_system_defaults.py),
 * 前端将其降级为静态文本展示,**禁止编辑**;PromptEditor 在保存时也会
 * 跳过这两个字段,确保后端不会因 UI 误操作覆盖契约值。
 * 非内置 Prompt(用户创建的项目级覆盖等)保留原有编辑表单。
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
import { computed, watch } from 'vue'
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
import {
 getPromptUsage,
 getPromptUsageDomainIcon,
 getPromptUsageDomainLabel,
} from '~/config/promptUsage'
const props = defineProps<{
 prompt: PromptDetail | null
 mode: 'edit' | 'create'
}>
const emit = defineEmits<{
 'update:values': [values: { title: string, description: string }]
}>
// 表单 schema —— 与 PromptUpdateInputSchema 字段语义对齐,错误消息中文化
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
// 表单值变化向上冒泡(内置 Prompt 不参与编辑,但仍需将当前值上抛供 isDirty 比较)
watch(values, (v) => {
 emit('update:values', {
 title: v.title ?? '',
 description: v.description ?? '',
 })
}, { deep: true })
// ============================================================================
// 是否为锁死字段模式(内置 Prompt 的 title/description 不允许修改)
// ============================================================================
const isLocked = computed<boolean>( => props.prompt?.is_builtin === true)
const usage = computed( => getPromptUsage(props.prompt?.slug))
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
 project: '空间级',
}
</script>
<template>
 <form class="space-y-5">
 <!-- 内置 Prompt 锁死提示 -->
 <div
 v-if="isLocked"
 class="rounded-lg border border-primary/30 bg-primary/5 px-3 py-2.5 text-xs text-foreground flex items-start gap-2"
 >
 <span class="icon-[lucide--shield-check] text-primary text-base shrink-0 mt-px" />
 <div class="leading-relaxed">
 <span class="font-semibold text-foreground">系统内置 Prompt</span>
 <span class="text-muted-foreground"> · 标题与描述受代码契约约束，不可在此修改；正文与变量元数据仍可编辑并生成新版本。</span>
 </div>
 </div>
 <!-- 调用位置卡片：仅在能匹配到 slug 时展示 -->
 <div
 v-if="usage"
 class="card space-y-3"
 >
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--map-pin] text-primary text-base" />
 <h4 class="text-sm font-semibold text-foreground">
 调用位置
 </h4>
 <Badge variant="secondary" class="ml-auto gap-1 text-[10px]">
 <span:class="getPromptUsageDomainIcon(usage.domain)" class="text-xs" />
 {{ getPromptUsageDomainLabel(usage.domain) }}
 </Badge>
 <Badge v-if="usage.reserved" variant="muted" class="gap-1 text-[10px]">
 <span class="icon-[lucide--zap-off] text-xs" />
 保留位
 </Badge>
 </div>
 <p class="text-sm text-foreground leading-relaxed">
 {{ usage.scenario }}
 </p>
 <div class="space-y-1.5 pt-1">
 <div class="flex gap-2">
 <span class="text-[11px] text-muted-foreground shrink-0 w-12 pt-0.5">触发</span>
 <span class="text-xs text-foreground/80 leading-relaxed">{{ usage.trigger }}</span>
 </div>
 <div class="flex gap-2">
 <span class="text-[11px] text-muted-foreground shrink-0 w-12 pt-0.5">调用</span>
 <code class="text-[11px] font-mono text-foreground bg-muted px-1.5 py-0.5 rounded leading-relaxed break-all">
 {{ usage.callsite }}
 </code>
 </div>
 </div>
 </div>
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
 <!-- 内置 Prompt：标题 / 描述以只读静态文本呈现 -->
 <div v-if="isLocked && prompt" class="space-y-4">
 <div class="space-y-1.5">
 <div class="flex items-center gap-1.5">
 <span class="text-xs font-medium text-foreground">标题</span>
 <span class="icon-[lucide--lock] text-muted-foreground text-[11px]" />
 <span class="text-[10px] text-muted-foreground">不可修改</span>
 </div>
 <div
 data-testid="builtin-title"
 class="rounded-md border border-border/60 bg-muted/40 px-3 py-2 text-sm text-foreground"
 >
 {{ prompt.title }}
 </div>
 </div>
 <div class="space-y-1.5">
 <div class="flex items-center gap-1.5">
 <span class="text-xs font-medium text-foreground">描述</span>
 <span class="icon-[lucide--lock] text-muted-foreground text-[11px]" />
 <span class="text-[10px] text-muted-foreground">不可修改</span>
 </div>
 <div
 data-testid="builtin-description"
 class="rounded-md border border-border/60 bg-muted/40 px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap":class="prompt.description ? 'text-foreground': 'text-muted-foreground italic'"
 >
 {{ prompt.description || '（无描述）' }}
 </div>
 </div>
 </div>
 <!-- 非内置 Prompt：可编辑的标题 / 描述表单 -->
 <template v-else>
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
 </template>
 </form>
</template>
