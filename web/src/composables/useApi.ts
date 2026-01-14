import { ref } from 'vue'
import { toast } from 'vue-sonner'
export function useApi<T = any>(
 apiFunc: (...args: any) => Promise<T>,
 options: {
 showError?: boolean
 successMessage?: string
 onSuccess?: (data: T) => void
 onError?: (error: any) => void
 } = {}
) {
 const loading = ref(false)
 const error = ref<any>(null)
 const data = ref<T | null>(null)
 const execute = async (...args: any) => {
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
 } catch (err: any) {
 error.value = err
 const message = err.response?.data?.detail || err.message || '操作失败'
 if (options.showError !== false) {
 toast.error(message)
 }
 if (options.onError) {
 options.onError(err)
 }
 throw err
 } finally {
 loading.value = false
 }
 }
 return {
 loading,
 error,
 data,
 execute
 }
}