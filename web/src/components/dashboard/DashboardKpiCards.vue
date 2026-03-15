<script setup lang="ts">
import StatCard from '~/components/common/StatCard.vue'
export interface KpiStat {
 title: string
 value: number
 icon: string
 statIconClass: string
 link: string
}
defineProps<{
 stats: KpiStat
 loading: boolean
}>
</script>
<template>
 <section class="grid gap-5 grid-cols-2 lg:grid-cols-4">
 <StatCard
 v-for="stat in stats":key="stat.title":title="stat.title":value="stat.value":icon="stat.icon":icon-class="stat.statIconClass":loading="loading":to="stat.link"
 />
 </section>
</template>
