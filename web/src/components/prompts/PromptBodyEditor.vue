<script setup lang="ts">
import type { Extension } from '@codemirror/state'
import { search } from '@codemirror/search'
import { EditorView } from '@codemirror/view'
/**
 * PromptBodyEditor — Prompt 正文 CodeMirror 6 编辑器
 *
 * 视觉设计变更（vs. -04 初版）：
 *   - 原先与 JsonEditor 共用的 oneDark + rgba(0,0,0,0.3) 蒙层，在 Friday
 *     浅色应用背景上会形成「中灰底 + 灰文字」的低对比度组合（WCAG <4.5:1），
 *     已替换为本仓库自有的 fridayLightTheme（teal/slate light token 对齐）。
 *   - 外壳卡片由 white bg + slate-200 border + 圆角 + 细投影替代，与
 *     DESIGN.md「Sub2API Clean Card」风格对齐。
 *
 * 扩展栈：fridayLightTheme + search + EditorView.lineWrapping + variableHighlight。
 * Prompt 语法是纯 Jinja2，前端不做语法验证；后端 strict_undefined 渲染兜底。
 *
 * 固定高度 480px（UI-SPEC §CodeMirror 视觉契约），避免 Sheet 内部纵向无限撑高。
 */
import { Codemirror } from 'vue-codemirror'
import { fridayLightTheme } from '~/components/codemirror/fridayLightTheme'
import { variableHighlight } from './codemirror/variableHighlight'

withDefaults(defineProps<{
  modelValue: string
  readonly?: boolean
}>(), {
  readonly: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const extensions: Extension[] = [
  fridayLightTheme,
  search(),
  EditorView.lineWrapping,
  variableHighlight(),
]

function handleChange(value: string): void {
  emit('update:modelValue', value)
}
</script>

<template>
  <div
    class="rounded-lg overflow-hidden border border-border/50 bg-card shadow-sm"
    :style="{ height: '480px' }"
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

/**
 * {{var}} 装饰类:已在 variables_schema 中声明的变量 —— primary teal 色。
 * HSL 值与 215-UI-SPEC.md §Color §CSS 类 一致,禁止改动。
 */
:deep(.cm-prompt-variable) {
  color: hsl(168 76% 42%);
  font-weight: 600;
  text-decoration: underline;
  text-underline-offset: 2px;
  background: hsl(168 76% 42% / 0.08);
  border-radius: 3px;
  padding: 0 2px;
}

/**
 * {{var}} 装饰类:未在 variables_schema 中声明的变量 —— destructive 红色 + wavy 下划线。
 * HSL 值与 215-UI-SPEC.md §Color §CSS 类 一致,禁止改动。
 */
:deep(.cm-prompt-variable-unknown) {
  color: hsl(0 72% 51%);
  font-weight: 600;
  text-decoration: underline wavy;
  background: hsl(0 72% 51% / 0.08);
  border-radius: 3px;
  padding: 0 2px;
}
</style>
