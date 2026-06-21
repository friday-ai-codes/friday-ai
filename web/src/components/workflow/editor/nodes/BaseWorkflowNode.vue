<script setup lang="ts">
/**
 * BaseWorkflowNode - 所有自定义节点的基础壳组件
 *
 * 负责：glassmorphism 外观、动态 Handle 渲染、选中态高亮。
 * 图标和颜色从 nodeVisuals 统一数据源获取。
 */
import { Handle, Position, useVueFlow } from '@vue-flow/core'
import { NodeToolbar } from '@vue-flow/node-toolbar'
import { Copy, Play, Trash2 } from 'lucide-vue-next'
import { storeToRefs } from 'pinia'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from '~/composables/useToast'
import { useNodeTypesStore } from '~/stores/useNodeTypesStore'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
import { getNodeDefinition } from '~/types/workflow/registry'
import { generateShortId } from '~/utils/shortId'
import { randomUUID } from '~/utils/uuid'
import NodeInsertMenu from '../NodeInsertMenu.vue'
import { useNodeStyle } from './composables/useNodeStyle'
import { getNodeVisual } from './nodeVisuals'

interface PortItem {
  id: string
  group: 'input' | 'output'
}

const props = withDefaults(defineProps<{
  id: string
  data: {
    name: string
    nodeType: string
    disabled?: boolean
    [key: string]: unknown
  }
  selected?: boolean
  /** 隐藏指定方向的 Handle，供 DynamicPortNode 等自行管理端口 */
  hideHandles?: 'input' | 'output' | 'both' | 'none'
}>(), { hideHandles: 'none' })

const store = useWorkflowsStore()
const nodeTypesStore = useNodeTypesStore()
const { dirtyNodeIds } = storeToRefs(store)
const { getSelectedNodes } = useVueFlow()
const router = useRouter()
const { success, error: toastError } = useToast()

const visual = computed(() => getNodeVisual(props.data.nodeType))
const style = computed(() => useNodeStyle(visual.value.color).value)

/**
 * Handle 端口集以后端 NodePort（useNodeTypesStore.inputs/outputs）为准（D-04）。
 * computed 依赖 store ref → fetchNodeTypes 异步就绪后自动重渲染（RESEARCH Pitfall 1）。
 * store 未就绪（首帧/离线）时回退最小端口（单 in/单 out + default），避免首帧空 Handle。
 */
const ports = computed<PortItem[]>(() => {
  const nt = nodeTypesStore.getNodeType(props.data.nodeType)
  if (!nt) {
    return [
      { id: 'default', group: 'input' },
      { id: 'default', group: 'output' },
    ]
  }
  return [
    ...nt.inputs.map(p => ({ id: p.name, group: 'input' as const })),
    ...nt.outputs.map(p => ({ id: p.name, group: 'output' as const })),
  ]
})
const inputPorts = computed(() => ports.value.filter(p => p.group === 'input'))
const outputPorts = computed(() => ports.value.filter(p => p.group === 'output'))

/** 多选时隐藏单节点工具栏，改用画布级统一工具栏 */
const isMultiSelect = computed(() => getSelectedNodes.value.length > 1)

/** 当前节点是否有未保存的配置修改 */
const isDirty = computed(() => dirtyNodeIds.value.has(props.id))

/**
 * 节点配置摘要候选字段（参考 dify 节点 body 显示关键配置）：
 * 按顺序在 config 中查找首个有值的字段，渲染「标签：值」一行，让用户不点开也知节点意图。
 */
const SUMMARY_FIELDS: { keys: string[], label: string }[] = [
  { keys: ['model', 'model_name', 'modelName'], label: '模型' },
  { keys: ['provider'], label: '供应商' },
  { keys: ['event_type', 'eventType', 'trigger_event', 'event'], label: '事件' },
  { keys: ['expression', 'condition'], label: '条件' },
  { keys: ['tool_name', 'tool', 'toolName'], label: '工具' },
  { keys: ['language', 'lang'], label: '语言' },
  { keys: ['url', 'endpoint'], label: 'URL' },
  { keys: ['prompt', 'system_prompt', 'instruction'], label: '提示词' },
  { keys: ['dataset', 'dataset_id', 'collection'], label: '知识库' },
  { keys: ['repository', 'repo', 'branch'], label: '仓库' },
]

