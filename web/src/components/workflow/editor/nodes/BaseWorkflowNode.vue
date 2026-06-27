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
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useDesignTimeVariables } from '~/composables/useDesignTimeVariables'
import { useToast } from '~/composables/useToast'
import { useNodeTypesStore } from '~/stores/useNodeTypesStore'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
import { getNodeDefinition } from '~/types/workflow/registry'
import { generateEndpointToken } from '~/utils/endpointToken'
import { generateShortId } from '~/utils/shortId'
import { randomUUID } from '~/utils/uuid'
import { useConnectionDragState } from '../composables/useConnectionDragState'
import { useImCapability } from '../composables/useImCapability'
import NodeInsertMenu from '../NodeInsertMenu.vue'
import { useNodeStyle } from './composables/useNodeStyle'
import { getNodeVisual } from './nodeVisuals'

interface PortItem {
  id: string
  group: 'input' | 'output'
  label: string
  /** 端口能力契约 shape（typed=非空 → 方形+shape 色；空=通用流圆形，零回归）。 */
  shape?: string
}

/** 出口端口语义 → 颜色/标签：default=成功(绿)、error=失败(红)、need_clarification=需澄清(琥珀)，其余中性 */
type PortKind = 'success' | 'error' | 'clarify' | 'neutral'

const props = withDefaults(defineProps<{
  id: string
  data: {
    name: string
    nodeType: string
    disabled?: boolean
    [key: string]: unknown
  }
  selected?: boolean
  /** 隐藏指定方向的 Handle，供 BranchNode 等自行管理端口 */
  hideHandles?: 'input' | 'output' | 'both' | 'none'
}>(), { hideHandles: 'none' })

function portKind(id: string): PortKind {
  if (id === 'error')
    return 'error'
  if (id === 'default')
    return 'success'
  if (id === 'need_clarification')
    return 'clarify'
  return 'neutral'
}

const PORT_DOT_COLOR: Record<PortKind, string> = {
  success: '#10b981',
  error: '#ef4444',
  clarify: '#f59e0b',
  neutral: '#94a3b8',
}

/**
 * 能力 shape → 色板（UI-SPEC「能力 shape 色板」）。
 * shape 非空时优先于 handle-id 语义色；O(1) 查表，避免每帧建新对象。
 */
const SHAPE_DOT_COLOR: Record<string, string> = {
  clarification_request: '#f59e0b',
  clarification_answer: '#f59e0b',
  feishu_message: '#06b6d4',
  feishu_document: '#6366f1',
  technical_plan: '#8b5cf6',
  coding_assignment: '#a78bfa',
  approval_result: '#10b981',
}

/**
 * handle 背景/描边色（着色优先级，UI-SPEC「着色优先级」）：
 * shape 非空 → `SHAPE_DOT_COLOR[shape]`（未知 shape 回退语义色）；
 * shape 空 → 回退既有 `PORT_DOT_COLOR[portKind(id)]`（保 default 绿/error 红零回归）。
 */
function handleColor(port: PortItem): string {
  if (port.shape)
    return SHAPE_DOT_COLOR[port.shape] ?? PORT_DOT_COLOR[portKind(port.id)]
  return PORT_DOT_COLOR[portKind(port.id)]
}

/** 卡内分支列表用：仅文字色（语义色由行末圆点 + 文字共同传达） */
const PORT_TEXT_CLASS: Record<PortKind, string> = {
  success: 'text-emerald-600',
  error: 'text-red-600',
  clarify: 'text-amber-600',
  neutral: 'text-muted-foreground',
}

const store = useWorkflowsStore()
const nodeTypesStore = useNodeTypesStore()
const { dirtyNodeIds } = storeToRefs(store)
const { getSelectedNodes } = useVueFlow()
const router = useRouter()
const { success, error: toastError } = useToast()
const { t } = useI18n()

// 拖拽连接态（SLOT-03）：驱动 input handle 的 compatible-highlight / forbidden 类。
const { dragging, isCompatibleTarget } = useConnectionDragState()
// 图级 IM 能力门控（SLOT-04 / CONTEXT D）：缺 chat_id 源时降级 IM 依赖节点。
const { isImGated } = useImCapability()

/** 本节点是否因缺 IM 源被门控（视觉降级 + 锁徽标 + 引导 tooltip）。 */
const imGated = computed(() => isImGated(props.data.nodeType))

/**
 * 附着父节点 id（SLOT-04，跨 plan 数据契约）：来源**固定**为
 * `props.data.metadata.parentNodeId`——93-03 transform 固化的同源字段，非空即本节点为附着子。
 */
const attachedParentId = computed<string | null>(() => {
  const meta = props.data.metadata as Record<string, unknown> | undefined
  const pid = meta?.parentNodeId
  return typeof pid === 'string' && pid ? pid : null
})

