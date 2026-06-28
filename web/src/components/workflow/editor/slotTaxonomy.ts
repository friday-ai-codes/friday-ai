/**
 * 插槽能力分类学（SLOT-04 拼积木式插槽 · 单一配置来源）
 *
 * 把工作流节点分为「宿主（带槽）」与「插件（可插入槽）」两个角色，按**能力类型**匹配：
 * 同一能力槽接受**一类**插件（非钉死某个节点）。调整哪些节点带哪些槽，只需改本文件。
 *
 * - `SlotCapability`：能力（=槽类型）。
 * - `CAPABILITY_META`：每种能力的标题/提示/色板。
 * - `NODE_PROVIDES`：插件节点 → 它提供的能力（可被拖入对应能力槽）。
 * - `NODE_SLOTS`：宿主节点 → 它暴露的能力槽列表。
 * - `resolveSlotEdges`：拖入插件后自动建立的数据流边（按能力区分接线方向）。
 */

import type { Component } from 'vue'
import { FileText, MessageCircleQuestion, Send } from 'lucide-vue-next'

export type SlotCapability = 'clarification' | 'notification' | 'document'

export interface CapabilityMeta {
  /** 槽标题（卡内显示） */
  label: string
  /** 空槽提示（拖入引导） */
  hint: string
  /** 命中态提示（兼容插件拖近时） */
  activeHint: string
  /** shape 色（与 BaseWorkflowNode SHAPE_DOT_COLOR 同口径） */
  color: string
  /** 槽图标组件（lucide-vue-next，纯展示） */
  icon: Component
}

export const CAPABILITY_META: Record<SlotCapability, CapabilityMeta> = {
  clarification: {
    label: '澄清',
    hint: '拖入「澄清卡」',
    activeHint: '松开放入澄清卡',
    color: '#f59e0b',
    icon: MessageCircleQuestion,
  },
  notification: {
    label: '通知',
    hint: '拖入「飞书通知」',
    activeHint: '松开放入通知',
    color: '#06b6d4',
    icon: Send,
  },
  document: {
    label: '文档',
    hint: '拖入「飞书文档生成」',
    activeHint: '松开放入文档生成',
    color: '#6366f1',
    icon: FileText,
  },
}

/** 插件节点 → 它提供的能力（拖入匹配能力槽即附着）。 */
export const NODE_PROVIDES: Record<string, SlotCapability> = {
  clarification_card: 'clarification',
  notify_feishu_im: 'notification',
  notify_feishu: 'notification',
  feishu_doc_create: 'document',
}

/** 宿主节点 → 它暴露的能力槽（按 stage 顺序展示）。 */
export const NODE_SLOTS: Record<string, SlotCapability[]> = {
  ai_plan_research: ['clarification', 'document', 'notification'],
  ai_coding_dispatcher: ['document', 'notification'],
  ai_coding: ['document', 'notification'],
  human_approval: ['document', 'notification'],
  create_pr: ['notification'],
  merge_pr: ['notification'],
  create_branch: ['notification'],
  mcp_deploy: ['notification'],
  create_group_chat: ['notification'],
  create_work_item_chat: ['notification'],
  board_split: ['notification'],
}

/** 该节点暴露的能力槽列表（无则空数组）。 */
export function getNodeSlots(nodeType: string): SlotCapability[] {
  return NODE_SLOTS[nodeType] ?? []
}

// ============================================================================
// 信号反应器（SLOT P4 缺氧精髓）：把能力插槽从「类型匹配拼图」升级为「订阅宿主生命
// 周期信号的反应器」。附着插件实例把已选信号存到 `metadata.subscribeSignals: string[]`，
// 保存工作流时由后端 config_sync 转换为 WorkflowReaction（reaction 配置为 SSOT）。
// 信号名与后端 `workflows.reactions.signal.SIGNAL_NAMES` 子集对齐。
// ============================================================================

/** 可订阅信号（与后端 SIGNAL_NAMES 子集对齐；clarification 是内部回路通道，不在此列）。 */
export type SubscribableSignal = 'node.completed' | 'node.failed' | 'artifact.produced'

export const SIG_NODE_COMPLETED: SubscribableSignal = 'node.completed'
export const SIG_NODE_FAILED: SubscribableSignal = 'node.failed'
export const SIG_ARTIFACT_PRODUCED: SubscribableSignal = 'artifact.produced'

export interface SignalMeta {
  /** chip 上切换按钮短标签（成功/失败/产出） */
  label: string
  /** 切换按钮 title 提示 */
  hint: string
  /** 语义色（与 handle 语义色同口径：成功绿/失败红/产出紫） */
  color: string
}

/** 信号 → 文案/色板（文案内联在 ts，规避 zh-CN.json 整文件提交坑）。 */
export const SIGNAL_META: Record<SubscribableSignal, SignalMeta> = {
  'node.completed': { label: '成功', hint: '宿主节点成功完成时触发', color: '#10b981' },
  'node.failed': { label: '失败', hint: '宿主节点失败时触发', color: '#ef4444' },
  'artifact.produced': { label: '产出', hint: '产出技术方案等交付物时触发', color: '#8b5cf6' },
}

/**
 * 各能力可订阅的信号集合（信号反应器的「可选项」）：
 * - clarification：内部澄清回路通道，不订阅生命周期信号（恒空）。
 * - notification / document：可订阅 成功 / 失败 / 产出。
 * 列表顺序即 UI 展示顺序（稳定，避免抖动）。
 */
