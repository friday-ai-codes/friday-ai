<script setup lang="ts">
import { nodeViewProps, NodeViewWrapper } from '@tiptap/vue-3'
import { computed } from 'vue'
const props = defineProps(nodeViewProps)
function deleteNode {
 props.deleteNode
}
const argsPreview = computed( => {
 const args = props.node.attrs.args as string
 if (!args || args.length === 0)
 return ''
 return `(${args.join(', ')})`
})
</script>
<template>
 <NodeViewWrapper
 as="span"
 class="inline-flex items-center gap-1 pl-1.5 pr-1 py-0.5 rounded-md select-none transition-colors duration-150":class="[selected ? 'bg-blue-500 text-white border border-blue-500': 'bg-blue-50 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-800']"
 contenteditable="false"
 >
 <span class="icon-[lucide--function-square] text-[10px]":class="selected ? 'opacity-90': 'opacity-70'" />
 <span class="flex flex-col leading-tight">
 <code class="font-mono text-[11px] font-medium">{{ node.attrs.name }}</code>
 <span class="text-[9px]":class="selected ? 'opacity-80': 'opacity-60'">{{ argsPreview }}</span>
 </span>
 <button
 v-if="editor.isEditable"
 type="button"
 class="self-start rounded .5":class="selected ? 'hover:bg-white/20': 'hover:bg-blue-500/20'"
 @click="deleteNode"
 >
 <span class="icon-[lucide--x] w-2.5 .5" />
 </button>
 </NodeViewWrapper>
</template>
