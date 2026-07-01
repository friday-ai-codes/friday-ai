<script setup lang="ts">
import { TransitionPresets, useTransition } from '@vueuse/core'
import { computed, reactive, watch } from 'vue'

export interface KpiStat {
  title: string
  value: number
  /** 完整 iconify 类名，如 'icon-[lucide--folder-git-2]'（必须是完整字面量，Tailwind 才能扫描到） */
  icon: string
  link: string
  /** 今日新增数量 */
  todayNew: number
}

const props = defineProps<{
  stats: KpiStat[]
  loading: boolean
}>()

// 为每个 stat 创建动效源（初始值为 0）；stats 数量在页面生命周期内固定
const indices = props.stats.map((_, i) => i)
const sources = reactive<Record<number, number>>(
  Object.fromEntries(indices.map(i => [i, 0])),
)

// 数字平滑滚动动效
const animated = Object.fromEntries(
  indices.map(i => [i, useTransition(
    computed(() => sources[i]),
    { duration: 800, transition: TransitionPresets.easeOutCubic },
  )]),
)

watch(() => props.loading, (newLoading) => {
  if (!newLoading) {
    props.stats.forEach((stat, i) => {
      sources[i] = stat.value
    })
  }
})

watch(() => props.stats.map(s => s.value), (newValues) => {
  if (!props.loading) {
    newValues.forEach((v, i) => {
      sources[i] = v
    })
  }
}, { deep: true })

// 入场动效（.kpi-cell 错拍浮现）由首页主时间线（index.vue）统一编排，
// 此处不再单独起动画，避免多条独立时间线导致出现顺序错乱。
</script>

<template>
  <!-- 单卡分格 KPI strip：格子间用 1px 分隔线，避免 6 张独立小卡片的拥挤感 -->
  <section class="card overflow-hidden" aria-label="数据总览">
    <div class="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-px bg-border/60">
      <RouterLink
        v-for="(stat, index) in stats"
        :key="stat.title"
        :to="stat.link"
        class="kpi-cell group bg-card px-5 py-4 flex flex-col gap-2.5 cursor-pointer transition-colors duration-200 hover:bg-primary/4 focus-visible:outline-2 focus-visible:outline-primary/50 focus-visible:-outline-offset-2"
      >
        <!-- 标题行：图标 + 名称，整行不换行 -->
        <div class="flex items-center gap-1.5 text-muted-foreground group-hover:text-primary transition-colors duration-200">
          <span class="text-base shrink-0" :class="stat.icon" aria-hidden="true" />
          <span class="text-xs font-medium whitespace-nowrap">{{ stat.title }}</span>
          <span
            class="icon-[lucide--arrow-up-right] ml-auto text-sm opacity-0 group-hover:opacity-60 transition-opacity duration-200"
            aria-hidden="true"
          />
        </div>

        <!-- 数值 + 今日新增 -->
        <template v-if="loading">
          <span class="inline-block w-14 h-8 bg-muted animate-pulse rounded" />
          <span class="inline-block w-16 h-3.5 bg-muted animate-pulse rounded" />
        </template>
        <template v-else>
          <p class="text-3xl font-bold text-foreground tabular-nums leading-none">
            {{ Math.round(animated[index]?.value ?? 0) }}
          </p>
          <!-- 仅在有新增时展示「今日 +N」；无新增则不展示（不占位提示）。 -->
          <p
            v-if="stat.todayNew > 0"
            class="text-xs tabular-nums leading-none inline-flex items-center gap-1 text-emerald-600 font-medium"
          >
            <span class="icon-[lucide--trending-up]" aria-hidden="true" />
            今日新增 {{ stat.todayNew }}
          </p>
        </template>
      </RouterLink>
    </div>
  </section>
</template>
