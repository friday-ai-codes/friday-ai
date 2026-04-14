<script setup lang="ts">
import { nodeViewProps, NodeViewWrapper } from '@tiptap/vue-3'
const props = defineProps(nodeViewProps)
function deleteNode {
 props.deleteNode
}
</script>
<template>
 <NodeViewWrapper
 as="span"
 class="inline-flex items-center gap-1 pl-1.5 pr-1 py-0.5 rounded-md select-none transition-colors duration-150":class="[selected ? 'bg-primary text-white border border-primary': 'bg-primary/10 text-primary dark:text-primary border border-primary/20']"
 contenteditable="false"
 >
 <span class="icon-[lucide--variable] text-[10px]":class="selected ? 'opacity-90': 'opacity-70'" />
 <span class="flex flex-col leading-tight">
 <code class="font-mono text-[11px] font-medium">{{ node.attrs.outputName }}</code>
 <span class="text-[9px]":class="selected ? 'opacity-80': 'opacity-60'">{{ node.attrs.label }}</span>
 </span>
 <button
 v-if="editor.isEditable"
 type="button"
 class="self-start rounded .5":class="selected ? 'hover:bg-white/20': 'hover:bg-primary/20'"
 @click="deleteNode"
 >
 <span class="icon-[lucide--x] w-2.5 .5" />
 </button>
 </NodeViewWrapper>
</template>
