<script setup lang="ts">
withDefaults(defineProps<{
 showClear?: boolean
}>, {
 showClear: false,
})
defineEmits<{
 clear:
}>
</script>
<template>
 <div class="flex flex-wrap items-center gap-3 rounded-2xl bg-card/70 backdrop-blur-sm border border-border/50">
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--filter] text-muted-foreground" />
 <span class="text-sm text-muted-foreground">筛选</span>
 </div>
 <slot />
 <button
 v-if="showClear"
 class="btn btn-ghost btn-sm"
 @click="$emit('clear')"
 >
 <span class="icon-[lucide--x] mr-1" />
 清除筛选
 </button>
 </div>
</template>
