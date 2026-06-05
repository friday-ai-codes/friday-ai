<script setup lang="ts">
withDefaults(defineProps<{
  icon?: string
  title?: string
  description?: string
}>(), {
  icon: 'lucide--inbox',
  title: '暂无数据',
  description: '',
})
</script>

<template>
  <div class="flex flex-col items-center justify-center py-8 text-center">
    <!-- 图标容器（紧凑：与文字间距收紧，修复 block mb-2 散布写法） -->
    <div class="inline-flex p-2.5 rounded-xl bg-primary/10 mb-2.5">
      <span class="text-2xl text-muted-foreground/50" :class="`icon-[${icon}]`" />
    </div>

    <p class="text-sm font-medium text-foreground">
      {{ title }}
    </p>
    <p v-if="description" class="mt-1 text-xs text-muted-foreground">
      {{ description }}
    </p>

    <!-- CTA：调用方传入按钮（组件本身不强依赖 Button） -->
    <div v-if="$slots.default" class="mt-3">
      <slot />
    </div>
  </div>
</template>
