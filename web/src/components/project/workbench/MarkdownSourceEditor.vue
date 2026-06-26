<script setup lang="ts">
import type { Extension } from '@codemirror/state'
import { markdown } from '@codemirror/lang-markdown'
import { search } from '@codemirror/search'
import { EditorView } from '@codemirror/view'
/**
 * MarkdownSourceEditor — Markdown 源码 CodeMirror 6 编辑器（WB-03）。
 *
 * 用于工作区 5 文件「编辑源码」态：人工区可编辑、系统区只读。查看态走
 * `MarkdownRenderer`（渲染），本组件只负责源码编辑（不渲染、不执行 HTML，XSS
 * 风险隔离于渲染侧）。
 *
 * 主题沿用本仓库自有的 `fridayLightTheme`（teal/slate 浅色 token），与
 * `PromptBodyEditor` / `JsonEditor` 一致；不引入暗色 one-dark。
 *
 * 扩展栈：markdown() 语言 + fridayLightTheme + search + lineWrapping。
 */
import { Codemirror } from 'vue-codemirror'
import { fridayLightTheme } from '~/components/codemirror/fridayLightTheme'

withDefaults(defineProps<{
  modelValue: string
  readonly?: boolean
  height?: string
}>(), {
  readonly: false,
  height: '240px',
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const extensions: Extension[] = [
  markdown(),
  fridayLightTheme,
  search(),
  EditorView.lineWrapping,
]

function handleChange(value: string): void {
  emit('update:modelValue', value)
}
</script>

<template>
  <div
    class="rounded-lg overflow-hidden border border-border/50 bg-card shadow-sm"
    :style="{ height }"
  >
    <Codemirror
      :model-value="modelValue"
      :extensions="extensions"
      :disabled="readonly"
      :indent-with-tab="true"
      :tab-size="2"
      :style="{ height: '100%' }"
      @update:model-value="handleChange"
    />
  </div>
</template>

<style scoped>
:deep(.cm-editor) {
  height: 100%;
  background: transparent;
}
:deep(.cm-editor.cm-focused) {
  outline: none;
}
:deep(.cm-scroller) {
  overflow: auto;
  padding: 4px 12px;
}
</style>
