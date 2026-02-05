<script setup lang="ts">
import { NodeViewWrapper, nodeViewProps } from '@tiptap/vue-3'
const props = defineProps(nodeViewProps)
function deleteNode {
 props.deleteNode
}
</script>
<template>
 <NodeViewWrapper
 as="span"
 class="inline-flex items-center gap-1 px-2 py-0.5 mx-0.5 bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-500/20 rounded-md text-sm font-medium select-none"
 contenteditable="false"
 >
 <span class="icon-[lucide--variable] text-xs opacity-70" />
 <span>{{ node.attrs.label }}</span>
 <button
 v-if="editor.isEditable"
 type="button"
 class="ml-0.5 hover:bg-blue-500/20 rounded .5 -mr-1"
 @click="deleteNode"
 >
 <span class="icon-[lucide--x] w-3 " />
 </button>
 </NodeViewWrapper>
</template>
