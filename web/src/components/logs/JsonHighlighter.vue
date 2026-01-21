<script setup lang="ts">
import { codeToHtml } from 'shiki'
const props = defineProps<{
 json: Record<string, unknown> | null
 theme?: 'github-dark' | 'github-light'
}>
const html = ref('')
const loading = ref(true)
// 动态加载并高亮 JSON
watch(
 => props.json,
 async (newJson) => {
 if (!newJson) {
 html.value = ''
 loading.value = false
 return
 }
 loading.value = true
 try {
 const jsonString = JSON.stringify(newJson, null, 2)
 html.value = await codeToHtml(jsonString, {
 lang: 'json',
 theme: props.theme ?? 'github-dark',
 })
 }
 catch (e) {
 console.error('Failed to highlight JSON:', e)
 // Fallback to plain text
 html.value = `<pre>${JSON.stringify(newJson, null, 2)}</pre>`
 }
 finally {
 loading.value = false
 }
 },
 { immediate: true },
)
</script>
<template>
 <div class="json-highlighter">
 <div v-if="loading" class="flex items-center justify-center ">
 <span class="icon-[lucide--loader-2] w-5 animate-spin text-muted-foreground" />
 <span class="ml-2 text-sm text-muted-foreground">加载中...</span>
 </div>
 <div v-else-if="!json" class=" text-sm text-muted-foreground">
 无数据
 </div>
 <!-- eslint-disable-next-line vue/no-v-html -->
 <div v-else class="overflow-auto rounded-md" v-html="html" />
 </div>
</template>
<style scoped>
.json-highlighter:deep(pre) {
 margin: 0;
 padding: 1rem;
 font-size: 0.875rem;
 line-height: 1.5;
 overflow-x: auto;
}
.json-highlighter:deep(code) {
 font-family: ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace;
}
</style>
