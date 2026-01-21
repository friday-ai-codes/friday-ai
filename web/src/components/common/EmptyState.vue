<script setup lang="ts">
import { Button } from '~/components/ui/button'
withDefaults(defineProps<{
 icon?: string
 title?: string
 description?: string
 actionLabel?: string
 gradient?: string
}>, {
 icon: 'lucide--inbox',
 title: '暂无数据',
 description: '这里还没有任何内容',
 gradient: 'from-primary/20 to-secondary/40',
})
const emit = defineEmits<{
 action:
}>
</script>
<template>
 <div class="relative flex flex-col items-center justify-center py-16 text-center">
 <!-- 背景装饰 -->
 <div class="absolute inset-0 -z-10 overflow-hidden">
 <div class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-64 bg-gradient-to-br rounded-full blur-3xl opacity-30":class="gradient" />
 </div>
 <!-- 图标容器 -->
 <div class="relative mb-6">
 <div class="absolute inset-0 bg-gradient-to-br from-muted to-muted/30 rounded-2xl blur-xl" />
 <div class="relative inline-flex items-center justify-center w-20 rounded-2xl bg-gradient-to-br from-muted/80 to-muted/40 border border-border/50 backdrop-blur-sm">
 <span class="text-4xl text-muted-foreground/60":class="[`icon-[${icon}]`]" />
 </div>
 </div>
 <!-- 文字内容 -->
 <h3 class="text-lg font-semibold text-foreground mb-2">
 {{ title }}
 </h3>
 <p class="text-muted-foreground mb-8 max-w-sm leading-relaxed">
 {{ description }}
 </p>
 <!-- 操作按钮 -->
 <Button v-if="actionLabel" class="group relative overflow-hidden" @click="emit('action')">
 <span class="absolute inset-0 bg-gradient-to-r from-white/0 via-white/20 to-white/0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700" />
 <span class="icon-[lucide--plus] mr-2" />
 {{ actionLabel }}
 </Button>
 </div>
</template>
