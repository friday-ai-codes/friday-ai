<script setup lang="ts">
import type { SliderRootProps } from 'reka-ui'
import type { HTMLAttributes } from 'vue'
import { computed } from 'vue'
import Slider from './Slider.vue'

/**
 * 单值 Slider 包装组件
 * 将 reka-ui 的数组类型 modelValue 转换为单个数值
 */

interface Props extends Omit<SliderRootProps, 'modelValue'> {
  class?: HTMLAttributes['class']
  modelValue?: number
}

const props = withDefaults(defineProps<Props>(), {
  modelValue: 0,
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: number): void
}>()

const arrayValue = computed({
  get: () => [props.modelValue],
  set: (v: number[]) => emit('update:modelValue', v[0]),
})
</script>

<template>
  <Slider v-model="arrayValue" :class="props.class" v-bind="$attrs" />
</template>
