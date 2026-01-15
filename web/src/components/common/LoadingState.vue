<script setup lang="ts">
import { Skeleton } from '~/components/ui/skeleton'
withDefaults(defineProps<{
 variant?: 'spinner' | 'skeleton' | 'dots'
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
 <div v-if="variant === 'spinner'" class="flex flex-col items-center justify-center py-12">
 <div class="relative w-10 ">
 <span class="icon-[lucide--loader-circle] w-10 text-primary animate-spin" />
 </div>
 <p v-if="text" class="mt-4 text-muted-foreground">
 {{ text }}
 </p>
 </div>
 <!-- Skeleton 变体 -->
 <div v-else-if="variant === 'skeleton'" class="space-y-4">
 <div v-for="i in count":key="i" class="space-y-2">
 <Skeleton class=" w-3/4" />
 <Skeleton class=" w-1/2" />
 </div>
 </div>
 <!-- Dots 变体 -->
 <div v-else-if="variant === 'dots'" class="flex items-center justify-center gap-1 py-8">
 <span
 v-for="i in 3":key="i"
 class="w-2 bg-primary rounded-full animate-bounce":style="{ animationDelay: `${(i - 1) * 0.15}s` }"
 />
 <span v-if="text" class="ml-3 text-muted-foreground">{{ text }}</span>
 </div>
</template>