function summarizeConfig(config: Record<string, unknown> | undefined): string | null {
  if (!config)
    return null
  for (const { keys, label } of SUMMARY_FIELDS) {
    for (const k of keys) {
      const v = config[k]
      if (typeof v === 'string' && v.trim()) {
        const text = v.trim()
        return `${label}：${text.length > 40 ? `${text.slice(0, 40)}…` : text}`
      }
      if (typeof v === 'number')
        return `${label}：${v}`
    }
  }
  return null
}

/** 节点摘要：优先显示用户填写的描述，否则从 config 提取关键字段 */
const nodeSummary = computed<string | null>(() => {
  const desc = typeof props.data.description === 'string' ? props.data.description.trim() : ''
  if (desc)
    return desc
  return summarizeConfig(props.data.config as Record<string, unknown> | undefined)
})

/** 单节点测试 loading 状态 */
const isTesting = ref(false)

/** 多端口时沿垂直方向均匀分布的 top 百分比（横向 L→R 布局，Handle 竖排） */
function portTop(index: number, total: number): string {
  if (total <= 1)
    return '50%'
  return `${((index + 1) / (total + 1)) * 100}%`
}

/**
 * 在指定方向追加并自动连线一个新节点（复用 NodeInsertMenu 选择）。
 * - output（右）：新节点放本节点右侧，边 本节点 → 新节点
 * - input（左）：新节点放本节点左侧，边 新节点 → 本节点
 */
function appendNode(direction: 'input' | 'output', nodeType: string) {
  const current = store.nodes.find(n => n.id === props.id)
  if (!current)
    return
  const def = getNodeDefinition(nodeType)
  const newNodeId = randomUUID()
  const offset = 340
  store.addNode({
    id: newNodeId,
    shortId: generateShortId(),
    nodeType,
    name: def?.displayName || nodeType,
    description: '',
    position: {
      x: (current.position?.x ?? 0) + (direction === 'output' ? offset : -offset),
      y: current.position?.y ?? 0,
    },
    config: (def?.defaultConfig as Record<string, unknown>) ?? {},
    onError: 'abort',
    retryTimes: 0,
    retryDelay: 5,
    nodeTimeoutSeconds: null,
    fallbackValues: null,
    runCondition: null,
    metadata: {},
  })
  if (direction === 'output') {
    store.addEdge({
      id: `edge-${props.id}-${newNodeId}-${Date.now()}`,
      source: props.id,
      target: newNodeId,
      sourcePort: outputPorts.value[0]?.id ?? 'default',
      targetPort: 'default',
      label: undefined,
      condition: null,
    })
  }
  else {
    store.addEdge({
      id: `edge-${newNodeId}-${props.id}-${Date.now()}`,
      source: newNodeId,
      target: props.id,
      sourcePort: 'default',
      targetPort: inputPorts.value[0]?.id ?? 'default',
      label: undefined,
      condition: null,
    })
  }
}

function handleDelete() {
  store.removeNode(props.id)
}

function handleCopy() {
  const currentNode = store.nodes.find(n => n.id === props.id)
  if (!currentNode)
    return
  const newNode = {
    ...JSON.parse(JSON.stringify(currentNode)),
    id: randomUUID(),
    shortId: generateShortId(),
    position: {
      x: (currentNode.position?.x ?? 0) + 50,
      y: (currentNode.position?.y ?? 0) + 50,
    },
  }
  newNode.name = `${currentNode.name} (副本)`
  store.addNode(newNode)
}

async function handleTest() {
  if (isTesting.value)
    return
  isTesting.value = true
  try {
    const result = await store.executeWorkflow({}, false, props.id)
    if (result?.execution_id) {
      success('单节点测试已启动')
      router.push(`/executions/${result.execution_id}`)
    }
  }
  catch (e: unknown) {
    toastError((e as Error).message || '启动测试失败')
  }
  finally {
    isTesting.value = false
  }
}
</script>

