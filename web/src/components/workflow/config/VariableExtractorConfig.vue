<script setup lang="ts">
import type { ExtractionRule, VariableExtractorConfig } from '~/types/workflow'

import { computed, ref } from 'vue'

import { Button } from '~/components/ui/button'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '~/components/ui/collapsible'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '~/components/ui/dialog'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { Separator } from '~/components/ui/separator'
import { Switch } from '~/components/ui/switch'
import { QUICK_FIELD_OPTIONS } from '~/types/workflow'

// ============================================================================
// Props & Emits
// ============================================================================

interface Props {
  config: VariableExtractorConfig
}

const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'update:config', value: VariableExtractorConfig): void
}>()

// ============================================================================
// Config Model
// ============================================================================

// 直接使用 computed 管理 extractions，不需要 useConfigModel
// 因为这个组件只有一个数组字段，不需要复杂的字段管理

const extractions = computed({
  get: () => props.config.extractions ?? [],
  set: v => emit('update:config', { ...props.config, extractions: v }),
})

// ============================================================================
// 快捷字段面板
// ============================================================================

const showQuickFields = ref(true)
const showHelpDialog = ref(false)

function addQuickField(quickField: typeof QUICK_FIELD_OPTIONS[number]) {
  // 检查是否已存在
  if (extractions.value.some(e => e.key === quickField.key)) {
    return
  }

  const newRule: ExtractionRule = {
    source_path: quickField.path,
    key: quickField.key,
    name: quickField.name,
    desc: quickField.desc,
    required: false,
  }

  extractions.value = [...extractions.value, newRule]
}

function isQuickFieldAdded(key: string): boolean {
  return extractions.value.some(e => e.key === key)
}

// ============================================================================
// 提取规则管理
// ============================================================================

function addRule() {
  const newRule: ExtractionRule = {
    source_path: '',
    key: '',
    name: '',
    desc: '',
    required: false,
  }
  extractions.value = [...extractions.value, newRule]
}

function removeRule(index: number) {
  extractions.value = extractions.value.filter((_, i) => i !== index)
}

function updateRule(index: number, field: keyof ExtractionRule, value: any) {
  const updated = [...extractions.value]
  updated[index] = { ...updated[index], [field]: value }
  extractions.value = updated
}
</script>

