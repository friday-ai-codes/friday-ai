<script setup lang="ts">
/**
 * PromptVariableForm.vue — 动态变量输入表单
 *
 * 职责：根据 body 中的 {{var}} 占位符动态生成输入字段，支持：
 * - 1024 字符前端早拒（与后端 server/prompts/services.py VARIABLE_MAX_LENGTH 对齐）
 * - 后端 422 prompt_variable_missing 的 inline 红框高亮
 * - 根据 variablesSchema.description 或当前值长度自动在 Input / Textarea 间切换
 *
 * 数据源：父组件 PromptPreviewPanel 持有 missingVariables 状态，本组件仅负责渲染 + emit
 */

import type { VariableSpec } from '~/types/prompts'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { Textarea } from '~/components/ui/textarea'
import { extractVariables } from './codemirror/variableHighlight'

const props = defineProps<{
  body: string
  variablesSchema: Record<string, VariableSpec>
  /** 从父 Preview 面板传入的后端 422 missing 数组，用于 inline 高亮 */
  missingVariables?: string[]
}>()

const emit = defineEmits<{
  'update:values': [values: Record<string, string>]
}>()

/** 最大变量值长度，与后端 services.py::VARIABLE_MAX_LENGTH 对齐 */
const VARIABLE_MAX_LENGTH = 1024

/** 展示给用户看的 `{{var}}` 字面量，避免在模板 mustache 里写双花括号导致 Vue 解析器误判 */
const exampleVarLiteral = '{{input_text}}'

const detectedVariables = computed(() => extractVariables(props.body))

// 内部反应式存储每个变量的值 + 错误文本
const values = reactive<Record<string, string>>({})
const fieldErrors = reactive<Record<string, string>>({})

// 当变量集合或 schema 变化时，初始化 values 使用 schema.default
watch(
  [detectedVariables, () => props.variablesSchema],
  ([vars, schema]) => {
    for (const v of vars) {
      if (!(v in values)) {
        values[v] = schema[v]?.default ?? ''
      }
    }
    // 删除不再出现的变量
    for (const key of Object.keys(values)) {
      if (!vars.includes(key)) {
        delete values[key]
        delete fieldErrors[key]
      }
    }
  },
  { immediate: true, deep: true },
)

function handleInput(varName: string, newValue: string): void {
  if (newValue.length > VARIABLE_MAX_LENGTH) {
    fieldErrors[varName] = '变量值不能超过 1024 字符'
    // 不更新 values，不 emit —— 前端早拒
    return
  }
  fieldErrors[varName] = ''
  values[varName] = newValue
  emit('update:values', { ...values })
}

/** 判断某变量是否应使用 Textarea（有 description 或当前值较长） */
function useTextarea(varName: string): boolean {
  const spec = props.variablesSchema[varName]
  if (spec?.description)
    return true
  return (values[varName]?.length ?? 0) > 80
}

function placeholderFor(varName: string): string {
  return props.variablesSchema[varName]?.description ?? '请输入变量值'
}

/** 后端 422 missing 列表是否命中此变量（用于 inline 高亮） */
function isMissing(varName: string): boolean {
  return (props.missingVariables ?? []).includes(varName)
}

function effectiveError(varName: string): string {
  if (fieldErrors[varName])
    return fieldErrors[varName]
  if (isMissing(varName))
    return '此变量为必填'
  return ''
}
</script>

<template>
  <div class="space-y-4">
    <h4 class="text-sm font-semibold text-foreground">
      填写测试变量
    </h4>

    <div v-if="detectedVariables.length === 0" class="text-xs text-muted-foreground">
      当前正文未检测到变量，例如 <code class="font-mono">{{ exampleVarLiteral }}</code>
    </div>

    <div
      v-for="varName in detectedVariables"
      :key="varName"
      class="space-y-1.5"
    >
      <Label :for="`var-${varName}`" class="text-xs font-medium">
        <code class="font-mono text-foreground">{{ varName }}</code>
        <span v-if="variablesSchema[varName]?.required === false" class="ml-1 text-muted-foreground">（可选）</span>
      </Label>

      <Textarea
        v-if="useTextarea(varName)"
        :id="`var-${varName}`"
        :model-value="values[varName] ?? ''"
        :placeholder="placeholderFor(varName)"
        :class="{ 'border-destructive ring-destructive/50': effectiveError(varName) !== '' }"
        rows="3"
        @update:model-value="(v: string | number) => handleInput(varName, String(v))"
      />
      <Input
        v-else
        :id="`var-${varName}`"
        :model-value="values[varName] ?? ''"
        :placeholder="placeholderFor(varName)"
        :class="{ 'border-destructive ring-destructive/50': effectiveError(varName) !== '' }"
        @update:model-value="(v: string | number) => handleInput(varName, String(v))"
      />

      <p v-if="effectiveError(varName)" class="text-xs text-destructive">
        {{ effectiveError(varName) }}
      </p>
    </div>
  </div>
</template>
