// 组合式函数导出
// 这里导出的函数会被 unplugin-auto-import 自动导入
/**
 * 示例组合式函数
 * 用于演示 composables 的使用方式
 */
export function useExample {
 const count = ref(0)
 function increment {
 count.value++
 }
 function decrement {
 count.value--
 }
 return {
 count: readonly(count),
 increment,
 decrement,
 }
}