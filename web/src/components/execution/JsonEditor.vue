<script setup lang="ts">
import type { Extension } from '@codemirror/state'
import { json, jsonParseLinter } from '@codemirror/lang-json'
import { linter } from '@codemirror/lint'
import { search } from '@codemirror/search'
import { EditorView } from '@codemirror/view'
/**
 * JsonEditor — CodeMirror 6 JSON 编辑器组件
 *
 * 支持只读和可编辑两种模式。可编辑模式包含行号、JSON 语法高亮、实时校验、搜索替换。
 *
 * 主题：fridayLightTheme（teal/slate 浅色 token）。原 oneDark + rgba(0,0,0,0.3)
 * 组合在 Friday 浅色应用背景上会形成灰底灰字（WCAG <4.5:1），已迁移到与
 * DESIGN.md「Sub2API Clean Card」对齐的浅色 token。
 */
import { computed } from 'vue'
import { Codemirror } from 'vue-codemirror'
import { fridayLightTheme } from '~/components/codemirror/fridayLightTheme'

const props = withDefaults(defineProps<{
  modelValue: string
  readonly?: boolean
  height?: string
}>(), {
  readonly: false,
  height: '300px',
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const extensions = computed<Extension[]>(() => {
  const exts: Extension[] = [
    json(),
    fridayLightTheme,
    search(),
    EditorView.lineWrapping,
  ]
  if (!props.readonly) {
    exts.push(linter(jsonParseLinter()))
  }
  return exts
})

function handleUpdate(value: string) {
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
      @update:model-value="handleUpdate"
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