/** 某 input port 在拖拽态下的兼容/禁止类（idle 时为空，零回归既有外观）。 */
function inputHandleClass(port: PortItem): string[] {
  const cls: string[] = []
  if (port.shape)
    cls.push('slot-handle-typed', 'slot-handle-input')
  if (dragging.value)
    cls.push(isCompatibleTarget(props.data.nodeType, port.id) ? 'compatible-highlight' : 'forbidden')
  if (imGated.value)
    cls.push('slot-handle-gated')
  return cls
}

/** output port 的 shape 类（typed → 圆角方形实心凸点；空 → 既有圆形）。 */
function outputHandleClass(port: PortItem): string[] {
  return port.shape ? ['slot-handle-typed', 'slot-handle-output'] : []
}

/** input handle style：typed shape → 圆角方形描边凹槽（透明底）；空 → 既有圆形（仅 top）。 */
function inputHandleStyle(port: PortItem, index: number, total: number): Record<string, string> {
  const base: Record<string, string> = { top: portTop(index, total) }
  if (port.shape) {
    base.borderRadius = '4px'
    base.border = `2px solid ${handleColor(port)}`
    base.background = 'transparent'
  }
  return base
}

/** output handle style：typed shape → 圆角方形实心；空 → 既有圆形，二者均着色（shape 优先）。 */
function outputHandleStyle(port: PortItem): Record<string, string> {
  const base: Record<string, string> = { backgroundColor: handleColor(port) }
  if (port.shape)
    base.borderRadius = '4px'
  return base
}

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
      { id: 'default', group: 'input', label: '输入' },
      { id: 'default', group: 'output', label: '输出' },
    ]
  }
  return [
    ...nt.inputs.map(p => ({ id: p.name, group: 'input' as const, label: p.label || p.name, shape: p.shape })),
    ...nt.outputs.map(p => ({ id: p.name, group: 'output' as const, label: p.label || p.name, shape: p.shape })),
  ]
})
const inputPorts = computed(() => ports.value.filter(p => p.group === 'input'))
const outputPorts = computed(() => ports.value.filter(p => p.group === 'output'))

/** 多选时隐藏单节点工具栏，改用画布级统一工具栏 */
const isMultiSelect = computed(() => getSelectedNodes.value.length > 1)

/** 当前节点是否有未保存的配置修改 */
const isDirty = computed(() => dirtyNodeIds.value.has(props.id))

/**
 * 配置字段中文标签字典（参考 dify 节点 body 的只读配置预览）。
 * config_schema 字段名为 snake_case 英文，缺少中文 title，这里集中映射。
 */
const CONFIG_LABELS: Record<string, string> = {
  method: '方法',
  secret: '密钥',
  delay_seconds: '延迟(秒)',
  delay_until: '延迟至',
  wait_mode: '等待',
  merge_strategy: '合并',
  timeout: '超时',
  timeout_seconds: '超时(秒)',
  timeout_action: '超时动作',
  list_source: '列表来源',
  execution_mode: '执行模式',
  max_concurrency: '并发',
  work_item_id: '工作项',
  work_item_type: '工作项类型',
  project_key: '项目',
  title: '标题',
  require_all: '需全部',
  timeout_hours: '超时(时)',
  model: '模型',
  model_name: '模型',
  provider: '供应商',
  prompt: '提示词',
  system_prompt: '提示词',
  language: '语言',
  url: 'URL',
  endpoint: '地址',
  tool: '工具',
  tool_name: '工具',
  repository: '仓库',
  branch: '分支',
  event_type: '事件',
  pass_input: '传入',
  default_branch: '默认分支',
}

// 设计态变量（上游节点输出）path → 友好标签映射，用于把 {{nodes.x.field}} 渲染成
// 与编辑器变量胶囊一致的可读名（如「飞书事件触发 - 工作项 ID」），而非原始模板字面量。
const { designTimeVariables } = useDesignTimeVariables(
  computed(() => store.nodes as any),
  computed(() => store.edges as any),
  computed(() => props.id),
)
const varLabelByPath = computed<Map<string, string>>(() => {
  const m = new Map<string, string>()
  for (const v of designTimeVariables.value) m.set(v.path, v.label)
  return m
})

/** 把变量路径渲染为友好名：优先用设计态变量标签，回退取末段字段名。 */
function friendlyVarName(path: string): string {
  const label = varLabelByPath.value.get(path)
  if (label)
    return label
  const segs = path.split('.').filter(Boolean)
  return segs[segs.length - 1] || path
}

// 卡片不展示的敏感/噪声字段（密钥类，详情在配置面板查看）
const HIDDEN_CHIP_KEYS = new Set([
  'endpoint_token',
  'api_key',
  'secret',
  'app_secret',
  'provider_credential_id',
])

