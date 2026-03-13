/**
 * Vue Flow 节点类型注册
 *
 * 所有节点统一使用 BaseWorkflowNode（图标/颜色由 nodeVisuals 数据源驱动）。
 * parallel/join 使用 DynamicPortNode（需要动态端口管理）。
 */
import { markRaw } from 'vue'
import type { NodeComponent } from '@vue-flow/core'
import type { NodeTypeKey } from '~/types/workflow/registry'
import { NODE_REGISTRY } from '~/types/workflow/registry'
import BaseWorkflowNode from './BaseWorkflowNode.vue'
import DynamicPortNode from './DynamicPortNode.vue'
import AIPlanGenerationNode from './AIPlanGenerationNode.vue'
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
 (Object.keys(NODE_REGISTRY) as NodeTypeKey).map((key) => [
 key,
 specialNodes[key] ?? baseNode,
 ]),
)
/** nodeVisuals 中有但 NODE_REGISTRY 中没有的节点类型也注册（如 manual_trigger） */
const visualOnlyTypes = Object.fromEntries(
 allNodeTypeKeys
 .filter((key) => !(key in registryTypes))
 .map((key) => [key, specialNodes[key] ?? baseNode]),
)
export const nodeTypes: Record<string, NodeComponent> = {
 ...registryTypes,
 ...visualOnlyTypes,
}
