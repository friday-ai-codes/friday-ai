<script setup lang="ts">
import { ref, watch } from 'vue'
import { Button } from '~/components/ui/button'
import MarkdownEditor from '~/components/ui/markdown-editor/MarkdownEditor.vue'
const props = defineProps<{
 markdown: string
 validationError?: string | null
}>
const emit = defineEmits<{
 'update:markdown': [value: string]
 'save':
}>
const localContent = ref(props.markdown)
watch( => props.markdown, (newVal) => {
 localContent.value = newVal
})
function handleContentChange(content: string) {
 localContent.value = content
 emit('update:markdown', content)
}
function handleSave {
 emit('save')
}
</script>
<template>
 <div class="technical-plan-editor">
 <!-- Header with save button -->
 <div class="flex items-center justify-between border-b border-border/50">
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--file-text] text-muted-foreground" />
 <span class="text-sm font-medium">Markdown 编辑</span>
 </div>
 <div class="flex items-center gap-3">
 <span v-if="validationError" class="text-xs text-destructive flex items-center gap-1">
 <span class="icon-[lucide--alert-triangle]" />
 校验失败
 </span>
 <Button class="" @click="handleSave">
 <span class="icon-[lucide--save] mr-2" />
 保存
 </Button>
 </div>
 </div>
 <!-- Editor area -->
 <div class="">
 <MarkdownEditor:model-value="localContent"
 placeholder="在此编辑技术方案..."
 min-height="400px"
 max-height="600px"
 @update:model-value="handleContentChange"
 />
 </div>
 <!-- Validation error banner -->
 <div v-if="validationError" class=" bg-destructive/10 border-t border-destructive/20">
 <div class="flex items-start gap-3">
 <div class=" rounded-lg bg-destructive/20 flex-shrink-0">
 <span class="icon-[lucide--alert-circle] text-lg text-destructive" />
 </div>
 <div class="flex-1">
 <p class="text-sm font-medium text-destructive">
 Schema 校验失败
 </p>
 <p class="text-sm text-muted-foreground mt-1">
 {{ validationError }}
 </p>
 <p class="text-xs text-muted-foreground mt-2 flex items-center gap-1">
 <span class="icon-[lucide--info]" />
 您仍可强制保存，但可能影响后续执行。
 </p>
 </div>
 </div>
 </div>
 </div>
</template>
