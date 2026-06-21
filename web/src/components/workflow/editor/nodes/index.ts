import type { NodeComponent } from '@vue-flow/core'
/**
 * Vue Flow 节点类型注册
 *
 * 所有节点统一使用 BaseWorkflowNode（图标/颜色由 nodeVisuals 数据源驱动）。
 * condition/parallel 使用 BranchNode（分支在卡片内各自一个出口 handle，命名对齐后端 branch_i）。
 */
import { markRaw } from 'vue'
import AIPlanGenerationNode from './AIPlanGenerationNode.vue'
import BaseWorkflowNode from './BaseWorkflowNode.vue'
import BranchNode from './BranchNode.vue'
import { allNodeTypeKeys } from './nodeVisuals'

const baseNode = markRaw(BaseWorkflowNode) as unknown as NodeComponent
const branchNode = markRaw(BranchNode) as unknown as NodeComponent
const aiPlanGenNode = markRaw(AIPlanGenerationNode) as unknown as NodeComponent

/** 特殊节点覆盖 */
const specialNodes: Record<string, NodeComponent> = {
  condition: branchNode,
  parallel: branchNode,
  ai_plan_generation: aiPlanGenNode,
}

/**
 * 从 nodeVisuals（前端视觉源全集）生成节点类型映射。
 * 节点定义已收敛到 useNodeTypesStore（运行时源），此处仅需 Vue Flow 组件注册。
 */
const registeredTypes: Record<string, NodeComponent> = Object.fromEntries(
  allNodeTypeKeys.map(key => [key, specialNodes[key] ?? baseNode]),
)

/**
 * 使用 Proxy 为未注册的节点类型提供 fallback，
 * 避免数据库中残留旧类型（如 generate_plan）时 Vue Flow 报 "Node type is missing" 警告。
 */
export const nodeTypes: Record<string, NodeComponent> = new Proxy(registeredTypes, {
  get(target, prop, receiver) {
    if (typeof prop === 'string' && !(prop in target)) {
      return baseNode
    }
    return Reflect.get(target, prop, receiver)
  },
})
