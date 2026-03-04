<script setup lang="ts">
/**
 * MarkdownRenderer — 通用 Markdown 渲染组件
 *
 * 接收 Markdown 字符串，通过 markdown-it + Shiki 渲染为 HTML。
 * 延迟初始化渲染器实例，首次使用时加载。
 */
import { ref, watch } from 'vue'
import { getMarkdownRenderer } from '~/composables/useMarkdownRenderer'
import { Skeleton } from '~/components/ui/skeleton'
const props = defineProps<{
 content: string
}>
const html = ref('')
const loading = ref(true)
async function renderMarkdown(content: string) {
 if (!content) {
 html.value = ''
 loading.value = false
 return
 }
 loading.value = true
 try {
 const md = await getMarkdownRenderer
 html.value = md.render(content)
 }
 catch {
 // 渲染失败时回退到纯文本
 html.value = `<pre>${content}</pre>`
 }
 finally {
 loading.value = false
 }
}
watch( => props.content, renderMarkdown, { immediate: true })
</script>
<template>
 <div>
 <Skeleton v-if="loading" class=" w-full rounded-lg" />
 <!-- eslint-disable-next-line vue/no-v-html -->
 <div v-else class="markdown-body text-sm text-foreground" v-html="html" />
 </div>
</template>
<style scoped>
.markdown-body:deep(h1) {
 @apply text-xl font-bold mt-4 mb-2;
}
.markdown-body:deep(h2) {
 @apply text-lg font-semibold mt-3 mb-2;
}
.markdown-body:deep(h3) {
 @apply text-base font-semibold mt-2 mb-1;
}
.markdown-body:deep(p) {
 @apply my-2 leading-relaxed;
}
.markdown-body:deep(ul) {
 @apply list-disc ml-4 my-2;
}
.markdown-body:deep(ol) {
 @apply list-decimal ml-4 my-2;
}
.markdown-body:deep(li) {
 @apply my-0.5;
}
.markdown-body:deep(code:not(pre code)) {
 @apply bg-muted px-1 py-0.5 rounded text-sm font-mono;
}
.markdown-body:deep(pre) {
 @apply my-3 rounded-lg overflow-x-auto;
}
.markdown-body:deep(table) {
 @apply w-full border-collapse my-3;
}
.markdown-body:deep(th) {
 @apply border border-border px-3 py-1.5 bg-muted/50 text-left font-medium;
}
.markdown-body:deep(td) {
 @apply border border-border px-3 py-1.5;
}
.markdown-body:deep(a) {
 @apply text-primary underline underline-offset-2;
}
.markdown-body:deep(blockquote) {
 @apply border- border-muted pl-4 my-2 text-muted-foreground;
}
.markdown-body:deep(strong) {
 @apply font-semibold;
}
.markdown-body:deep(em) {
 @apply italic;
}
</style>
