/**
 * useExecutionDag — 将 workflow_definition + node_executions + timeline 合并为 Vue Flow 节点/边
 *
 * 独立于编辑器的 useWorkflowsStore，避免只读视图和编辑视图的状态冲突。
 */
import type { Edge, Node, NodeComponent } from '@vue-flow/core'
import type { Ref } from 'vue'
import type {
  NodeExecution,
  TimelineData,
  WorkflowDefinition,
  WorkflowExecution,
} from '~/stores/useExecutionsStore'
import type { NodeCost, SubStepProgress } from '~/types/execution'
import { MarkerType } from '@vue-flow/core'
import { computed, markRaw } from 'vue'
import GradientEdge from '~/components/workflow/editor/edges/GradientEdge.vue'
import ExecutionNode from '../ExecutionNode.vue'
import { deriveLifecycleFromStatus, type LifecyclePhase, normalizeLifecyclePhase } from './lifecycleBadge'

/** Vue Flow 执行节点的 data 载荷类型 */
export interface ExecutionNodeData {
  nodeType: string
  name: string
  status: string
  duration: number | null
  startedAt: string | null
  isBottleneck: boolean
  bottleneckLevel: 'critical' | 'warning' | null
  nodeExecution: NodeExecution | null
  config: Record<string, unknown>
  /** 运行中节点的实时 elapsed 秒数（由 useNodeTimer 注入） */
  elapsed?: number
  /** 节点级成本数据（由页面层从 CostBreakdown 注入） */
  cost?: NodeCost
  /** 是否可以从此节点继续执行（失败 + 定义未变更） */
  canResume?: boolean
  /** 从此继续按钮的回调（由 ExecutionDagView 注入） */
  onResumeClick?: (nodeId: string) => void
  /** 子步骤进度摘要（折叠时显示） */
  subStepProgress?: SubStepProgress | null
  /** 是否为 AI 节点（有子步骤能力） */
  isAINode?: boolean
  /** 子步骤点击回调（打开详情） */
  onSubStepClick?: (nodeExecutionId: string, subStepId: string) => void
  /** 是否为调试暂停中的节点 */
  isDebugPaused?: boolean
  /** 调试放行按钮回调 */
  onDebugRelease?: (nodeId: string) => void
  /** 调试跳过按钮回调 */
  onDebugSkip?: (nodeId: string) => void
  /** 该节点是否设置了断点 */
  hasBreakpoint?: boolean
  /** 切换断点的回调 */
  onToggleBreakpoint?: (nodeId: string) => void
  /** 是否为调试执行（控制断点指示器显示） */
  isDebugExecution?: boolean
  /** P5：节点生命周期相位（WS 投影优先，缺省从 status 兜底） */
  lifecycle?: LifecyclePhase
  /** P5：收敛轮次（澄清/修订态有值） */
  round?: number | null
  /** P5：收敛轮次上限 */
  maxRounds?: number | null
}

/** 自定义节点类型注册 */
export const executionNodeTypes: Record<string, NodeComponent> = {
  execution: markRaw(ExecutionNode) as unknown as NodeComponent,
}

/** 自定义边类型注册（复用编辑器的 GradientEdge） */
export const executionEdgeTypes = {
  gradient: markRaw(GradientEdge),
}

/**
 * 将 workflow_definition + node_executions + timeline 数据合并为 Vue Flow 格式。
 */
export function useExecutionDag(
  execution: Ref<WorkflowExecution | null>,
  timelineData: Ref<TimelineData | null>,
  definitionChanged?: Ref<boolean>,
  statusOverride?: (nodeExecution: NodeExecution) => string | undefined,
) {
  const dagNodes = computed<Node<ExecutionNodeData>[]>(() => {
    const exec = execution.value
    if (!exec?.workflow_definition)
      return []

    const definition: WorkflowDefinition = exec.workflow_definition
    const execMap = new Map<string, NodeExecution>(
      (exec.node_executions ?? []).map(ne => [ne.node, ne]),
    )
    const bottleneckMap = new Map(
      (timelineData.value?.nodes ?? [])
        .filter(n => n.is_bottleneck)
        .map(n => [n.node_id, n]),
    )

    const AI_NODE_TYPES = ['ai_prompt', 'ai_coding', 'ai_plan_generation', 'ai_coding_dispatcher']

    return definition.nodes?.map((defNode) => {
      const ne = execMap.get(defNode.id)
      const bn = bottleneckMap.get(defNode.id)
      const nodeStatus = (ne ? statusOverride?.(ne) : undefined) ?? ne?.status ?? 'pending'
      // P5：生命周期相位 —— WS 投影 lifecycle 优先，缺省从节点 status 兜底（静态加载/旧执行）。
      const lifecycle: LifecyclePhase = ne?.lifecycle
        ? normalizeLifecyclePhase(ne.lifecycle)
        : deriveLifecycleFromStatus(nodeStatus)
      return {
        id: defNode.id,
        type: 'execution',
        position: { ...defNode.position },
        data: {
          nodeType: defNode.node_type,
          name: defNode.name,
          status: nodeStatus,
          duration: ne?.duration ?? null,
          startedAt: ne?.started_at ?? null,
          isBottleneck: bn?.is_bottleneck ?? false,
          bottleneckLevel: bn?.bottleneck_level ?? null,
          nodeExecution: ne ?? null,
          config: defNode.config ?? {},
          canResume: nodeStatus === 'failed' && !(definitionChanged?.value ?? false),
          subStepProgress: ne?.sub_step_progress ?? null,
          isAINode: AI_NODE_TYPES.includes(defNode.node_type),
          isDebugPaused: exec.debug_paused_at_node === defNode.id,
          lifecycle,
          round: ne?.round ?? null,
          maxRounds: ne?.max_rounds ?? null,
        },
      }
    }) ?? []
  })

  const dagEdges = computed<Edge[]>(() => {
    const exec = execution.value
    if (!exec?.workflow_definition)
      return []

    const definition: WorkflowDefinition = exec.workflow_definition
    return definition.edges?.map(defEdge => ({
      id: defEdge.id,
      source: defEdge.source,
      target: defEdge.target,
      sourceHandle: defEdge.sourcePort || 'default',
      targetHandle: defEdge.targetPort || 'default',
      type: 'gradient',
      markerEnd: MarkerType.ArrowClosed,
    })) ?? []
  })

  return { dagNodes, dagEdges }
}
