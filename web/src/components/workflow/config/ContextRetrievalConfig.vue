<script setup lang="ts">
import type { NodeType } from '~/stores/useNodeTypesStore'
import type { ContextRetrievalConfig } from '~/types/workflow'
import type { WorkflowEdge, WorkflowNode } from '~/types/workflow/store'

import { computed } from 'vue'
import { Label } from '~/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'
import { Separator } from '~/components/ui/separator'
import { SliderSingle } from '~/components/ui/slider'
import { Switch } from '~/components/ui/switch'
import NodePortsDisplay from '~/components/workflow/NodePortsDisplay.vue'
import SmartInput from '~/components/workflow/smart-input/SmartInput.vue'
import { useConfigModel } from '~/composables/useConfigModel'
import { contextRetrievalConfigSchema } from '~/types/workflow'

// ============================================================================
// Types
// ============================================================================

interface Repository {
  id: string
  name: string
}

// ============================================================================
// Props & Emits
// ============================================================================

interface Props {
  config: ContextRetrievalConfig
  repositories?: Repository[]
  /** 设计态：工作流画布节点列表 */
  workflowNodes?: WorkflowNode[]
  /** 设计态：工作流画布边列表 */
  workflowEdges?: WorkflowEdge[]
  /** 设计态：当前正在配置的节点 ID */
  currentNodeId?: string | null
  /** 节点类型信息 */
  nodeTypeInfo?: NodeType | null
}

const props = withDefaults(defineProps<Props>(), {
  repositories: () => [],
  workflowNodes: () => [],
  workflowEdges: () => [],
  currentNodeId: null,
  nodeTypeInfo: null,
})
const emit = defineEmits<{
  (e: 'update:config', value: ContextRetrievalConfig): void
}>()

// ============================================================================
// Config Model
// ============================================================================

const { field } = useConfigModel({
  config: () => props.config,
  emit: v => emit('update:config', v),
  schema: contextRetrievalConfigSchema,
})

const query = field('query', '')
const topK = field('top_k', 10)
const scoreThreshold = field('score_threshold', 0.5)
const languageFilter = field('language_filter', '')
const includeContent = field('include_content', true)
const formatAsMarkdown = field('format_as_markdown', true)

// ============================================================================
// Repositories - 支持字符串（JSONPath 表达式）或数组
// ============================================================================

const repositoriesModel = computed({
  get: () => {
    const val = props.config.repositories
    // 如果是字符串（JSONPath 表达式），直接返回
    if (typeof val === 'string')
      return val
    // 如果是数组，返回空字符串（旧数据迁移场景）
    return ''
  },
  set: (val: string) => {
    emit('update:config', { ...props.config, repositories: val })
  },
})

// ============================================================================
// 语言选项
// ============================================================================

const languageOptions = [
  { value: '', label: '全部语言' },
  { value: 'python', label: 'Python' },
  { value: 'typescript', label: 'TypeScript' },
  { value: 'javascript', label: 'JavaScript' },
  { value: 'go', label: 'Go' },
  { value: 'java', label: 'Java' },
  { value: 'rust', label: 'Rust' },
  { value: 'vue', label: 'Vue' },
]

// reka-ui 的 SelectItem 不允许空字符串值，用 'all' 哨兵映射「全部语言」(='')
const ALL_LANGUAGES = 'all'
const languageFilterModel = computed<string>({
  get: () => (languageFilter.value as string) || ALL_LANGUAGES,
  set: (v: string) => {
    languageFilter.value = v === ALL_LANGUAGES ? '' : v
  },
})
</script>

