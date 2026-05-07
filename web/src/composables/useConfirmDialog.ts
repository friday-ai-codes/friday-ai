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
 // reka-ui 的 AlertDialogAction 在点击时会同步触发 update:open=false,
 // 而模板里 @update:open 又会调到 handleCancel。如果这里同步 resolve(false),
 // 会先于后续的 @click="handleConfirm" 把 promise 锁死,导致点"确认"也得到 false。
 // 因此把 resolve(false) 推到 microtask:同步 click 数组里的 handleConfirm 先抢到
 // resolvePromise 并 resolve(true)+置空,微任务再检查时看到 null 就跳过。
 function handleCancel {
 isOpen.value = false
 if (!resolvePromise)
 return
 const r = resolvePromise
 queueMicrotask( => {
 if (resolvePromise === r) {
 resolvePromise = null
 r(false)
 }
 })
 }
 return {
 isOpen,
 options,
 confirm,
 handleConfirm,
 handleCancel,
 }
}
