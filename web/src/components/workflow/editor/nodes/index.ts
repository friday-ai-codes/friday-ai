/**
 * Vue Flow 节点类型注册
 *
 * 按 NODE_REGISTRY 中每个节点的 category 映射到对应类别组件。
 * parallel/join 特殊节点使用 DynamicPortNode。
 */
import { markRaw } from 'vue'
import type { NodeComponent } from '@vue-flow/core'
import type { NodeCategory, NodeTypeKey } from '~/types/workflow/registry'
import { NODE_REGISTRY } from '~/types/workflow/registry'
import TriggerNode from './TriggerNode.vue'
import ActionNode from './ActionNode.vue'
import ControlNode from './ControlNode.vue'
import IntegrationNode from './IntegrationNode.vue'
import DynamicPortNode from './DynamicPortNode.vue'
/** 类别到组件的映射 */
const categoryComponents: Record<NodeCategory, NodeComponent> = {
 trigger: markRaw(TriggerNode) as unknown as NodeComponent,
 action: markRaw(ActionNode) as unknown as NodeComponent,
 control: markRaw(ControlNode) as unknown as NodeComponent,
 integration: markRaw(IntegrationNode) as unknown as NodeComponent,
 ai: markRaw(ActionNode) as unknown as NodeComponent,
}
/** 特殊节点覆盖（parallel/join 使用动态端口组件） */
const specialNodes: Record<string, NodeComponent> = {
 parallel: markRaw(DynamicPortNode) as unknown as NodeComponent,
 join: markRaw(DynamicPortNode) as unknown as NodeComponent,
}
/** 从 NODE_REGISTRY 动态生成节点类型映射 */
export const nodeTypes: Record<string, NodeComponent> = Object.fromEntries(
 (Object.keys(NODE_REGISTRY) as NodeTypeKey).map((key) => [
 key,
 specialNodes[key] ?? categoryComponents[NODE_REGISTRY[key].category],
 ]),
)
