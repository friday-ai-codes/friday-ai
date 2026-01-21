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
 <div class="absolute inset-0 bg-gradient-to-r from-primary to-primary/50 rounded-full blur-xl opacity-30 animate-pulse" />
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
 <div class="w-10 rounded-lg bg-gradient-to-br from-muted to-muted/50 animate-pulse" />
 <div class="flex-1 space-y-2">
 <div class=" w-3/4 bg-gradient-to-r from-muted to-muted/50 animate-pulse rounded-md" />
 <div class=" w-1/2 bg-gradient-to-r from-muted/80 to-muted/30 animate-pulse rounded-md" />
 </div>
 </div>
 </div>
 </div>
 <!-- Card 变体 - 用于卡片列表 -->
 <div v-else-if="variant === 'card'" class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
 <div v-for="i in count":key="i" class=" rounded-2xl bg-card/50 border border-border/30">
 <div class="flex items-start justify-between mb-4">
 <div class="w-12 rounded-xl bg-gradient-to-br from-muted to-muted/50 animate-pulse" />
 <div class="w-20 rounded-full bg-gradient-to-r from-muted to-muted/50 animate-pulse" />
 </div>
 <div class="space-y-2">
 <div class=" w-2/3 bg-gradient-to-r from-muted to-muted/50 animate-pulse rounded-md" />
 <div class=" w-full bg-gradient-to-r from-muted/80 to-muted/30 animate-pulse rounded-md" />
 <div class=" w-3/4 bg-gradient-to-r from-muted/60 to-muted/20 animate-pulse rounded-md" />
 </div>
 <div class="flex gap-2 mt-4">
 <div class="flex-1 rounded-lg bg-gradient-to-r from-muted to-muted/50 animate-pulse" />
 <div class="w-9 rounded-lg bg-gradient-to-r from-muted to-muted/50 animate-pulse" />
 </div>
 </div>
 </div>
 <!-- Dots 变体 -->
 <div v-else-if="variant === 'dots'" class="flex items-center justify-center gap-2 py-12">
 <span
 v-for="i in 3":key="i"
 class="w-2.5 .5 bg-gradient-to-br from-primary to-primary/60 rounded-full animate-bounce":style="{ animationDelay: `${(i - 1) * 0.15}s` }"
 />
 <span v-if="text" class="ml-4 text-muted-foreground font-medium">{{ text }}</span>
 </div>
</template>
