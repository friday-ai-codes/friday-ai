import type { NodeComponent } from '@vue-flow/core'
import type { NodeTypeKey } from '~/types/workflow/registry'
/**
 * Vue Flow 节点类型注册
 *
 * 所有节点统一使用 BaseWorkflowNode（图标/颜色由 nodeVisuals 数据源驱动）。
 * parallel/join 使用 DynamicPortNode（需要动态端口管理）。
 */
import { markRaw } from 'vue'
import { NODE_REGISTRY } from '~/types/workflow/registry'
import AIPlanGenerationNode from './AIPlanGenerationNode.vue'
import BaseWorkflowNode from './BaseWorkflowNode.vue'
import DynamicPortNode from './DynamicPortNode.vue'
import { allNodeTypeKeys } from './nodeVisuals'

const baseNode = markRaw(BaseWorkflowNode) as unknown as NodeComponent
const dynamicNode = markRaw(DynamicPortNode) as unknown as NodeComponent
const aiPlanGenNode = markRaw(AIPlanGenerationNode) as unknown as NodeComponent

/** 特殊节点覆盖 */
const specialNodes: Record<string, NodeComponent> = {
  parallel: dynamicNode,
  join: dynamicNode,
  ai_plan_generation: aiPlanGenNode,
}

/** 从 NODE_REGISTRY + nodeVisuals 合并生成节点类型映射 */
const registryTypes = Object.fromEntries(
  (Object.keys(NODE_REGISTRY) as NodeTypeKey[]).map(key => [
    key,
    specialNodes[key] ?? baseNode,
  ]),
)

/** nodeVisuals 中有但 NODE_REGISTRY 中没有的节点类型也注册（如 manual_trigger） */
const visualOnlyTypes = Object.fromEntries(
  allNodeTypeKeys
    .filter(key => !(key in registryTypes))
    .map(key => [key, specialNodes[key] ?? baseNode]),
)

const registeredTypes: Record<string, NodeComponent> = {
  ...registryTypes,
  ...visualOnlyTypes,
}

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
