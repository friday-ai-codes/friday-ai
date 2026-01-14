/**
 * Toast 通知组合式函数
 * 封装 sonner toast 功能
 */
import { toast } from 'vue-sonner'
export function useToast {
 /**
 * 成功通知
 */
 function success(message: string, description?: string) {
 toast.success(message, {
 description,
 duration: 3000,
 })
 }
 /**
 * 错误通知
 */
 function error(message: string, description?: string) {
 toast.error(message, {
 description,
 duration: 5000,
 })
 }
 /**
 * 警告通知
 */
 function warning(message: string, description?: string) {
 toast.warning(message, {
 description,
 duration: 4000,
 })
 }
 /**
 * 信息通知
 */
 function info(message: string, description?: string) {
 toast.info(message, {
 description,
 duration: 3000,
 })
 }
 /**
 * 加载中通知（返回 dismiss 函数）
 */
 function loading(message: string) {
 return toast.loading(message)
 }
 /**
 * Promise 通知
 */
 function promise<T>(
 promise: Promise<T>,
 options: {
 loading: string
 success: string | ((data: T) => string)
 error: string | ((error: Error) => string)
 },
 ) {
 return toast.promise(promise, options)
 }
 /**
 * 关闭所有通知
 */
 function dismissAll {
 toast.dismiss
 }
 return {
 success,
 error,
 warning,
 info,
 loading,
 promise,
 dismissAll,
 // 导出原始 toast 以便高级用法
 toast,
 }
}