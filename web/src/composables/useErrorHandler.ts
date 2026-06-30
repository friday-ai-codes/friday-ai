import { ApiError } from '~/api/client'
import { useToast } from '~/composables/useToast'

const STATUS_MESSAGES: Record<number, string> = {
  401: '请重新登录',
  403: '无权限',
  404: '资源不存在',
  429: '操作太快了，请稍后再试',
  500: '服务器错误',
}

/**
 * 从 unknown 错误中提取用户可读的错误消息（纯函数）
 *
 * 优先级：ApiError.detail > STATUS_MESSAGES[status] > TypeError 网络检测 > Error.message > 默认值
 */
export function extractErrorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    return e.detail || STATUS_MESSAGES[e.status] || '操作失败'
  }
  if (e instanceof TypeError && e.message === 'Failed to fetch') {
    return '网络连接失败，请检查网络'
  }
  if (e instanceof Error) {
    return e.message
  }
  return '操作失败'
}

/**
 * 统一错误处理 composable
 *
 * 通过 useToast 显示错误通知，不直接依赖 vue-sonner。
 */
export function useErrorHandler() {
  const { error: showError } = useToast()

  function handleError(e: unknown, context?: string): void {
    const message = extractErrorMessage(e)
    // context 作为「动作」前缀，统一补「失败」；若调用方已自带「失败」则不重复（避免「…失败失败」）。
    const title = context
      ? (context.endsWith('失败') ? context : `${context}失败`)
      : '操作失败'
    showError(title, message)
  }

  return { handleError }
}
