<script setup lang="ts">
import type { VariableSpec } from '~/types/prompts'
/**
 * PromptVariablePanel — 变量提示面板(只读展示,不输入)
 *
 * 职责:
 *   在 Sheet「正文编辑」Tab 右侧以吸顶卡片展示当前 body 中检测到的所有变量,
 *   并根据 variables_schema 中是否声明该变量,分别展示「必填 / 可选 / 未声明」三态徽章。
 *
 * 数据流:
 *   body (string) + variables_schema (Record) —prop 驱动—> detectedVariables (computed)
 *                                                        —> 三态徽章逐行渲染
 *
 * 变量检测基于 -01 交付的 extractVariables(正则与后端 _PLACEHOLDER_RE 字面一致),
 * 返回去重后的字母序列表,无需本组件再次处理排序。
 *
 * 文案严格对齐 215-UI-SPEC.md §Copywriting:
 *   - section 标题 「变量」
 *   - 空态 「当前正文未检测到变量」
 *   - 三态徽章 「必填」/「可选」/「未声明」
 *   - 底部警告 「此变量未在元数据中声明」
 */
import { Badge } from '~/components/ui/badge'
import { extractVariables } from './codemirror/variableHighlight'

const props = defineProps<{
  body: string
  variablesSchema: Record<string, VariableSpec>
}>()

// 实时扫描 body 抽取变量(去重 + 字母序排序由 extractVariables 完成)
const detectedVariables = computed(() => extractVariables(props.body))

// 是否存在未声明的变量(body 出现但 schema 未列出)
const hasUndeclared = computed(() =>
  detectedVariables.value.some(v => !isDeclared(v)),
)

// 变量在 variables_schema 中是否声明 —— 使用 hasOwnProperty 避免 prototype 污染误判
function isDeclared(varName: string): boolean {
  return Object.prototype.hasOwnProperty.call(props.variablesSchema, varName)
}

// 变量在 variables_schema 中是否为必填
function isRequired(varName: string): boolean {
  return props.variablesSchema[varName]?.required === true
}
</script>

<template>
  <div class="card p-4 space-y-3">
    <h4 class="text-sm font-semibold text-foreground">
      变量
    </h4>

    <!-- 空态:body 为空或 body 中无 {{var}} 占位符 -->
    <div
      v-if="detectedVariables.length === 0"
      class="text-xs text-muted-foreground"
    >
      当前正文未检测到变量
    </div>

    <!-- 变量列表:每行一个变量 + 三态徽章 -->
    <ul v-else class="space-y-2">
      <li
        v-for="varName in detectedVariables"
        :key="varName"
        class="flex items-center justify-between gap-2"
      >
        <code class="text-xs font-mono text-foreground">{{ varName }}</code>
        <div class="flex items-center gap-1">
          <Badge v-if="isDeclared(varName) && isRequired(varName)" variant="default">
            必填
          </Badge>
          <Badge v-else-if="isDeclared(varName) && !isRequired(varName)" variant="outline">
            可选
          </Badge>
          <Badge v-else variant="warning">
            未声明
          </Badge>
        </div>
      </li>
    </ul>

    <!-- 底部警告:任意变量未在 schema 声明 -->
    <p v-if="hasUndeclared" class="text-xs text-amber-700">
      此变量未在元数据中声明
    </p>
  </div>
</template>
