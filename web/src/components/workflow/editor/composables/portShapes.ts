/**
 * 端口能力契约形状（shape）纯逻辑工具（SLOT-03 前端判定核心）。
 *
 * 职责：
 * - `arePortShapesCompatible`：连接两端 shape 的兼容纯函数（前端权威即时判定，
 *   后端 `WorkflowGraphValidator._validate_port_shapes` 仍是保存时兜底防线）。
 * - `resolvePortShape`：按 node_type + handle 从 `useNodeTypesStore` 取端口 shape。
 * - `SHAPE_DISPLAY_KEY` / `shapeDisplayName`：shape → 中文友好名（不向 UI 暴露英文标识符）。
 *
 * 性能：本模块为纯函数 + O(1) store 查找，不打日志、不建每帧新对象，
 * 可安全用于高频拖拽（isValidConnection）路径。
 */
import { useNodeTypesStore } from '~/stores/useNodeTypesStore'

/**
 * 两端口 shape 是否契约兼容。
 *
 * 口径与后端 `_validate_port_shapes` 完全一致（**空契约=通配** 为零回归命门）：
 * - 任一端为空/undefined（含未声明、`default`、`error` 等通用端口 shape 恒空）→ `true`（放行）。
 * - 双端非空且相等 → `true`。
 * - 双端非空且不等 → `false`（拒绝）。
 */
export function arePortShapesCompatible(
  srcShape: string | undefined,
  tgtShape: string | undefined,
): boolean {
  // 空契约通配：任一端无 shape 则放行（零回归命门）。
  if (!srcShape || !tgtShape)
    return true
  return srcShape === tgtShape
}

/**
 * 按 node_type + handleId 从 store 解析端口 shape。
 *
 * - `group='output'` 查 outputs，`group='input'` 查 inputs，按 `name===handleId` 匹配。
 * - store 未就绪（无该节点类型）/ 未知端口 → 返回 `undefined`（不抛）。
 */
export function resolvePortShape(
  nodeType: string,
  handleId: string,
  group: 'input' | 'output',
): string | undefined {
  const nt = useNodeTypesStore().getNodeType(nodeType)
  if (!nt)
    return undefined
  const ports = group === 'output' ? nt.outputs : nt.inputs
  return ports?.find(p => p.name === handleId)?.shape
}

/**
 * 7 个 typed shape → i18n key（`workflow.editor.shape.*`）。
 * 用于校验提示展示中文友好名，未映射的 shape 退化为空串（不暴露未知英文标识符）。
 */
export const SHAPE_DISPLAY_KEY: Record<string, string> = {
  clarification_request: 'workflow.editor.shape.clarificationRequest',
  clarification_answer: 'workflow.editor.shape.clarificationAnswer',
  feishu_message: 'workflow.editor.shape.feishuMessage',
  feishu_document: 'workflow.editor.shape.feishuDocument',
  technical_plan: 'workflow.editor.shape.technicalPlan',
  coding_assignment: 'workflow.editor.shape.codingAssignment',
  approval_result: 'workflow.editor.shape.approvalResult',
}

/**
 * shape → 中文显示名：有映射用 `t(key)`；无映射回退原 shape（再无则空串）。
 * 不传 `t` 时（如纯 boolean 校验路径）直接回退原 shape——该串不会展示给用户。
 */
export function shapeDisplayName(
  shape: string | undefined,
  t?: (key: string) => string,
): string {
  if (!shape)
    return ''
  const key = SHAPE_DISPLAY_KEY[shape]
  if (key && t)
    return t(key)
  return shape
}
