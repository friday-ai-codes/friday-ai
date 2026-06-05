<template>
  <div class="wrapper">
    <ChildComp :title="title" />
    <user-card @save="onSave">{{ title }}</user-card>
    <span>{{ title }}</span>
  </div>
</template>

<script setup lang="ts">
import ChildComp from './ChildComp.vue'
import UserCard from './UserCard.vue'

const title = 'hello'

function onSave() {
  return title
}
</script>

<style scoped>
.wrapper { display: flex; }
</style>
