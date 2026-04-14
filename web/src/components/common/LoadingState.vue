<script setup lang="ts">
withDefaults(defineProps<{
 variant?: 'spinner' | 'skeleton' | 'dots' | 'card'
 text?: string
 count?: number
}>, {
 variant: 'spinner',
 text: '加载中...',
 count: 3,
})
</script>
<template>
 <!-- Spinner 变体 -->
 <div v-if="variant === 'spinner'" class="flex flex-col items-center justify-center py-16">
 <div class="relative">
 <!-- 外圈光晕 -->
 <div class="absolute inset-0 rounded-full blur-xl opacity-30 animate-pulse" />
 <!-- 旋转环 -->
 <div class="relative w-12 rounded-full border-2 border-muted">
 <div class="absolute inset-0 rounded-full border-2 border-transparent border-t-primary animate-spin" />
 </div>
 </div>
 <p v-if="text" class="mt-6 text-muted-foreground font-medium">
 {{ text }}
 </p>
 </div>
 <!-- Skeleton 变体 -->
 <div v-else-if="variant === 'skeleton'" class="space-y-4">
 <div v-for="i in count":key="i" class="space-y-3 rounded-xl bg-card/50 border border-border/30">
 <div class="flex items-center gap-3">
 <div class="w-10 rounded-lg bg-primary/10 animate-pulse" />
 <div class="flex-1 space-y-2">
 <div class=" w-3/4 animate-pulse rounded-md" />
 <div class=" w-1/2 animate-pulse rounded-md" />
 </div>
 </div>
 </div>
 </div>
 <!-- Card 变体 - 用于卡片列表 -->
 <div v-else-if="variant === 'card'" class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
 <div v-for="i in count":key="i" class=" rounded-2xl bg-card/50 border border-border/30">
 <div class="flex items-start justify-between mb-4">
 <div class="w-12 rounded-xl bg-primary/10 animate-pulse" />
 <div class="w-20 rounded-full animate-pulse" />
 </div>
 <div class="space-y-2">
 <div class=" w-2/3 animate-pulse rounded-md" />
 <div class=" w-full animate-pulse rounded-md" />
 <div class=" w-3/4 animate-pulse rounded-md" />
 </div>
 <div class="flex gap-2 mt-4">
 <div class="flex-1 rounded-lg animate-pulse" />
 <div class="w-9 rounded-lg animate-pulse" />
 </div>
 </div>
 </div>
 <!-- Dots 变体 -->
 <div v-else-if="variant === 'dots'" class="flex items-center justify-center gap-2 py-12">
 <span
 v-for="i in 3":key="i"
 class="w-2.5 .5 bg-primary/10 rounded-full animate-bounce":style="{ animationDelay: `${(i - 1) * 0.15}s` }"
 />
 <span v-if="text" class="ml-4 text-muted-foreground font-medium">{{ text }}</span>
 </div>
</template>