export const CAPABILITY_SIGNALS: Record<SlotCapability, SubscribableSignal[]> = {
  clarification: [],
  notification: [SIG_NODE_COMPLETED, SIG_NODE_FAILED, SIG_ARTIFACT_PRODUCED],
  document: [SIG_NODE_COMPLETED, SIG_ARTIFACT_PRODUCED, SIG_NODE_FAILED],
}

/** 默认订阅信号（空槽提示「（默认订阅完成）」即指此）。 */
export const DEFAULT_SUBSCRIBE_SIGNAL: SubscribableSignal = SIG_NODE_COMPLETED

/** 该能力可订阅的信号集合（不支持订阅的能力返回空数组）。 */
export function getSubscribableSignals(capability: SlotCapability): SubscribableSignal[] {
  return CAPABILITY_SIGNALS[capability] ?? []
}

/** 该能力是否支持信号订阅（notification/document 支持，clarification 不支持）。 */
export function supportsSignalSubscription(capability: SlotCapability): boolean {
  return getSubscribableSignals(capability).length > 0
}

/**
 * 归一化某能力的已选订阅信号：
 * - 过滤非该能力可订阅的非法值、去重；
 * - 为空（或全非法）时回退默认（node.completed）；
 * - 不支持订阅的能力（clarification）恒返回 []；
 * - 按 `CAPABILITY_SIGNALS` 顺序稳定排序。
 */
export function normalizeSubscribeSignals(
  capability: SlotCapability,
  signals: readonly string[] | undefined,
): SubscribableSignal[] {
  const allowed = getSubscribableSignals(capability)
  if (allowed.length === 0)
    return []
  const allowedSet = new Set<string>(allowed)
  const picked = new Set<string>()
  for (const s of signals ?? []) {
    if (allowedSet.has(s))
      picked.add(s)
  }
  if (picked.size === 0)
    return [DEFAULT_SUBSCRIBE_SIGNAL]
  return allowed.filter(s => picked.has(s))
}

/**
 * 切换某信号的订阅态（chip 上点「成功/失败/产出」）。
 * - 取消最后一个信号时不允许清空（保持原集合，至少订阅一个）；
 * - 非该能力可订阅的信号忽略（返回归一化后的原集合）。
 */
export function toggleSubscribeSignal(
  capability: SlotCapability,
  current: readonly string[] | undefined,
  signal: SubscribableSignal,
): SubscribableSignal[] {
  const normalized = normalizeSubscribeSignals(capability, current)
  if (!getSubscribableSignals(capability).includes(signal))
    return normalized
  if (normalized.includes(signal)) {
    const next = normalized.filter(s => s !== signal)
    if (next.length === 0)
      return normalized // 不允许清空，至少保留一个订阅
    return normalizeSubscribeSignals(capability, next)
  }
  return normalizeSubscribeSignals(capability, [...normalized, signal])
}

/** 空槽提示：支持订阅的能力追加「（默认订阅完成）」注脚。 */
export function getEmptySlotHint(capability: SlotCapability): string {
  const base = CAPABILITY_META[capability].hint
  return supportsSignalSubscription(capability) ? `${base}（默认订阅完成）` : base
}

/** 该节点提供的能力（非插件返回 null）。 */
export function getNodeProvides(nodeType: string): SlotCapability | null {
  return NODE_PROVIDES[nodeType] ?? null
}

/** 插件能力是否匹配某宿主槽。 */
export function isPluginCompatible(pluginType: string, capability: SlotCapability): boolean {
  return getNodeProvides(pluginType) === capability
}

export interface SlotEdgeSpec {
  source: string
  target: string
  sourcePort: string
  targetPort: string
}

/**
 * 从宿主可用 output 端口里挑「主成功出口」：优先 default，否则第一个非 error/clarify 出口
 * （如 human_approval 取 approved）。用于 notification/document 的下游接线。
 */
function pickSuccessOutput(hostOutputs: string[]): string {
  if (hostOutputs.includes('default'))
    return 'default'
  return hostOutputs.find(o => o !== 'error' && o !== 'clarify') ?? 'default'
}

/**
 * 拖入插件后应建立的数据流边（按能力区分方向）：
 * - clarification：宿主 `clarify`→插件 `clarification_request`，插件 `clarification_answer`→宿主 `resume`
 *   （双向澄清回路；宿主须具备 clarify/resume 端口）。
 * - notification / document：宿主主成功出口 → 插件 `default`（下游附加动作）。
 */
export function resolveSlotEdges(params: {
  hostId: string
  hostOutputs: string[]
  hostInputs: string[]
  pluginId: string
  capability: SlotCapability
}): SlotEdgeSpec[] {
  const { hostId, hostOutputs, hostInputs, pluginId, capability } = params
  if (capability === 'clarification') {
    const edges: SlotEdgeSpec[] = []
    if (hostOutputs.includes('clarify'))
      edges.push({ source: hostId, target: pluginId, sourcePort: 'clarify', targetPort: 'clarification_request' })
    if (hostInputs.includes('resume'))
      edges.push({ source: pluginId, target: hostId, sourcePort: 'clarification_answer', targetPort: 'resume' })
    return edges
  }
  // notification / document：宿主完成 → 插件执行
  return [{ source: hostId, target: pluginId, sourcePort: pickSuccessOutput(hostOutputs), targetPort: 'default' }]
}
