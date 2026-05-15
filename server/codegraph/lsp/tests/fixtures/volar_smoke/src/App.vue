<template>
 <div class="app">{{ greeting }}</div>
</template>
<script lang="ts" setup>
import { computed } from 'vue'
import { sayHello } from '@/utils'
const greeting = computed( => sayHello('volar'))
</script>
