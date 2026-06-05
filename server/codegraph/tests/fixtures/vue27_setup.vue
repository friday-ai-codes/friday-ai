<template>
  <div>
    <p>{{ message }}</p>
    <button @click="onClick">点我</button>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { fetchData } from './api'

interface Props {
  initialMessage: string
}

const props = defineProps<Props>()
const message = ref(props.initialMessage)
const length = computed(() => message.value.length)

function onClick() {
  fetchData().then((data) => {
    message.value = data
  })
}

const reset = () => {
  message.value = ''
}
</script>

<style scoped>
button { color: red; }
</style>
