import type { InjectionKey } from 'vue'

/**
 * 工作流画布聚焦能力的 provide/inject 契约。
 *
 * 背景：`fitView` 只能在 VueFlow 上下文（WorkflowCanvas）内调用，而触发聚焦的
 * IssuesPanel 位于 NodeConfigPanel 内，与 WorkflowCanvas 是**兄弟组件**，无法直接
 * 用 useVueFlow()。因此由共同祖先（workflows/[id].vue）provide 一个可变持有器，
 * WorkflowCanvas 挂载后把自身的 `focusNode` 写入持有器，IssuesPanel 注入后调用。
 *
 * inject 不可用 / 尚未注册时调用方应安全降级（no-op）。
 */
export type FocusNodeFn = (nodeId: string) => void

export interface WorkflowFocusContext {
  /** 由 WorkflowCanvas 注册的画布聚焦函数；未就绪时为 null */
  focusNode: FocusNodeFn | null
  /** 由 WorkflowCanvas 注册的一键自动布局函数（横向 LR + fitView）；未就绪时为 null */
  autoLayout: (() => void) | null
}

export const WorkflowFocusKey: InjectionKey<WorkflowFocusContext> = Symbol('workflow-focus')
