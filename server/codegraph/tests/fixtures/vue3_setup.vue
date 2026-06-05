<template>
  <div>
    <h2>{{ title }}</h2>
    <MyButton :label="label" @click="onSubmit" />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import MyButton from './MyButton.vue'

interface Props {
  title: string
  initialLabel?: string
}

const props = defineProps<Props>()
const emit = defineEmits<{ (e: 'submit', payload: string): void }>()

const label = ref(props.initialLabel ?? '')

function onSubmit() {
  emit('submit', label.value)
}

defineExpose({ onSubmit })
</script>
