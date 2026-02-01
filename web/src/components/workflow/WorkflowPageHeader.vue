<script setup lang="ts">
import { Button } from '~/components/ui/button'
defineEmits<{
 (e: 'create'): void
}>
</script>
<template>
 <div class="flex items-center justify-between">
 <div class="space-y-1">
 <div class="flex items-center gap-3">
 <div class=" rounded-xl bg-gradient-to-br from-amber-500/20 to-orange-500/10 flex items-center justify-center">
 <span class="icon-[lucide--workflow] text-2xl text-amber-500" />
 </div>
 <h1 class="text-2xl font-bold">
 工作流
 </h1>
 </div>
 <p class="text-muted-foreground ml-12">
 管理和自动化您的开发工作流
 </p>
 </div>
 <Button class="group relative overflow-hidden" @click="$emit('create')">
 <span class="absolute inset-0 bg-gradient-to-r from-white/0 via-white/20 to-white/0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700" />
 <span class="icon-[lucide--plus] mr-2" />
 新建工作流
 </Button>
 </div>
</template>
