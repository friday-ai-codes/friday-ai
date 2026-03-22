<script setup lang="ts">
/**
 * JsonEditor — CodeMirror 6 JSON 编辑器组件
 *
 * 支持只读和可编辑两种模式。
 * 可编辑模式包含行号、JSON 语法高亮、实时校验、搜索替换。
 * 暗色主题适配 Glassmorphism 设计风格。
 */
import { computed } from 'vue'
import { Codemirror } from 'vue-codemirror'
import { json, jsonParseLinter } from '@codemirror/lang-json'
import { oneDark } from '@codemirror/theme-one-dark'
import { search } from '@codemirror/search'
import { linter } from '@codemirror/lint'
import { EditorView } from '@codemirror/view'
import type { Extension } from '@codemirror/state'
const props = withDefaults(defineProps<{
 modelValue: string
 readonly?: boolean
 height?: string
}>, {
 readonly: false,
 height: '300px',
})
const emit = defineEmits<{
 'update:modelValue': [value: string]
}>
const extensions = computed<Extension>( => {
 const exts: Extension = [
 json,
 oneDark,
 search,
 EditorView.lineWrapping,
 ]
 // 非只读时启用 JSON 语法实时校验
 if (!props.readonly) {
 exts.push(linter(jsonParseLinter))
 }
 return exts
})
function handleUpdate(value: string) {
 emit('update:modelValue', value)
}
</script>
<template>
 <div
 class="rounded-lg overflow-hidden border border-white/10":style="{ height }"
 >
 <Codemirror:model-value="modelValue":extensions="extensions":disabled="readonly":indent-with-tab="true":tab-size="2":style="{ height: '100%' }"
 @update:model-value="handleUpdate"
 />
 </div>
</template>
<style scoped>:deep(.cm-editor) {
 background: rgba(0, 0, 0, 0.3);
 height: 100%;
}:deep(.cm-scroller) {
 overflow: auto;
}
</style>
