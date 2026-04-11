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
 <div class="space-y-4">
 <!-- 顶部：section 标题 + 预览按钮 -->
 <div class="flex items-center justify-between">
 <h4 class="text-sm font-semibold text-foreground">
 渲染结果
 </h4>
 <Button:disabled="!canPreview || isPreviewing":title="canPreview ? '': '请先编辑 Prompt 正文'"
 @click="triggerPreview"
 >
 {{ isPreviewing ? '预览中…': '预览' }}
 </Button>
 </div>
 <!-- 渲染失败 Alert（非 PromptVariableMissingError） -->
 <div
 v-if="renderError"
 class="rounded-lg border border-destructive/50 bg-destructive/10 text-xs text-destructive"
 >
 渲染失败：{{ renderError }}
 </div>
 <!-- 变量输入表单（透传 missingVariables 供 inline 红框） -->
 <PromptVariableForm:body="body":variables-schema="prompt.active_version?.variables_schema ?? {}":missing-variables="missingVariables"
 @update:values="onValuesChange"
 />
 <!-- 渲染结果展示区 -->
 <div
 v-if="renderedResult !== null"
 class="rounded-lg border border-border/50 bg-muted "
 >
 <pre class="font-mono text-sm leading-6 text-foreground whitespace-pre-wrap">{{ renderedResult }}</pre>
 </div>
 <div
 v-else-if="!isPreviewing && !renderError"
 class="text-xs text-muted-foreground"
 >
 填写变量后点击「预览」查看渲染结果
 </div>
 </div>
</template>
