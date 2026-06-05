<script setup lang="ts">
import type { VariableSpec } from '~/types/prompts'
/**
 * VariableSchemaEditor — variables_schema 原始 JSON 编辑器
 *
 * 职责:
 *   在 Sheet「基础信息」Tab 底部子区承载 variables_schema 原始 JSON 编辑,
 *   内嵌 JsonEditor.vue(复用空间已有的 CodeMirror 6 + JSON 语法高亮/校验栈),
 *   不自造 CodeMirror 封装。
 *
 * 数据流:
 *   外部 modelValue (Record<string, VariableSpec>)
 *     |-> JSON.stringify 格式化为 string rawText
 *     |-> 传给 JsonEditor
 *     |-> JsonEditor emit 字符串变化
 *     |-> JSON.parse 校验
 *         |-> 成功 → emit update:modelValue 为对象
 *         |-> 失败 → emit parse-error 事件 + 内部 parseError 态提示
 *
 * 契约:
 *   - 校验后的 JSON 必须是 plain object(非 null / 非 array),否则视为 parse-error
 *   - JsonEditor 高度固定 240px(与 UI-SPEC §CodeMirror 视觉契约一致)
 *   - Label 文本 「变量元数据（JSON）」严格对齐 215-UI-SPEC.md §Copywriting 只读字段表
 */
import { ref, watch } from 'vue'
import JsonEditor from '~/components/execution/JsonEditor.vue'

const props = defineProps<{
  modelValue: Record<string, VariableSpec>
}>()

// 事件名 parseError 采用 camelCase(Vue ESLint custom-event-name-casing 要求)。
// 父组件在模板中通过 kebab-case `@parse-error` 监听会自动映射。
const emit = defineEmits<{
  'update:modelValue': [value: Record<string, VariableSpec>]
  'parseError': [message: string]
}>()

// 序列化为 2 空格缩进的 JSON 字符串
const rawText = ref(JSON.stringify(props.modelValue ?? {}, null, 2))
const parseError = ref<string | null>(null)

// 外部 modelValue 变化 → 重新序列化并同步到编辑器
watch(() => props.modelValue, (v) => {
  const formatted = JSON.stringify(v ?? {}, null, 2)
  if (formatted !== rawText.value) {
    rawText.value = formatted
  }
}, { deep: true })

function handleRawChange(value: string): void {
  rawText.value = value
  try {
    const parsed = JSON.parse(value)
    if (parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed)) {
      parseError.value = null
      emit('update:modelValue', parsed as Record<string, VariableSpec>)
    }
    else {
      parseError.value = '变量元数据必须是对象'
      emit('parseError', parseError.value)
    }
  }
  catch (e) {
    parseError.value = e instanceof Error ? e.message : 'JSON 解析失败'
    emit('parseError', parseError.value)
  }
}
</script>

<template>
  <div class="space-y-2">
    <label class="text-xs font-medium text-foreground">变量元数据（JSON）</label>
    <JsonEditor
      :model-value="rawText"
      height="240px"
      @update:model-value="handleRawChange"
    />
    <p v-if="parseError" class="text-xs text-destructive">
      {{ parseError }}
    </p>
  </div>
</template>
