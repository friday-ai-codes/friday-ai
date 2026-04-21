/**
 * Analytics 页面筛选状态 Pinia Store（Phase Plan — ）
 *
 * 职责：持有 Analytics 页面的分组维度 grouping，供 KpiCards / TokenCostChart / Selector 共享。
 *
 * 设计：
 * - 简单 setup store（参考 providerCredential.ts 模板）
 * - 不持久化到 sessionStorage（切 tab 重置为默认 none，符合 "分组是查询语境而非用户偏好" 语义）
 * - 仅一个 ref + 一个 setter，无复杂缓存
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
export type AnalyticsGrouping = 'none' | 'provider_type' | 'project'
export const useAnalyticsFiltersStore = defineStore('analyticsFilters', => {
 const grouping = ref<AnalyticsGrouping>('none')
 function setGrouping(value: AnalyticsGrouping): void {
 grouping.value = value
 }
 return { grouping, setGrouping }
})
