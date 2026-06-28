/**
 * useSignalLayer（P6 画布双层视图 · 信号订阅层）
 *
 * 画布默认只渲染「交付流」（实线主路径，附着插件折叠为宿主卡内 chip，不单独成节点）。
 * 信号层是一个**纯派生的渲染叠加层**：开启后，从每个附着了 notification/document 插件的
 * 宿主节点，按其子插件 `metadata.subscribeSignals`（reaction 配置 = SSOT）派生出「信号订阅边」
 * ——宿主 → 该能力的可视化目标（通知/文档），用**虚线 + 信号语义色**（复用 `SIGNAL_META`）
 * 渲染，明显区别于实线交付边。
 *
 * 红线：以 reaction 配置（子插件 subscribeSignals）为准派生，**不持久化新边、不写 store 业务边**；
 * 关闭信号层时本 composable 产出空集合，画布与现状完全一致（两层互不干扰）。
 *
 * clarification 是内部澄清回路通道（不订阅生命周期信号），不在信号层派生（恒跳过）。
 */
import type { Edge } from '@vue-flow/core'
import type { MaybeRefOrGetter } from 'vue'
import type { SlotCapability, SubscribableSignal } from '../slotTaxonomy'
import type { WorkflowNodeStore } from '~/types/workflow/store'
import { computed, toValue } from 'vue'
import {
  getNodeProvides,
  normalizeSubscribeSignals,
  SIGNAL_META,
  supportsSignalSubscription,
} from '../slotTaxonomy'

/** VueFlow 边 type 标识：信号订阅边用自定义边组件（SignalSubscriptionEdge.vue）渲染。 */
export const SIGNAL_EDGE_TYPE = 'signalSubscription'

/** 信号订阅边的 data 载荷（派生字段，非 store 事实源）。 */
export interface SignalSubscriptionEdgeData {
  /** 边类型判别（运行时合同 §2.7 边类型 `signal_subscription`）。 */
  kind: 'signal_subscription'
  /** 订阅的宿主信号名。 */
  signal: SubscribableSignal
  /** 信号语义色（复用 SIGNAL_META：成功绿 / 失败红 / 产出紫）。 */
  color: string
  /** 短标签（成功 / 失败 / 产出），供边中点 pill 展示。 */
  label: string
  /** 宿主能力（notification / document）。 */
  capability: SlotCapability
  /** 宿主节点 id（= source）。 */
  hostId: string
  /** 附着插件 id（= target，信号层下被「surfaced」为可视化目标节点）。 */
  pluginId: string
}

/** 信号订阅边（VueFlow Edge + 强类型 data）。 */
export type SignalSubscriptionEdge = Edge<SignalSubscriptionEdgeData>

/** 是否为附着子节点（插件）：带非空 metadata.parentNodeId。 */
function attachedParentId(node: WorkflowNodeStore): string | null {
  const pid = node.metadata?.parentNodeId
  return typeof pid === 'string' && pid.length > 0 ? pid : null
}

/**
 * 从 store 节点纯派生信号订阅边（无副作用、可独立单测）。
 *
 * 规则：
 * - 仅处理「附着插件」（有 parentNodeId）且其能力支持信号订阅（notification / document）。
 *   clarification 等不支持订阅的能力恒跳过。
 * - 每个插件按 `normalizeSubscribeSignals` 归一化后的订阅信号集，**每个信号派生一条边**
 *   （信号各有语义色，多订阅 = 多色边）；未显式订阅时归一为默认「完成」信号（绿）。
 * - source = 宿主节点 id；target = 插件 id；虚线 + 信号色 style。
 */
export function deriveSignalEdges(nodes: readonly WorkflowNodeStore[]): SignalSubscriptionEdge[] {
  const edges: SignalSubscriptionEdge[] = []
  for (const node of nodes) {
    const hostId = attachedParentId(node)
    if (!hostId)
      continue
    const capability = getNodeProvides(node.nodeType)
    if (!capability || !supportsSignalSubscription(capability))
      continue
    const signals = normalizeSubscribeSignals(
      capability,
      node.metadata?.subscribeSignals as readonly string[] | undefined,
    )
    for (const signal of signals) {
      const meta = SIGNAL_META[signal]
      edges.push({
        id: `signal::${hostId}::${node.id}::${signal}`,
        source: hostId,
        target: node.id,
        type: SIGNAL_EDGE_TYPE,
        // 虚线 + 信号语义色：明显区别于实线 gradient 交付边。
        style: {
          stroke: meta.color,
          strokeWidth: 1.5,
          strokeDasharray: '6 4',
          strokeOpacity: 0.9,
        },
        // 派生叠加层：不可选/不可删/不可聚焦（纯渲染，不进入 store 变更回路）。
        selectable: false,
        focusable: false,
        deletable: false,
        data: {
          kind: 'signal_subscription',
          signal,
          color: meta.color,
          label: meta.label,
          capability,
          hostId,
          pluginId: node.id,
        },
      })
    }
  }
  return edges
}

/**
 * 信号层 composable：按开关派生信号订阅边。
 * - `enabled` 关 → 恒空集合（画布与现状一致）。
 * - `enabled` 开 → 从 store 节点派生（reaction 配置为准）。
 */
export function useSignalLayer(
  nodes: MaybeRefOrGetter<readonly WorkflowNodeStore[]>,
  enabled: MaybeRefOrGetter<boolean>,
) {
  const signalEdges = computed<SignalSubscriptionEdge[]>(() =>
    toValue(enabled) ? deriveSignalEdges(toValue(nodes)) : [],
  )

  /** 信号边的目标插件 id 集（信号层下需把这些被折叠的附着子「surfaced」为可视化目标节点）。 */
  const signalTargetIds = computed<Set<string>>(
    () => new Set(signalEdges.value.map(e => e.target)),
  )

  return { signalEdges, signalTargetIds }
}
