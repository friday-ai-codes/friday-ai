<template>
 <div class="user-card">
 <h2>{{ title }}</h2>
 <p>计数：{{ count }}</p>
 <button @click="handleClick">点击</button>
 <ChildComp:value="title" @save="onSave" />
 </div>
</template>
<script>
import ChildComp from './ChildComp.vue'
export default {
 name: 'UserCardOptions',
 components: { ChildComp },
 props: {
 initialTitle: { type: String, default: '默认标题' },
 },
 data {
 return {
 title: this.initialTitle,
 count: 0,
 }
 },
 methods: {
 handleClick {
 this.count++
 },
 onSave(payload) {
 this.$emit('save', payload)
 },
 },
 mounted {
 console.log('mounted')
 },
}
</script>
<style scoped>
.user-card { padding: 10px; }
</style>