<template>
  <div class="space-y-4">
    <!-- 标题和帮助按钮 -->
    <div class="flex items-center justify-between">
      <div class="flex items-center gap-2">
        <span class="icon-[lucide--variable] text-lg text-primary" />
        <span class="font-medium">变量提取配置</span>
      </div>
      <Dialog v-model:open="showHelpDialog">
        <DialogTrigger as-child>
          <Button variant="ghost" size="sm" class="text-muted-foreground">
            <span class="icon-[lucide--help-circle] mr-1" />
            帮助
          </Button>
        </DialogTrigger>
        <DialogContent class="max-w-2xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle class="flex items-center gap-2">
              <span class="icon-[lucide--book-open] text-primary" />
              JSONPath 变量提取说明
            </DialogTitle>
            <DialogDescription>
              使用 JSONPath 语法从上游节点的 JSON 输出中提取数据
            </DialogDescription>
          </DialogHeader>

          <div class="space-y-6 pt-4">
            <!-- 工作原理 -->
            <div class="space-y-2">
              <h4 class="font-medium flex items-center gap-2">
                <span class="icon-[lucide--workflow] text-primary" />
                工作原理
              </h4>
              <p class="text-sm text-muted-foreground">
                变量提取节点从上游节点（如「获取工作项详情」）的输出中，使用 JSONPath 语法提取指定字段，
                并注册为全局变量供后续节点使用。
              </p>
            </div>

            <!-- 输入示例 -->
            <div class="space-y-2">
              <h4 class="font-medium flex items-center gap-2">
                <span class="icon-[lucide--file-input] text-green-500" />
                输入示例（上游节点输出）
              </h4>
              <pre class="bg-muted rounded-lg p-3 text-xs overflow-x-auto"><code>{
  "id": 6659791768,
  "name": "响应式适配需求",
  "description": "修复响应式问题",
  "project_key": "000000000000000000000001",
  "fields": [
    { "key": "field_000001", "value": "https://docs.example.com/prd" },
    { "key": "field_000009", "value": "https://docs.example.com/tech" },
    { "key": "description", "value": "详细需求描述..." }
  ]
}</code></pre>
            </div>

            <!-- 提取规则配置 -->
            <div class="space-y-2">
              <h4 class="font-medium flex items-center gap-2">
                <span class="icon-[lucide--settings] text-primary" />
                提取规则配置
              </h4>
              <div class="bg-muted rounded-lg p-3 space-y-2 text-sm">
                <div class="grid grid-cols-3 gap-2 font-medium text-xs text-muted-foreground border-b pb-2">
                  <span>显示名称</span>
                  <span>变量 Key</span>
                  <span>JSONPath 路径</span>
                </div>
                <div class="grid grid-cols-3 gap-2 text-xs">
                  <span>工作项名称</span>
                  <code class="text-primary">workItemName</code>
                  <code>$.name</code>
                </div>
                <div class="grid grid-cols-3 gap-2 text-xs">
                  <span>需求文档</span>
                  <code class="text-primary">prdUrl</code>
                  <code>$.fields[?(@.key=='field_000001')].value</code>
                </div>
                <div class="grid grid-cols-3 gap-2 text-xs">
                  <span>描述</span>
                  <code class="text-primary">description</code>
                  <code>$.fields[?(@.key=='description')].value</code>
                </div>
              </div>
            </div>

            <!-- 输出示例 -->
            <div class="space-y-2">
              <h4 class="font-medium flex items-center gap-2">
                <span class="icon-[lucide--file-output] text-primary" />
                输出示例（提取结果）
              </h4>
              <pre class="bg-muted rounded-lg p-3 text-xs overflow-x-auto"><code>{
  "workItemName": {
    "name": "工作项名称",
    "value": "响应式适配需求",
    "path": "$.name"
  },
  "prdUrl": {
    "name": "需求文档",
    "value": "https://docs.example.com/prd",
    "path": "$.fields[?(@.key=='field_000001')].value"
  },
  "description": {
    "name": "描述",
    "value": "详细需求描述...",
    "path": "$.fields[?(@.key=='description')].value"
  }
}</code></pre>
            </div>

            <!-- JSONPath 语法 -->
            <div class="space-y-2">
              <h4 class="font-medium flex items-center gap-2">
                <span class="icon-[lucide--code] text-primary" />
                常用 JSONPath 语法
              </h4>
              <div class="bg-muted rounded-lg p-3 space-y-1.5 text-xs">
                <div class="flex gap-2">
                  <code class="bg-background px-1.5 py-0.5 rounded min-w-24">$</code>
                  <span class="text-muted-foreground">根对象</span>
                </div>
                <div class="flex gap-2">
                  <code class="bg-background px-1.5 py-0.5 rounded min-w-24">$.name</code>
                  <span class="text-muted-foreground">获取根对象的 name 字段</span>
                </div>
                <div class="flex gap-2">
                  <code class="bg-background px-1.5 py-0.5 rounded min-w-24">$.data.user</code>
                  <span class="text-muted-foreground">嵌套路径访问</span>
                </div>
                <div class="flex gap-2">
                  <code class="bg-background px-1.5 py-0.5 rounded min-w-24">$.items[0]</code>
                  <span class="text-muted-foreground">数组第一个元素</span>
                </div>
                <div class="flex gap-2">
                  <code class="bg-background px-1.5 py-0.5 rounded min-w-24">$.items[*].id</code>
                  <span class="text-muted-foreground">数组所有元素的 id</span>
                </div>
                <div class="flex gap-2">
                  <code class="bg-background px-1.5 py-0.5 rounded min-w-24 whitespace-nowrap">[?(@.key=='x')]</code>
                  <span class="text-muted-foreground">过滤器，匹配 key 等于 'x' 的元素</span>
                </div>
              </div>
            </div>

            <!-- 后续使用 -->
            <div class="space-y-2">
              <h4 class="font-medium flex items-center gap-2">
                <span class="icon-[lucide--zap] text-yellow-500" />
                在后续节点中使用
              </h4>
              <p class="text-sm text-muted-foreground">
                提取的变量注册为全局变量后，可在后续节点的配置中通过模板语法引用：
              </p>
              <div class="bg-muted rounded-lg p-3 text-xs space-y-1">
                <code v-pre>{{ global.workItemName }}</code>
                <span class="text-muted-foreground ml-2">→ 响应式适配需求</span>
              </div>
            </div>

            <!-- 参考链接 -->
            <div class="border-t pt-4">
              <a
                href="https://goessner.net/articles/JsonPath/"
                target="_blank"
                class="text-sm text-primary hover:underline inline-flex items-center gap-1"
              >
                <span class="icon-[lucide--external-link]" />
                JSONPath 官方文档
              </a>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>

    <!-- 快捷字段 -->
    <Collapsible v-model:open="showQuickFields">
      <div class="flex items-center justify-between">
        <Label class="text-sm font-medium">常用字段快捷添加</Label>
        <CollapsibleTrigger as-child>
          <Button variant="ghost" size="sm">
            <span class="icon-[lucide--chevron-down] transition-transform" :class="{ 'rotate-180': !showQuickFields }" />
          </Button>
        </CollapsibleTrigger>
      </div>
      <CollapsibleContent class="pt-2">
        <div class="flex flex-wrap gap-2">
          <Button
            v-for="field in QUICK_FIELD_OPTIONS"
            :key="field.key"
            size="sm"
            :variant="isQuickFieldAdded(field.key) ? 'secondary' : 'outline'"
            :disabled="isQuickFieldAdded(field.key)"
            @click="addQuickField(field)"
          >
            <span v-if="isQuickFieldAdded(field.key)" class="icon-[lucide--check] mr-1" />
            <span v-else class="icon-[lucide--plus] mr-1" />
            {{ field.name }}
          </Button>
        </div>
        <p class="text-xs text-muted-foreground mt-2">
          基于飞书项目常用字段预设，点击快速添加
        </p>
      </CollapsibleContent>
    </Collapsible>

    <Separator />

    <!-- 提取规则列表 -->
    <div class="space-y-3">
      <div class="flex items-center justify-between">
        <Label>提取规则</Label>
        <Button size="sm" variant="outline" @click="addRule">
          <span class="icon-[lucide--plus] mr-1" />
          添加规则
        </Button>
      </div>

      <div v-if="extractions.length === 0" class="text-center py-8 text-muted-foreground">
        <span class="icon-[lucide--variable] text-4xl mb-2 block opacity-50" />
        <p>暂无提取规则</p>
        <p class="text-xs">
          点击上方快捷字段或「添加规则」开始配置
        </p>
      </div>

      <div
        v-for="(rule, index) in extractions"
        :key="index"
        class="rounded-lg border border-border/50 bg-card/50 p-4 space-y-3"
      >
        <div class="flex items-start justify-between">
          <div class="flex items-center gap-2">
            <div class="p-1.5 rounded-md bg-primary/10">
              <span class="icon-[lucide--variable] text-primary" />
            </div>
            <span class="font-medium text-sm">{{ rule.name || '未命名变量' }}</span>
            <span v-if="rule.required" class="text-xs text-destructive">必填</span>
          </div>
          <Button
            variant="ghost"
            size="sm"
            class="text-muted-foreground hover:text-destructive"
            @click="removeRule(index)"
          >
            <span class="icon-[lucide--trash-2]" />
          </Button>
        </div>

        <div class="grid grid-cols-2 gap-3">
          <!-- 显示名称 -->
          <div class="space-y-1">
            <Label class="text-xs">显示名称</Label>
            <Input
              :model-value="rule.name"
              placeholder="如：需求描述"
              @update:model-value="v => updateRule(index, 'name', v)"
            />
          </div>

          <!-- 变量标识符 -->
          <div class="space-y-1">
            <Label class="text-xs">变量 Key</Label>
            <Input
              :model-value="rule.key"
              placeholder="如：requirementDesc"
              class="font-mono text-sm"
              @update:model-value="v => updateRule(index, 'key', v)"
            />
          </div>
        </div>

        <!-- JSONPath 路径 -->
        <div class="space-y-1">
          <Label class="text-xs">JSONPath 路径</Label>
          <Input
            :model-value="rule.source_path"
            placeholder="$.fields[?(@.key=='description')].value"
            class="font-mono text-sm"
            @update:model-value="v => updateRule(index, 'source_path', v)"
          />
        </div>

        <!-- 描述 -->
        <div class="space-y-1">
          <Label class="text-xs">描述（选填）</Label>
          <Input
            :model-value="rule.desc"
            placeholder="变量用途说明"
            @update:model-value="v => updateRule(index, 'desc', v)"
          />
        </div>

        <!-- 必填开关 -->
        <div class="flex items-center justify-between pt-1">
          <div>
            <Label class="text-xs">必填变量</Label>
            <p class="text-xs text-muted-foreground">
              提取失败时节点将报错
            </p>
          </div>
          <Switch
            :checked="rule.required"
            @update:checked="(v: boolean) => updateRule(index, 'required', v)"
          />
        </div>
      </div>
    </div>

    <!-- 使用提示 -->
    <div class="rounded-lg bg-muted/50 p-3">
      <p class="text-xs text-muted-foreground">
        <span class="icon-[lucide--info] mr-1" />
        提取的变量可在后续节点中通过
        <code v-pre class="bg-muted px-1 py-0.5 rounded text-primary">{{ global.variableKey }}</code>
        语法引用
      </p>
    </div>
  </div>
</template>