<template>
  <div>
    <!-- 单选浮动工具栏：仅单选时显示，多选时隐藏（由画布级统一工具栏接管） -->
    <NodeToolbar
      :is-visible="selected && !isMultiSelect"
      :position="Position.Top"
      :offset="10"
    >
      <div class="flex gap-1 bg-card/90 backdrop-blur-sm border border-border/50 rounded-xl p-1 shadow-lg">
        <button
          class="p-1.5 rounded-lg hover:bg-emerald-500/10 transition-colors text-muted-foreground hover:text-emerald-600 disabled:opacity-50 disabled:cursor-not-allowed"
          title="测试到此节点"
          :disabled="isTesting"
          @click.stop="handleTest"
        >
          <span v-if="isTesting" class="icon-[lucide--loader-circle] animate-spin w-3.5 h-3.5" />
          <Play v-else class="w-3.5 h-3.5" />
        </button>
        <button
          class="p-1.5 rounded-lg hover:bg-muted transition-colors text-muted-foreground hover:text-foreground"
          title="复制节点"
          @click.stop="handleCopy"
        >
          <Copy class="w-3.5 h-3.5" />
        </button>
        <button
          class="p-1.5 rounded-lg hover:bg-destructive/10 transition-colors text-muted-foreground hover:text-destructive"
          title="删除节点"
          @click.stop="handleDelete"
        >
          <Trash2 class="w-3.5 h-3.5" />
        </button>
      </div>
    </NodeToolbar>

    <div
      class="w-[200px] bg-card/80 backdrop-blur-sm border rounded-2xl p-3 transition-all duration-200 group hover:shadow-md hover:border-opacity-70"
      :class="[style.borderColor, selected ? `ring-2 ${style.ringColor} shadow-lg` : '', data.disabled ? 'grayscale opacity-50' : '']"
    >
      <!-- Input Handles：永远左入（target=Left）；触发器节点 inputPorts 为空则不渲染 -->
      <Handle
        v-for="(port, i) in inputPorts"
        v-show="inputPorts.length > 0 && hideHandles !== 'input' && hideHandles !== 'both'"
        :id="port.id"
        :key="port.id"
        type="target"
        :position="Position.Left"
        :style="{ top: portTop(i, inputPorts.length) }"
      />

      <!-- 入方向 hover "+"：在左侧追加并连线一个新节点（触发器无入端口则不显示） -->
      <div
        v-if="inputPorts.length > 0 && hideHandles !== 'input' && hideHandles !== 'both'"
        class="nodrag nopan absolute -left-7 top-1/2 -translate-y-1/2 z-10 opacity-0 group-hover:opacity-100 transition-opacity"
      >
        <NodeInsertMenu @select="(nt) => appendNode('input', nt)" />
      </div>

      <!-- 头部：图标 + 名称 -->
      <div class="relative flex items-center gap-2 mb-2">
        <div class="bg-gradient-to-br rounded-lg p-1.5" :class="[style.iconBg]">
          <slot name="icon">
            <component :is="visual.icon" class="w-4 h-4" :class="style.iconColor" />
          </slot>
        </div>
        <span class="text-sm font-medium text-foreground truncate">
          {{ data.name }}
        </span>
        <span
          v-if="isDirty"
          class="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-amber-400 shadow-sm"
          title="配置已修改，未保存"
        />
      </div>

      <!-- 内容 slot：未自定义时回退为配置摘要（描述 / 关键 config 字段） -->
      <slot name="content">
        <p
          v-if="nodeSummary"
          class="mt-0.5 text-xs text-muted-foreground leading-snug line-clamp-2"
        >
          {{ nodeSummary }}
        </p>
      </slot>

      <!-- Output Handles：永远右出（source=Right） -->
      <Handle
        v-for="(port, i) in outputPorts"
        v-show="hideHandles !== 'output' && hideHandles !== 'both'"
        :id="port.id"
        :key="port.id"
        type="source"
        :position="Position.Right"
        :style="{ top: portTop(i, outputPorts.length) }"
      />

      <!-- 出方向 hover "+"：在右侧追加并连线一个新节点 -->
      <div
        v-if="outputPorts.length > 0 && hideHandles !== 'output' && hideHandles !== 'both'"
        class="nodrag nopan absolute -right-7 top-1/2 -translate-y-1/2 z-10 opacity-0 group-hover:opacity-100 transition-opacity"
      >
        <NodeInsertMenu @select="(nt) => appendNode('output', nt)" />
      </div>
    </div>
  </div>
</template>
