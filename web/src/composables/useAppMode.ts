import { ref, watch } from 'vue'
export type AppMode = 'friday' | 'chat'
function resolveInitialMode: AppMode {
 if (typeof window === 'undefined') {
 return 'friday'
 }
 const savedMode = localStorage.getItem('app-mode') as AppMode | null
 return savedMode || 'friday'
}
// 模块级共享 ref，所有组件共用同一响应式状态
const mode = ref<AppMode>(resolveInitialMode)
watch(mode, v => localStorage.setItem('app-mode', v))
// Chat 数据是否已初始化（切到 chat 模式时懒加载）
const chatInitialized = ref(false)
export function useAppMode {
 return {
 mode,
 chatInitialized,
 setMode(m: AppMode) {
 mode.value = m
 },
 }
}
