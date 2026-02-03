<script setup lang="ts">
import { computed, ref } from 'vue'
import { Button } from '~/components/ui/button'
const props = defineProps<{
 plan: Record<string, unknown> | null
}>
const formattedJson = computed( => {
 if (!props.plan)
 return ''
 return JSON.stringify(props.plan, null, 2)
})
const copied = ref(false)
async function copyToClipboard {
 if (!formattedJson.value)
 return
 try {
 await navigator.clipboard.writeText(formattedJson.value)
 copied.value = true
 setTimeout( => {
 copied.value = false
 }, 2000)
 }
 catch {
 // Fallback for older browsers
 const textarea = document.createElement('textarea')
 textarea.value = formattedJson.value
 document.body.appendChild(textarea)
 textarea.select
 document.execCommand('copy')
 document.body.removeChild(textarea)
 copied.value = true
 setTimeout( => {
 copied.value = false
 }, 2000)
 }
}
</script>
<template>
 <div class="technical-plan-viewer">
 <!-- Empty state -->
 <div v-if="!plan" class="flex flex-col items-center justify-center py-16 text-muted-foreground">
 <div class=" rounded-2xl bg-gradient-to-br from-muted/50 to-muted/30 mb-4">
 <span class="icon-[lucide--file-code] text-4xl" />
 </div>
 <p class="text-base font-medium">
 暂无技术方案
 </p>
 <p class="text-sm mt-1">
 技术方案生成后将在此显示
 </p>
 </div>
 <!-- JSON view -->
 <div v-else>
 <!-- Header with copy button -->
 <div class="flex items-center justify-between border-b border-border/50">
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--braces] text-muted-foreground" />
 <span class="text-sm font-medium">JSON 结构</span>
 <span class="text-xs text-muted-foreground">(只读)</span>
 </div>
 <Button variant="ghost" size="sm" class="" @click="copyToClipboard">
 <span v-if="copied" class="icon-[lucide--check] mr-2 text-emerald-500" />
 <span v-else class="icon-[lucide--copy] mr-2" />
 {{ copied ? '已复制': '复制' }}
 </Button>
 </div>
 <!-- JSON display -->
 <div class="">
 <pre class=" overflow-auto max-h-[600px] text-sm font-mono bg-muted/30 rounded-xl border border-border/30"><code class="text-foreground/90">{{ formattedJson }}</code></pre>
 </div>
 </div>
 </div>
</template>
