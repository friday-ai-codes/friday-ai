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
