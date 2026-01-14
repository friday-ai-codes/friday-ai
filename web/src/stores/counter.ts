import { defineStore } from 'pinia'
/**
 * 示例 Store
 * 用于演示 Pinia 的使用方式
 */
export const useCounterStore = defineStore('counter', => {
 const count = ref(0)
 const doubleCount = computed( => count.value * 2)
 function increment {
 count.value++
 }
 function decrement {
 count.value--
 }
 function reset {
 count.value = 0
 }
 return {
 count,
 doubleCount,
 increment,
 decrement,
 reset,
 }
})