const SINGLE_VAR_RE = /^\{\{(.+?)\}\}$/
const ANY_VAR_RE = /\{\{(.+?)\}\}/g

interface ConfigChip {
  label: string
  /** var=变量绑定（胶囊）/ auto=自动 / plain=普通文本 */
  kind: 'var' | 'auto' | 'plain'
  display: string
}

function truncate(s: string, max = 22): string {
  return s.length > max ? `${s.slice(0, max)}…` : s
}

/** 把单个配置字段格式化为卡片 chip；不展示的值返回 null。 */
function buildChip(key: string, raw: unknown): ConfigChip | null {
  if (raw === null || raw === undefined)
    return null
  const label = CONFIG_LABELS[key] ?? key
  if (typeof raw === 'boolean')
    return { label, kind: 'plain', display: raw ? '是' : '否' }
  if (typeof raw === 'number')
    return { label, kind: 'plain', display: String(raw) }
  if (typeof raw !== 'string')
    return null
  const s = raw.trim()
  if (!s)
    return null
  if (s === '__auto__')
    return { label, kind: 'auto', display: '自动' }
  const single = s.match(SINGLE_VAR_RE)
  if (single)
    return { label, kind: 'var', display: friendlyVarName(single[1].trim()) }
  if (s.includes('{{')) {
    // 混合文本：把内嵌变量替换成友好名后截断展示
    const sub = s.replace(ANY_VAR_RE, (_m, p) => friendlyVarName(String(p).trim()))
    return { label, kind: 'plain', display: truncate(sub) }
  }
  return { label, kind: 'plain', display: truncate(s) }
}

/**
 * 节点卡片配置预览：按 config_schema 字段顺序取最多 3 个有值字段。
 * 变量绑定渲染为友好胶囊（不暴露 {{nodes.xxx}} 原文），密钥字段不展示。
 */
const configChips = computed<ConfigChip[]>(() => {
  const config = (props.data.config ?? {}) as Record<string, unknown>
  const nt = nodeTypesStore.getNodeType(props.data.nodeType)
  const order = nt?.config_schema?.properties
    ? Object.keys(nt.config_schema.properties)
    : Object.keys(config)
  const chips: ConfigChip[] = []
  for (const key of order) {
    if (chips.length >= 3)
      break
    if (HIDDEN_CHIP_KEYS.has(key))
      continue
    const chip = buildChip(key, config[key])
    if (chip)
      chips.push(chip)
  }
  return chips
})

