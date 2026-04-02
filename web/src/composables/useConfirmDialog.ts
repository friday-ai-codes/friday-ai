import { ref } from 'vue'
interface ConfirmOptions {
 title?: string
 description: string
 confirmText?: string
 cancelText?: string
 variant?: 'default' | 'destructive'
}
const isOpen = ref(false)
const options = ref<ConfirmOptions>({ description: '' })
let resolvePromise: ((value: boolean) => void) | null = null
export function useConfirmDialog {
 function confirm(opts: ConfirmOptions | string): Promise<boolean> {
 const normalizedOpts = typeof opts === 'string' ? { description: opts }: opts
 options.value = normalizedOpts
 isOpen.value = true
 return new Promise<boolean>((resolve) => {
 resolvePromise = resolve
 })
 }
 function handleConfirm {
 isOpen.value = false
 resolvePromise?.(true)
 resolvePromise = null
 }
 function handleCancel {
 isOpen.value = false
 resolvePromise?.(false)
 resolvePromise = null
 }
 return {
 isOpen,
 options,
 confirm,
 handleConfirm,
 handleCancel,
 }
}
