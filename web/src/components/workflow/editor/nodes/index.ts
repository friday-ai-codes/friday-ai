/**
 * Vue Flow 节点类型注册
 *
 * 将 NODE_REGISTRY 中所有节点类型映射到 DefaultWorkflowNode。
 * Phase 会为各类型创建专用组件。
 */
import { markRaw } from 'vue'
import type { NodeComponent } from '@vue-flow/core'
import type { NodeTypeKey } from '~/types/workflow/registry'
import { NODE_REGISTRY } from '~/types/workflow/registry'
import DefaultWorkflowNode from './DefaultWorkflowNode.vue'
const rawNode = markRaw(DefaultWorkflowNode) as unknown as NodeComponent
/** 从 NODE_REGISTRY 动态生成节点类型映射 */
export const nodeTypes: Record<string, NodeComponent> = Object.fromEntries(
 (Object.keys(NODE_REGISTRY) as NodeTypeKey).map((key) => [key, rawNode]),
)
