import type { Ref } from 'vue'
import { ref } from 'vue'
import { toast } from 'vue-sonner'
// 显式定义返回类型以避免类型推断问题
interface UseApiReturn<T> {
 loading: Ref<boolean>
 error: Ref<unknown>
 data: Ref<T | null>
 execute: (...args: unknown) => Promise<T>
}
export function useApi<T = unknown>(
 apiFunc: (...args: unknown) => Promise<T>,
 options: {
 showError?: boolean
 successMessage?: string
 onSuccess?: (data: T) => void
 onError?: (error: unknown) => void
 } = {},
): UseApiReturn<T> {
 const loading = ref(false)
 const error = ref<unknown>(null)
 const data = ref<T | null>(null) as Ref<T | null>
 const execute = async (...args: unknown): Promise<T> => {
 loading.value = true
 error.value = null
 try {
 const result = await apiFunc(...args)
 data.value = result
 if (options.successMessage) {
 toast.success(options.successMessage)
 }
 if (options.onSuccess) {
 options.onSuccess(result)
 }
 return result
 }
 catch (err: unknown) {
 error.value = err
 const errorObj = err as { response?: { data?: { detail?: string } }, message?: string }
 const message = errorObj.response?.data?.detail || errorObj.message || '操作失败'
 if (options.showError !== false) {
 toast.error(message)
 }
 if (options.onError) {
 options.onError(err)
 }
 throw err
 }
 finally {
 loading.value = false
 }
 }
 return {
 loading,
 error,
 data,
 execute,
 }
}
