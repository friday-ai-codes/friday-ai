<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { useVModel } from '@vueuse/core'
import { cn } from '~/lib/utils'
const props = defineProps<{
 class?: HTMLAttributes['class']
 defaultValue?: string | number
 modelValue?: string | number
}>
const emits = defineEmits<{
 (e: 'update:modelValue', payload: string | number): void
}>
const modelValue = useVModel(props, 'modelValue', emits, {
 passive: true,
 defaultValue: props.defaultValue,
})
</script>
<template>
 <textarea
 v-model="modelValue":class="cn(
 'flex min- w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50',
 props.class,
 )"
 />
</template>
