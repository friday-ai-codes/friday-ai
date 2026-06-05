<script setup lang="ts">
defineProps<{
  icon: string
  iconGradient?: string
  iconColor?: string
  title: string
  description?: string
}>()
</script>

<template>
  <div class="flex flex-col md:flex-row md:items-center justify-between gap-4">
    <div class="space-y-1">
      <div class="flex items-center gap-3">
        <div
          class="p-2 rounded-xl bg-gradient-to-br flex items-center justify-center"
          :class="iconGradient || 'from-primary/20 to-primary/10'"
        >
          <span class="text-2xl" :class="[`icon-[${icon}]`, iconColor || 'text-primary']" />
        </div>
        <h1 class="text-2xl font-bold">
          {{ title }}
        </h1>
        <slot name="title-suffix" />
      </div>
      <p v-if="description" class="text-muted-foreground ml-12">
        {{ description }}
      </p>
    </div>
    <div class="flex items-center gap-3">
      <slot name="actions" />
    </div>
  </div>
</template>
