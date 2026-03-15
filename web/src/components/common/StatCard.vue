<script setup lang="ts">
import { computed } from 'vue'
const props = withDefaults(defineProps<{
 title: string
 value: string | number
 icon: string
 iconClass?: string
 loading?: boolean
 to?: string
 trend?: {
 value: number
 direction: 'up' | 'down'
 }
}>, {
 iconClass: 'stat-icon-primary',
 loading: false,
})
const tag = computed( => props.to ? 'RouterLink': 'div')
</script>
<template>
 <component:is="tag"
 v-bind="to ? { to }: {}"
 class="card flex items-start gap-4":class="to ? 'card-interactive group': ''"
 >
 <!-- 图标 -->
 <div class="stat-icon":class="iconClass">
 <span class="text-xl":class="`icon-[${icon}]`" />
 </div>
 <!-- 内容 -->
 <div class="min-w-0 flex-1">
 <p class="text-sm text-muted-foreground mb-1">
 {{ title }}
 </p>
 <p class="text-2xl font-bold text-foreground truncate">
 <template v-if="loading">
 <span class="inline-block w-10 bg-muted animate-pulse rounded" />
 </template>
 <template v-else>
 {{ value }}
 </template>
 </p>
 <!-- 趋势 -->
 <div v-if="trend && !loading" class="flex items-center gap-1 mt-1 text-xs">
 <span
 v-if="trend.direction === 'up'"
 class="icon-[lucide--trending-up] text-emerald-500"
 />
 <span
 v-else
 class="icon-[lucide--trending-down] text-red-500"
 />
 <span:class="trend.direction === 'up' ? 'text-emerald-600': 'text-red-600'">
 {{ trend.value }}%
 </span>
 </div>
 </div>
 <!-- 箭头（仅链接模式） -->
 <span
 v-if="to"
 class="icon-[lucide--arrow-up-right] text-muted-foreground/30 group-hover:text-primary transition-colors"
 />
 </component>
</template>
