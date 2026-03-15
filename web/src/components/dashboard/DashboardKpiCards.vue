<script setup lang="ts">
import { TransitionPresets, useTransition } from '@vueuse/core'
import { computed, reactive, watch } from 'vue'
import StatCard from '~/components/common/StatCard.vue'
export interface KpiStat {
 title: string
 value: number
 icon: string
 statIconClass: string
 link: string
}
const props = defineProps<{
 stats: KpiStat
 loading: boolean
}>
// 为每个 stat 创建动效源（初始值为 0）
const sources = reactive<Record<number, number>>({
 0: 0,
 1: 0,
 2: 0,
 3: 0,
})
// 用 useTransition 包裹，实现数字平滑滚动
const animated = Object.fromEntries(
 [0, 1, 2, 3].map(i => [i, useTransition(
 computed( => sources[i]),
 { duration: 800, transition: TransitionPresets.easeOutCubic },
 )]),
)
// 监听 loading 变化，loading 结束后赋值触发动效
watch( => props.loading, (newLoading) => {
 if (!newLoading) {
 props.stats.forEach((stat, i) => {
 sources[i] = stat.value
 })
 }
})
// 监听 stats 变化（数据更新时重新动画）
watch( => props.stats.map(s => s.value), (newValues) => {
 if (!props.loading) {
 newValues.forEach((v, i) => {
 sources[i] = v
 })
 }
}, { deep: true })
</script>
<template>
 <section class="grid gap-5 grid-cols-2 lg:grid-cols-4">
 <StatCard
 v-for="(stat, index) in stats":key="stat.title":title="stat.title":value="loading ? 0: Math.round(animated[index]?.value ?? 0)":icon="stat.icon":icon-class="stat.statIconClass":loading="loading":to="stat.link"
 />
 </section>
</template>