/** 节点描述（用户填写） */
const nodeDescription = computed<string | null>(() => {
  const d = typeof props.data.description === 'string' ? props.data.description.trim() : ''
  return d || null
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
  // 飞书事件触发节点：插入即生成专属端点 token，立即可展示端点 URL（与拖拽一致）
  const newConfig: Record<string, unknown> = { ...((def?.defaultConfig as Record<string, unknown>) ?? {}) }
  if (nodeType === 'feishu_event_trigger') {
    if (!newConfig.endpoint_token)
      newConfig.endpoint_token = generateEndpointToken()
    if (!newConfig.verification_token)
      newConfig.verification_token = generateEndpointToken()
  }
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
    config: newConfig,
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
      class="relative w-[200px] bg-card/80 backdrop-blur-sm border rounded-2xl p-3 transition-all duration-200 group hover:shadow-md hover:border-opacity-70"
      :class="[style.borderColor, selected ? `ring-2 ${style.ringColor} shadow-lg` : '', data.disabled ? 'grayscale opacity-50' : '', imGated ? 'opacity-40' : '']"
    >
      <!-- 附着子节点徽标（SLOT-04）：data.metadata.parentNodeId 非空 → 左上角『附着』+ tooltip -->
      <div
        v-if="attachedParentId"
        class="absolute -top-2 left-2 z-10 rounded-md bg-amber-500/12 px-1.5 py-0.5 text-[10px] font-medium leading-none text-amber-600"
        :title="t('workflow.editor.slot.attachedHint')"
      >
        {{ t('workflow.editor.slot.attachedBadge') }}
      </div>

      <!-- IM 能力门控锁徽标（SLOT-04 / CONTEXT D）：缺 chat_id 源 → 右上角锁 + 引导 tooltip -->
      <div
        v-if="imGated"
        class="absolute -top-2 -right-2 z-10 flex h-5 w-5 items-center justify-center rounded-full border border-border/60 bg-card shadow-sm"
        :title="t('workflow.editor.slot.imGatedHint')"
      >
        <span class="icon-[lucide--lock] h-3 w-3 text-amber-600" />
      </div>

      <!-- Input Handles：永远左入（target=Left）；触发器节点 inputPorts 为空则不渲染 -->
      <Handle
        v-for="(port, i) in inputPorts"
        v-show="inputPorts.length > 0 && hideHandles !== 'input' && hideHandles !== 'both'"
        :id="port.id"
        :key="port.id"
        type="target"
        :position="Position.Left"
        :class="inputHandleClass(port)"
        :style="inputHandleStyle(port, i, inputPorts.length)"
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

      <!-- 内容 slot：未自定义时回退为配置预览（标签 + 友好值/变量胶囊）+ 备注 -->
      <slot name="content">
        <div v-if="configChips.length || nodeDescription" class="mt-1 space-y-1">
          <div
            v-for="chip in configChips"
            :key="chip.label"
            class="flex items-center gap-1.5 text-[11px] leading-tight"
          >
            <span class="shrink-0 text-muted-foreground/60">{{ chip.label }}</span>
            <!-- 变量绑定：友好胶囊（不暴露 {{nodes.xxx}} 原文） -->
            <span
              v-if="chip.kind === 'var'"
              class="inline-flex min-w-0 items-center gap-1 rounded-md bg-primary/10 px-1.5 py-0.5 font-medium text-primary"
            >
              <span class="icon-[lucide--braces] w-2.5 h-2.5 shrink-0 opacity-70" />
              <span class="truncate">{{ chip.display }}</span>
            </span>
            <!-- 自动 -->
            <span
              v-else-if="chip.kind === 'auto'"
              class="rounded-md bg-muted px-1.5 py-0.5 text-muted-foreground"
            >
              {{ chip.display }}
            </span>
            <!-- 普通值 -->
            <span v-else class="truncate text-foreground/80">{{ chip.display }}</span>
          </div>
          <p
            v-if="nodeDescription"
            class="text-xs text-muted-foreground leading-snug line-clamp-2"
          >
            {{ nodeDescription }}
          </p>
        </div>
      </slot>

      <!-- 单出口：居中圆点（source=Right），保持极简外观 -->
      <Handle
        v-if="outputPorts.length === 1"
        v-show="hideHandles !== 'output' && hideHandles !== 'both'"
        :id="outputPorts[0].id"
        :key="outputPorts[0].id"
        type="source"
        :position="Position.Right"
        :class="outputHandleClass(outputPorts[0])"
        :style="outputHandleStyle(outputPorts[0])"
      />

      <!-- 多出口：卡片内底部「分支列表」。每行 = 语义文案 + 行末圆点（即出口 Handle）。
           连线自卡片右缘各圆点向右引出，文案落在卡内左侧，从结构上杜绝标签压线。
           每行 relative → Handle 的 Position.Right 以「行」为基准，圆点贴右缘并随行垂直居中。 -->
      <div
        v-if="outputPorts.length > 1 && hideHandles !== 'output' && hideHandles !== 'both'"
        class="-mx-3 mt-2.5 space-y-1 border-t border-border/40 px-3 pr-0 pt-2"
      >
        <div
          v-for="port in outputPorts"
          :key="port.id"
          class="relative flex items-center justify-end"
        >
          <span
            class="mr-2.5 whitespace-nowrap text-[10px] font-medium leading-none"
            :class="PORT_TEXT_CLASS[portKind(port.id)]"
          >
            {{ port.label }}
          </span>
          <Handle
            :id="port.id"
            type="source"
            :position="Position.Right"
            :class="outputHandleClass(port)"
            :style="outputHandleStyle(port)"
          />
        </div>
      </div>

      <!-- 出方向 hover "+"：在右侧追加并连线一个新节点。
           多出口节点不显示居中 "+"（语义不明）——从具体出口拖拽连线即可 -->
      <div
        v-if="outputPorts.length === 1 && hideHandles !== 'output' && hideHandles !== 'both'"
        class="nodrag nopan absolute -right-7 top-1/2 -translate-y-1/2 z-10 opacity-0 group-hover:opacity-100 transition-opacity"
      >
        <NodeInsertMenu @select="(nt) => appendNode('output', nt)" />
      </div>
    </div>
  </div>
</template>

<style scoped>
/* SLOT-03 拖拽态机：兼容目标 input handle 高亮放大 + emerald 光环；不兼容降透明 + 禁止光标。
   形状（圆角方形/圆形）与着色由 inline style 决定，此处只叠加拖拽态视觉，零回归 idle 外观。 */
.compatible-highlight {
  width: 14px !important;
  height: 14px !important;
  box-shadow: 0 0 0 4px hsl(142 71% 45% / 0.25) !important;
  z-index: 5;
}

.forbidden {
  opacity: 0.3 !important;
  cursor: not-allowed !important;
}

/* IM 门控 handle：缺 chat_id 源时禁止落点光标（节点整体降透明由卡片 class 控制）。 */
.slot-handle-gated {
  cursor: not-allowed !important;
}

@media (prefers-reduced-motion: reduce) {
  .compatible-highlight {
    transition: none !important;
  }
}
</style>
