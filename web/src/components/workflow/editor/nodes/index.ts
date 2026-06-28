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
 *
 * 同时 trap `has`：Vue Flow 内部用 `type in nodeTypes` 判定组件是否存在，
 * 仅 trap `get` 时未注册类型会被判为缺失而回退到内置默认节点（不渲染自定义 Handle/插槽）。
 * `has` 对任意字符串 key 返回 true，确保 `get` 的 baseNode fallback 真正被采用。
 */
export const nodeTypes: Record<string, NodeComponent> = new Proxy(registeredTypes, {
  get(target, prop, receiver) {
    if (typeof prop === 'string' && !(prop in target)) {
      return baseNode
    }
    return Reflect.get(target, prop, receiver)
  },
  has(target, prop) {
    if (typeof prop === 'string') {
      return true
    }
    return Reflect.has(target, prop)
  },
})
