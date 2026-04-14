<script setup lang="ts">
import { createHighlighterCore } from 'shiki/core'
import { createJavaScriptRegexEngine } from 'shiki/engine/javascript'
import { useErrorHandler } from '~/composables/useErrorHandler'
const props = withDefaults(defineProps<{
 json: Record<string, unknown> | null
 showCopy?: boolean
}>, {
 showCopy: true,
})
const { handleError } = useErrorHandler
const { success } = useToast
// 细粒度加载：只包含需要的语言和主题，使用轻量 JS 引擎
const highlighter = createHighlighterCore({
 themes: [import('shiki/themes/vitesse-dark.mjs')],
 langs: [
 import('shiki/langs/json.mjs'),
 import('shiki/langs/javascript.mjs'),
 import('shiki/langs/typescript.mjs'),
 import('shiki/langs/python.mjs'),
 ],
 engine: createJavaScriptRegexEngine,
})
const html = ref('')
const loading = ref(true)
const copied = ref(false)
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
 const hl = await highlighter
 html.value = hl.codeToHtml(jsonString, {
 lang: 'json',
 theme: 'vitesse-dark',
 })
 }
 catch {
 // Fallback to plain text
 html.value = `<pre>${JSON.stringify(newJson, null, 2)}</pre>`
 }
 finally {
 loading.value = false
 }
 },
 { immediate: true },
)
// 复制到剪贴板
async function copyToClipboard {
 if (!props.json)
 return
 try {
 await navigator.clipboard.writeText(JSON.stringify(props.json, null, 2))
 copied.value = true
 success('已复制', 'JSON 已复制到剪贴板')
 setTimeout( => {
 copied.value = false
 }, 2000)
 }
 catch (e: unknown) {
 handleError(e, '复制')
 }
}
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
 <template v-else>
 <!-- 复制按钮栏 -->
 <div
 v-if="showCopy !== false"
 class="sticky top-0 flex justify-end px-2 py-1.5 bg-[#121212] border-b border-zinc-800 z-10"
 >
 <button
 type="button"
 class="flex items-center gap-1 px-2 py-1 text-xs rounded-md bg-zinc-700/80 hover:bg-zinc-600 text-zinc-300 hover:text-white transition-colors"
 @click="copyToClipboard"
 >
 <span v-if="copied" class="icon-[lucide--check] text-green-400" />
 <span v-else class="icon-[lucide--copy]" />
 {{ copied ? '已复制': '复制' }}
 </button>
 </div>
 <!-- eslint-disable-next-line vue/no-v-html -->
 <div class="overflow-auto rounded-b-md" v-html="html" />
 </template>
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