<template>
  <div class="space-y-4">
    <!-- 节点端口信息 -->
    <NodePortsDisplay
      v-if="nodeTypeInfo && currentNodeId"
      :inputs="nodeTypeInfo.inputs"
      :outputs="nodeTypeInfo.outputs"
      :node-id="currentNodeId"
    />

    <Separator v-if="nodeTypeInfo" />

    <!-- 目标仓库 -->
    <div class="space-y-2">
      <Label class="flex items-center gap-1">
        目标仓库
        <span class="text-destructive">*</span>
      </Label>
      <SmartInput
        v-model="repositoriesModel"
        :workflow-nodes="workflowNodes"
        :workflow-edges="workflowEdges"
        :current-node-id="currentNodeId ?? undefined"
        placeholder="输入 {{ 选择变量，或 {{$ 使用 JSONPath"
      />
      <p class="text-xs text-muted-foreground">
        使用 JSONPath 提取仓库 ID 列表，如 <code v-pre class="bg-muted px-1 rounded">{{$.input.repositories[*].id}}</code>
      </p>
    </div>

    <Separator />

    <!-- 检索查询 -->
    <div class="space-y-2">
      <Label class="flex items-center gap-1">
        检索查询
        <span class="text-destructive">*</span>
      </Label>
      <SmartInput
        v-model="query"
        :workflow-nodes="workflowNodes"
        :workflow-edges="workflowEdges"
        :current-node-id="currentNodeId ?? undefined"
        placeholder="输入检索文本，或 {{ 选择变量"
      />
      <p class="text-xs text-muted-foreground">
        根据此文本检索相关代码，支持模板变量
      </p>
    </div>

    <Separator />

    <!-- 检索参数 -->
    <div class="space-y-4">
      <Label>检索参数</Label>

      <!-- Top K -->
      <div class="space-y-2">
        <div class="flex items-center justify-between">
          <span class="text-sm">返回数量</span>
          <span class="text-sm font-mono bg-secondary px-2 py-0.5 rounded">{{ topK }}</span>
        </div>
        <SliderSingle
          v-model="topK"
          :min="1"
          :max="50"
          :step="1"
        />
        <p class="text-xs text-muted-foreground">
          每个仓库返回的最相关代码片段数量
        </p>
      </div>

      <!-- 相似度阈值 -->
      <div class="space-y-2">
        <div class="flex items-center justify-between">
          <span class="text-sm">相似度阈值</span>
          <span class="text-sm font-mono bg-secondary px-2 py-0.5 rounded">{{ scoreThreshold.toFixed(2) }}</span>
        </div>
        <SliderSingle
          :model-value="scoreThreshold * 100"
          :min="0"
          :max="100"
          :step="5"
          @update:model-value="v => scoreThreshold = v / 100"
        />
        <p class="text-xs text-muted-foreground">
          过滤低于此分数的结果，0 表示不过滤
        </p>
      </div>

      <!-- 语言过滤 -->
      <div class="space-y-2">
        <Label>语言过滤</Label>
        <Select v-model="languageFilterModel">
          <SelectTrigger class="w-full">
            <SelectValue placeholder="全部语言" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem :value="ALL_LANGUAGES">
              全部语言
            </SelectItem>
            <SelectItem
              v-for="opt in languageOptions.filter(o => o.value)"
              :key="opt.value"
              :value="opt.value"
            >
              {{ opt.label }}
            </SelectItem>
          </SelectContent>
        </Select>
        <p class="text-xs text-muted-foreground">
          可选，仅检索指定编程语言的代码
        </p>
      </div>
    </div>

    <Separator />

    <!-- 输出选项 -->
    <div class="space-y-3">
      <Label>输出选项</Label>

      <div class="flex items-center justify-between">
        <div>
          <span class="text-sm">包含代码内容</span>
          <p class="text-xs text-muted-foreground">
            在结果中包含完整代码片段
          </p>
        </div>
        <Switch v-model:checked="includeContent" />
      </div>

      <div class="flex items-center justify-between">
        <div>
          <span class="text-sm">格式化为 Markdown</span>
          <p class="text-xs text-muted-foreground">
            输出带语法高亮的代码块
          </p>
        </div>
        <Switch v-model:checked="formatAsMarkdown" />
      </div>
    </div>

    <!-- 使用提示 -->
    <div class="rounded-lg bg-muted/50 p-3 space-y-2">
      <p class="text-xs text-muted-foreground">
        <span class="icon-[lucide--info] mr-1" />
        输出变量说明：
      </p>
      <ul class="text-xs text-muted-foreground space-y-1 ml-4">
        <li>
          <code v-pre class="bg-background px-1 rounded">{{ nodes.[id].formatted_context }}</code>
          - 格式化的 Markdown 文本
        </li>
        <li>
          <code v-pre class="bg-background px-1 rounded">{{ nodes.[id].contexts }}</code>
          - 原始检索结果数组
        </li>
        <li>
          <code v-pre class="bg-background px-1 rounded">{{ nodes.[id].total }}</code>
          - 结果数量
        </li>
      </ul>
    </div>
  </div>
</template>
