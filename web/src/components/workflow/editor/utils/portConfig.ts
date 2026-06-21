/**
 * 端口配置 — Vue Flow 节点 Handle 的 ID 与分组配置。
 *
 * 端口 ID 使用与后端 NodePort.name 一致的语义化名称（如 "default"、
 * "approved"、"rejected"），确保模板创建的工作流和用户手动连线的
 * 工作流都能正确匹配 Handle。
 *
 * SSOT-02 / D-04：画布 Handle 的正常渲染路径已迁移到 `useNodeTypesStore`
 * 的 inputs/outputs（见 BaseWorkflowNode.vue）。本文件的
 * `getDefaultPortsForNodeType` 不再参与正常渲染，仅作为 `migratePortId`
 * 的静态端口顺序回退源（用于把存量 edge 的旧式索引句柄迁移为语义名）。
 * `migratePortId` 按 D-02 保留——禁删，兼容存量 edge。
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
export const TRIGGER_NODE_TYPES = [
  'manual_trigger',
  'webhook_trigger',
  'feishu_event_trigger',
]

/**
 * 审批节点类型（一个输入，两个分支输出：approved/rejected）。
 */
const APPROVAL_NODE_TYPES = ['human_approval']

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
 * 直接使用名称作为端口 ID，与后端 NodePort.name 保持一致。
 */
function generatePortItems(inputs: string[], outputs: string[]): PortMetadata[] {
  const items: PortMetadata[] = []

  for (const name of inputs) {
    items.push({ id: name, group: 'input' })
  }

  for (const name of outputs) {
    items.push({ id: name, group: 'output' })
  }

  return items
}

/**
 * 获取节点类型的默认端口配置。
 * - 触发器节点: 0 输入, 1 输出
 * - 审批节点: 1 输入, 2 输出 (approved/rejected)
 * - 条件节点: 1 输入, 2 输出 (true/false 分支)
 * - 错误输出节点: 1 输入, 2 输出 (default/error)
 * - 动作节点: 1 输入, 1 输出
 */
export function getDefaultPortsForNodeType(nodeType: string): PortMetadata[] {
  if (TRIGGER_NODE_TYPES.includes(nodeType)) {
    return generatePortItems([], ['default'])
  }

  if (APPROVAL_NODE_TYPES.includes(nodeType)) {
    return generatePortItems(['default'], ['approved', 'rejected'])
  }

  if (nodeType === 'condition') {
    return generatePortItems(['default'], ['true', 'false'])
  }

  if (ERROR_OUTPUT_NODE_TYPES.includes(nodeType)) {
    return generatePortItems(['default'], ['default', 'error'])
  }

  if (nodeType === 'parallel') {
    return generatePortItems(['default'], ['branch_0', 'branch_1'])
  }

  if (nodeType === 'join') {
    return generatePortItems(['input_0', 'input_1'], ['default'])
  }

  return generatePortItems(['default'], ['default'])
}

/**
 * 将旧版索引式端口 ID（如 "output-0"）迁移为语义化名称。
 * 用于加载已有工作流时的向后兼容。
 */
export function migratePortId(
  handle: string,
  nodeType: string | undefined,
  direction: 'input' | 'output',
): string {
  if (!/^(input|output)-\d+$/.test(handle)) {
    return handle
  }

  if (!nodeType) {
    return 'default'
  }

  const ports = getDefaultPortsForNodeType(nodeType)
  const dirPorts = ports.filter(p => p.group === direction)
  const index = Number.parseInt(handle.split('-')[1], 10)

  if (index < dirPorts.length) {
    return dirPorts[index].id
  }

  return 'default'
}
