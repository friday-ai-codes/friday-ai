<script setup lang="ts">
import SpaceFilter from './SpaceFilter.vue'

defineProps<{
  mode: 'overview' | 'detail'
  repoLabel?: string
  spaceId: string | null
}>()

const emit = defineEmits<{
  (e: 'update:spaceId', value: string | null): void
  (e: 'back'): void
}>()

function onSpaceChange(value: string | null) {
  emit('update:spaceId', value)
}
</script>

<template>
  <div class="glass-card rounded-lg px-3 py-1.5 flex items-center gap-2 text-sm">
    <template v-if="mode === 'overview'">
      <span class="icon-[lucide--orbit] text-white/60" />
      <span class="text-white/80">Galaxy 总览</span>
      <span class="text-white/30 mx-1">·</span>
      <SpaceFilter :model-value="spaceId" @update:model-value="onSpaceChange" />
    </template>
    <template v-else>
      <button
        type="button"
        class="flex items-center gap-1 text-white/70 hover:text-white transition-colors"
        @click="emit('back')"
      >
        <span class="icon-[lucide--orbit]" />
        <span>Galaxy 总览</span>
      </button>
      <span class="text-white/30 mx-1">/</span>
      <span class="text-white truncate max-w-[260px]">
        {{ repoLabel || '仓库详情' }}
      </span>
    </template>
  </div>
</template>
