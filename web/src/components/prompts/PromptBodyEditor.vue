<script setup lang="ts">
import type { Extension } from '@codemirror/state'
import { search } from '@codemirror/search'
import { oneDark } from '@codemirror/theme-one-dark'
import { EditorView } from '@codemirror/view'
/**
 * PromptBodyEditor — Prompt 正文 CodeMirror 6 编辑器
 *
 * 职责:
 * 在 Sheet 抽屉「正文编辑」Tab 中承载 Prompt body 的多行文本编辑体验,
 * 并通过 variableHighlight 扩展实时装饰 {{var}} 占位符。
 *
 * 扩展栈与 JsonEditor.vue 严格对齐(除掉 json/linter,加上 variableHighlight):
 * oneDark + search + EditorView.lineWrapping + variableHighlight
 *
 * 固定高度 480px(work item §CodeMirror 视觉契约)避免 Sheet 内部纵向无限撑高。
 * 外层 wrapper 使用 Glassmorphism class 组合与 JsonEditor.vue 视觉一致。
 *
 * 不加任何语言高亮扩展(不含 markdown / 模板引擎专用解析器)——
 * Prompt 语法是纯 Jinja2,前端不做语法验证,后端 strict_undefined 渲染兜底。
 */
import { Codemirror } from 'vue-codemirror'
import { variableHighlight } from './codemirror/variableHighlight'
withDefaults(defineProps<{
 modelValue: string
 readonly?: boolean
}>, {
 readonly: false,
})
const emit = defineEmits<{
 'update:modelValue': [value: string]
}>
// 扩展栈:与 JsonEditor.vue 一致,唯一差别是用 variableHighlight 替代 json/linter。
// 不把扩展定义为 computed —— readonly prop 不需要动态切换扩展栈。
const extensions: Extension = [
 oneDark,
 search,
 EditorView.lineWrapping,
 variableHighlight,
]
function handleChange(value: string): void {
 emit('update:modelValue', value)
}
</script>
<template>
 <div
 class="rounded-lg overflow-hidden border border-border/50":style="{ height: '480px' }"
 >
 <Codemirror:model-value="modelValue":extensions="extensions":disabled="readonly":indent-with-tab="true":tab-size="2":style="{ height: '100%' }"
 @update:model-value="handleChange"
 />
 </div>
</template>
<style scoped>
/* CodeMirror 内部样式穿透 —— 与 JsonEditor.vue 一致 */:deep(.cm-editor) {
 background: rgba(0, 0, 0, 0.3);
 height: 100%;
}:deep(.cm-scroller) {
 overflow: auto;
}
/**
 * {{var}} 装饰类:已在 variables_schema 中声明的变量 —— primary teal 色。
 * HSL 值与 work-item item.md §Color §CSS 类 一致,禁止改动。
 */:deep(.cm-prompt-variable) {
 color: hsl(168 76% 42%);
 font-weight: 600;
 text-decoration: underline;
 text-underline-offset: 2px;
}
/**
 * {{var}} 装饰类:未在 variables_schema 中声明的变量 —— destructive 红色 + wavy 下划线。
 * HSL 值与 work-item item.md §Color §CSS 类 一致,禁止改动。
 */:deep(.cm-prompt-variable-unknown) {
 color: hsl(0 72% 51%);
 font-weight: 600;
 text-decoration: underline wavy;
}
</style>
