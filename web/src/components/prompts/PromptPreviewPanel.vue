<script setup lang="ts">
/**
 * PromptPreviewPanel.vue — Sheet 抽屉内 Preview Tab 的主面板
 *
 * 职责：
 * - 展示预览触发按钮（body 为空时 disabled + tooltip 提示）
 * - 调 store.previewPrompt(id, variables) 触发后端渲染
 * - instanceof PromptVariableMissingError 特判：走 inline 高亮（不 toast）
 * - 其他错误走 Alert + useErrorHandler 全局 toast
 * - 渲染结果以 <pre> 纯文本展示（依赖 Vue mustache 自动转义抵御 XSS）
 *
 * 上游依赖：
 * - ~/stores/prompts:previewPrompt（Plan Task 3 交付）
 * - ~/api/prompts:PromptVariableMissingError（Plan Task 2 交付）
 * - ./PromptVariableForm.vue（本 Plan Task 1 Part A）
 */
import type { PromptDetail } from '~/types/prompts'
import { PromptVariableMissingError } from '~/api/prompts'
import { Button } from '~/components/ui/button'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { usePromptsStore } from '~/stores/prompts'
import PromptVariableForm from './PromptVariableForm.vue'
const props = defineProps<{
 prompt: PromptDetail
 body: string
}>
const store = usePromptsStore
const { handleError } = useErrorHandler
const variables = ref<Record<string, string>>({})
const renderedResult = ref<string | null>(null)
const renderError = ref<string | null>(null)
const missingVariables = ref<string>
const isPreviewing = ref(false)
const canPreview = computed( => props.body.trim.length > 0)
async function triggerPreview: Promise<void> {
 if (!canPreview.value)
 return
 isPreviewing.value = true
 renderError.value = null
 missingVariables.value =
 try {
 const result = await store.previewPrompt(props.prompt.id, variables.value)
 renderedResult.value = result.rendered
 }
 catch (e) {
 // 特判：PromptVariableMissingError 走 inline 高亮，不走全局 toast
 if (e instanceof PromptVariableMissingError) {
 missingVariables.value = e.missing
 renderedResult.value = null
 return
 }
 // 其他错误走 Alert + 上抛全局 handler
 renderError.value = e instanceof Error ? e.message: '未知错误'
 handleError(e, '预览 Prompt')
 }
 finally {
 isPreviewing.value = false
 }
}
function onValuesChange(newValues: Record<string, string>): void {
 variables.value = newValues
 // 任意修改都清除 missing 高亮（用户正在重新填写）
 if (missingVariables.value.length > 0) {
 missingVariables.value =
 }
}
</script>
<template>
 <div class="space-y-5">
 <!-- 顶部：标题 + 预览按钮（按钮在最前以满足 wrapper.find('button') 契约） -->
 <div class="flex items-center justify-between gap-3">
 <div>
 <h4 class="text-sm font-semibold text-foreground flex items-center gap-2">
 <span class="icon-[lucide--eye] text-primary text-base" />
 预览渲染
 </h4>
 <p class="text-xs text-muted-foreground mt-0.5">
 填写下方变量后，点击预览查看后端渲染后的最终文本
 </p>
 </div>
 <Button:disabled="!canPreview || isPreviewing":title="canPreview ? '': '请先编辑 Prompt 正文'"
 @click="triggerPreview"
 >
 <span class="icon-[lucide--play] mr-1.5 text-sm" />
 {{ isPreviewing ? '预览中…': '预览' }}
 </Button>
 </div>
 <!-- 渲染失败 Alert（非 PromptVariableMissingError） -->
 <div
 v-if="renderError"
 role="alert"
 class="rounded-lg border border-destructive/40 bg-destructive/6 text-xs text-destructive flex items-start gap-2"
 >
 <span class="icon-[lucide--alert-circle] text-base shrink-0 mt-px" />
 <div class="leading-relaxed">
 <span class="font-semibold">渲染失败：</span>{{ renderError }}
 </div>
 </div>
 <!-- 变量输入表单（透传 missingVariables 供 inline 红框） -->
 <div class="rounded-xl border border-border/60 bg-card shadow-sm">
 <PromptVariableForm:body="body":variables-schema="prompt.active_version?.variables_schema ?? {}":missing-variables="missingVariables"
 @update:values="onValuesChange"
 />
 </div>
 <!-- 渲染结果展示区 -->
 <div class="space-y-2">
 <div class="flex items-center justify-between">
 <span class="text-xs font-semibold text-foreground">渲染结果</span>
 <span v-if="renderedResult !== null" class="text-[11px] text-muted-foreground">
 {{ renderedResult.length }} 字符
 </span>
 </div>
 <div
 v-if="renderedResult !== null"
 class="rounded-xl border border-primary/30 bg-primary/3 shadow-sm overflow-hidden"
 >
 <div class="px-3 py-1.5 border-b border-primary/15 bg-primary/6 text-[11px] font-medium text-primary flex items-center gap-1.5">
 <span class="icon-[lucide--check-circle] text-sm" />
 渲染成功
 </div>
 <pre class="font-mono text-sm leading-6 text-foreground whitespace-pre-wrap max-h-[400px] overflow-auto">{{ renderedResult }}</pre>
 </div>
 <div
 v-else-if="!isPreviewing && !renderError"
 class="rounded-xl border border-dashed border-border/60 bg-muted/30 px-4 py-6 text-center"
 >
 <p class="text-xs text-muted-foreground">
 填写变量后点击「预览」查看渲染结果
 </p>
 </div>
 <div
 v-else-if="isPreviewing"
 class="rounded-xl border border-border/60 bg-card px-4 py-6 text-center flex items-center justify-center gap-2"
 >
 <span class="icon-[lucide--loader-2] animate-spin text-primary" />
 <span class="text-xs text-muted-foreground">正在调用后端渲染…</span>
 </div>
 </div>
 </div>
</template>
