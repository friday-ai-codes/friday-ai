<script setup lang="ts">
import { nodeViewProps, NodeViewWrapper } from '@tiptap/vue-3'

const props = defineProps(nodeViewProps)

function deleteNode() {
  props.deleteNode()
}
</script>

<template>
  <NodeViewWrapper
    as="span"
    class="variable-chip-view inline-flex items-center gap-1.5 pl-2 pr-1 py-0.5 mx-0.5 my-0.5 align-middle rounded-md select-none ring-1 transition-colors duration-150"
    :class="[selected
      ? 'bg-teal-600 text-white ring-teal-600'
      : 'bg-teal-50 text-teal-800 ring-teal-300 dark:bg-teal-500/15 dark:text-teal-200 dark:ring-teal-500/40']"
    contenteditable="false"
  >
    <span
      class="icon-[lucide--braces] text-[11px] shrink-0"
      :class="selected ? 'text-white/90' : 'text-teal-500'"
    />
    <span class="flex flex-col leading-tight min-w-0">
      <code class="font-mono text-[11px] font-semibold truncate">{{ node.attrs.outputName }}</code>
      <span
        class="text-[9px] truncate"
        :class="selected ? 'text-white/85' : 'text-teal-700/70 dark:text-teal-300/70'"
      >{{ node.attrs.label }}</span>
    </span>
    <button
      v-if="editor.isEditable"
      type="button"
      class="self-center shrink-0 rounded p-0.5 transition-colors"
      :class="selected ? 'hover:bg-white/25' : 'hover:bg-teal-600/15 text-teal-600'"
      @click="deleteNode"
    >
      <span class="icon-[lucide--x] w-2.5 h-2.5" />
    </button>
  </NodeViewWrapper>
</template>
