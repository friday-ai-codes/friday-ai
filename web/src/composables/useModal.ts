import type { Component, Raw } from 'vue'
import { useModal as useVfmModal } from 'vue-final-modal'
export interface ModalOptions<T = unknown> {
 /** 弹窗组件 */
 component: Raw<Component>
 /** 传递给弹窗组件的 attrs/props */
 attrs?: Record<string, unknown>
 /** 弹窗关闭时的回调 */
 onClosed?: => void
 /** 弹窗确认时的回调，返回 Promise 用于异步确认 */
 onConfirm?: (result: T) => void | Promise<void>
 /** 弹窗取消时的回调 */
 onCancel?: => void
}
export interface ModalInstance<T = unknown> {
 /** 打开弹窗 */
 open: => Promise<string>
 /** 关闭弹窗 */
 close: => Promise<string>
 /** 销毁弹窗 */
 destroy: => void
 /** 等待弹窗结果（Promise 形式） */
 result: Promise<T | undefined>
}
/**
 * 命令式弹窗 composable
 *
 * @example
 * ```ts
 * import { useModal } from '~/composables/useModal'
 * import EditFormModal from './EditFormModal.vue'
 *
 * const { open, result } = useModal({
 * component: markRaw(EditFormModal),
 * attrs: {
 * title: '编辑项目',
 * data: projectData,
 * },
 * onConfirm: (result) => {
 * // handle confirm
 * },
 * onCancel: => {
 * // handle cancel
 * },
 * })
 *
 * await open
 * 或者使用 Promise 形式
 * const data = await result
 * ```
 */
export function useModal<T = unknown>(options: ModalOptions<T>): ModalInstance<T> {
 let resolveResult: (value: T | undefined) => void
 let rejectResult: (reason?: unknown) => void
 const resultPromise = new Promise<T | undefined>((resolve, reject) => {
 resolveResult = resolve
 rejectResult = reject
 })
 const modal = useVfmModal({
 component: options.component,
 attrs: {
 ...options.attrs,
 onConfirm: handleConfirm,
 onCancel: handleCancel,
 onClosed: => {
 options.onClosed?.
 },
 },
 })
 async function handleConfirm(data: T) {
 try {
 await options.onConfirm?.(data)
 resolveResult(data)
 await modal.close
 }
 catch (error) {
 rejectResult(error)
 }
 }
 async function handleCancel {
 options.onCancel?.
 resolveResult(undefined)
 await modal.close
 }
 return {
 open: modal.open,
 close: modal.close,
 destroy: modal.destroy,
 result: resultPromise,
 }
}
/**
 * 快速打开弹窗并等待结果
 *
 * @example
 * ```ts
 * const result = await openModal({
 * component: markRaw(ConfirmModal),
 * attrs: { message: '确定删除？' },
 * })
 * if (result) {
 * // 用户确认了
 * }
 * ```
 */
export async function openModal<T = unknown>(options: ModalOptions<T>): Promise<T | undefined> {
 const modal = useModal<T>(options)
 await modal.open
 return modal.result
}
