<script setup lang="ts">
import type { Space } from '~/types'
import { onMounted, ref } from 'vue'
import spacesApi from '~/api/spaces'

const props = defineProps<{
  modelValue: string[]
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string[]]
}>()

const spaces = ref<Space[]>([])
const loading = ref(true)
const loadError = ref(false)

onMounted(async () => {
  try {
    spaces.value = await spacesApi.list()
  }
  catch {
    loadError.value = true
  }
  finally {
    loading.value = false
  }
})

function isSelected(id: string) {
  return props.modelValue.includes(id)
}

function toggle(id: string) {
  if (props.disabled)
    return
  const next = isSelected(id)
    ? props.modelValue.filter(v => v !== id)
    : [...props.modelValue, id]
  emit('update:modelValue', next)
}
</script>

<template>
  <div>
    <!-- 加载中 -->
    <div v-if="loading" class="flex items-center gap-2 h-10 px-1 text-sm text-muted-foreground">
      <span class="icon-[lucide--loader-circle] animate-spin" />
      加载空间列表...
    </div>

    <!-- 加载失败 -->
    <p v-else-if="loadError" class="text-sm text-destructive flex items-center gap-1">
      <span class="icon-[lucide--alert-circle]" />
      空间列表加载失败，请刷新重试
    </p>

    <!-- 无空间：引导先创建 -->
    <div
      v-else-if="spaces.length === 0"
      class="flex items-center justify-between gap-3 rounded-xl border border-dashed border-border/70 bg-muted/20 px-4 py-3"
    >
      <p class="text-sm text-muted-foreground">
        还没有空间，仓库必须关联到至少一个空间
      </p>
      <RouterLink
        to="/spaces"
        class="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline shrink-0"
      >
        前往创建
        <span class="icon-[lucide--arrow-right]" />
      </RouterLink>
    </div>

    <!-- 空间 chips -->
    <div v-else class="flex flex-wrap gap-2">
      <button
        v-for="space in spaces"
        :key="space.id"
        type="button"
        :disabled="disabled"
        class="inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm transition-colors disabled:opacity-50"
        :class="isSelected(space.id)
          ? 'border-primary/50 bg-primary/10 text-primary font-medium'
          : 'border-border/70 bg-background text-muted-foreground hover:border-primary/30 hover:text-foreground'"
        @click="toggle(space.id)"
      >
        <span :class="isSelected(space.id) ? 'icon-[lucide--check]' : 'icon-[lucide--folder]'" class="text-xs" />
        {{ space.name }}
      </button>
    </div>
  </div>
</template>
