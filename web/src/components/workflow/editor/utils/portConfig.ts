/**
 * 端口配置 — 从 X6 portGroups 迁移的共享工具函数。
 *
 * 保留节点端口逻辑，移除所有 X6 特定依赖（PortGroupConfig、workflowPortGroups 等）。
 * 仅保留 Vue Flow 需要的 PortMetadata 和 getDefaultPortsForNodeType。
 */
/**
 * 端口元数据接口（简化版，移除 X6 特定字段）。
 */
export interface PortMetadata {
 id: string
 group: string
}
/**
 * 触发器节点类型（无输入，一个输出）。
 */
const TRIGGER_NODE_TYPES = [
 'manual_trigger',
 'webhook_trigger',
 'feishu_event_trigger',
]
/**
 * 条件节点类型（一个输入，两个分支输出）。
 */
const CONDITION_NODE_TYPES = ['condition', 'human_approval']
/**
 * 带错误输出端口的节点类型（1 个输入，2 个输出：default + error）。
 */
const ERROR_OUTPUT_NODE_TYPES = [
 'create_branch',
 'create_pr',
 'merge_pr',
 'notify_feishu',
 'mcp_deploy',
]
/**
 * 根据输入/输出名称生成端口项。
 *
 * @param inputs - 输入端口名称数组
 * @param outputs - 输出端口名称数组
 * @returns 端口元数据数组
 */
function generatePortItems(inputs: string, outputs: string): PortMetadata {
 const items: PortMetadata =
 inputs.forEach((_name, index) => {
 items.push({ id: `input-${index}`, group: 'input' })
 })
 outputs.forEach((_name, index) => {
 items.push({ id: `output-${index}`, group: 'output' })
 })
 return items
}
/**
 * 获取节点类型的默认端口配置。
 * - 触发器节点: 0 输入, 1 输出
 * - 条件节点: 1 输入, 2 输出 (true/false 分支)
 * - 错误输出节点: 1 输入, 2 输出 (default/error)
 * - 动作节点: 1 输入, 1 输出
 *
 * @param nodeType - 节点类型
 * @returns 端口元数据数组
 */
export function getDefaultPortsForNodeType(nodeType: string): PortMetadata {
 if (TRIGGER_NODE_TYPES.includes(nodeType)) {
 return generatePortItems(, ['output'])
 }
 // ai_plan_approval: 1 输入, 2 输出 (approved/rejected)
 if (nodeType === 'ai_plan_approval') {
 return generatePortItems(['input'], ['approved', 'rejected'])
 }
 if (CONDITION_NODE_TYPES.includes(nodeType)) {
 return generatePortItems(['input'], ['true', 'false'])
 }
 if (ERROR_OUTPUT_NODE_TYPES.includes(nodeType)) {
 return generatePortItems(['input'], ['default', 'error'])
 }
 if (nodeType === 'parallel') {
 return generatePortItems(['input'], ['branch_0', 'branch_1'])
 }
 if (nodeType === 'join') {
 return generatePortItems(['input_0', 'input_1'], ['output'])
 }
 // 动作节点: 1 输入, 1 输出
 return generatePortItems(['input'], ['output'])
}
