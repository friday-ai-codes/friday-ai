<script setup lang="ts">
import type { WorkflowEdge, WorkflowNode } from '~/types/workflow/store'
import Document from '@tiptap/extension-document'
import Gapcursor from '@tiptap/extension-gapcursor'
import History from '@tiptap/extension-history'
import Paragraph from '@tiptap/extension-paragraph'
import Placeholder from '@tiptap/extension-placeholder'
import Text from '@tiptap/extension-text'
import { EditorContent, useEditor } from '@tiptap/vue-3'
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useDesignTimeVariables } from '~/composables/useDesignTimeVariables'
import { createVariableSuggestion, VariableNode } from './extensions'
interface Props {
 modelValue: string
 workflowNodes?: WorkflowNode
 workflowEdges?: WorkflowEdge
 currentNodeId?: string
 placeholder?: string
 disabled?: boolean
}
const props = withDefaults(defineProps<Props>, {
 workflowNodes: =>,
 workflowEdges: =>,
 currentNodeId: '',
 placeholder: '',
 disabled: false,
})
const emit = defineEmits<{
 'update:modelValue': [value: string]
}>
// Design-time variables from upstream nodes
const workflowNodesRef = computed( => props.workflowNodes)
const workflowEdgesRef = computed( => props.workflowEdges)
const currentNodeIdRef = computed( => props.currentNodeId)
// Track if we're updating from external source to prevent loops
const isUpdatingFromExternal = ref(false)
const { designTimeVariables } = useDesignTimeVariables(
 workflowNodesRef,
 workflowEdgesRef,
 currentNodeIdRef,
)
const editor = useEditor({
 extensions: [
 Document,
 Paragraph,
 Text,
 History,
 Gapcursor,
 Placeholder.configure({
 placeholder: props.placeholder,
 }),
 VariableNode,
 createVariableSuggestion({
 items: => designTimeVariables.value,
 }),
 ],
 content: parseContent(props.modelValue),
 editable: !props.disabled,
 onUpdate: => {
 if (!isUpdatingFromExternal.value) {
 const serialized = serializeContent
 emit('update:modelValue', serialized)
 }
 },
 editorProps: {
 // Prevent Enter from creating new paragraphs (single-line behavior)
 handleKeyDown: (view, event) => {
 if (event.key === 'Enter' && !event.shiftKey) {
 // Prevent default behavior
 return true
 }
 return false
 },
 // Custom copy handler to serialize variable nodes as {{path}}
 clipboardTextSerializer: (slice) => {
 let text = ''
 slice.content.forEach((node) => {
 if (node.type.name === 'paragraph') {
 node.content.forEach((child) => {
 if (child.type.name === 'text') {
 text += child.text || ''
 }
 else if (child.type.name === 'variable') {
 text += `{{${child.attrs.path || ''}}}`
 }
 })
 }
 else if (node.type.name === 'variable') {
 text += `{{${node.attrs.path || ''}}}`
 }
 else if (node.type.name === 'text') {
 text += node.text || ''
 }
 })
 return text
 },
 attributes: {
 class: 'outline-none min-h-[2.25rem] flex items-center',
 },
 },
})
/**
 * Serialize editor content to string with {{path}} syntax
 */
function serializeContent: string {
 if (!editor.value)
 return ''
 const doc = editor.value.getJSON
 let result = ''
 // Traverse document nodes
 for (const node of doc.content ?? ) {
 if (node.type === 'paragraph') {
 for (const child of node.content ?? ) {
 if (child.type === 'text') {
 result += (child as { text?: string }).text ?? ''
 }
 else if (child.type === 'variable') {
 result += `{{${(child as { attrs?: { path?: string } }).attrs?.path ?? ''}}}`
 }
 }
 }
 }
 return result
}
/**
 * Parse string with {{path}} syntax to editor content
 */
function parseContent(value: string): object {
 const content: object =
 const regex = /\{\{([^}]+)\}\}/g
 let lastIndex = 0
 for (const match of value.matchAll(regex)) {
 // Add text before the match
 if (match.index > lastIndex) {
 content.push({
 type: 'text',
 text: value.slice(lastIndex, match.index),
 })
 }
 // Find variable info from design-time variables
 const path = match[1]
 const variable = designTimeVariables.value.find(v => v.path === path)
 content.push({
 type: 'variable',
 attrs: {
 path,
 label: variable?.label ?? path,
 nodeId: variable?.nodeId ?? '',
 outputName: variable?.key ?? '',
 },
 })
 lastIndex = match.index + match[0].length
 }
 // Add remaining text
 if (lastIndex < value.length) {
 content.push({
 type: 'text',
 text: value.slice(lastIndex),
 })
 }
 return {
 type: 'doc',
 content: [
 {
 type: 'paragraph',
 content: content.length > 0 ? content: undefined,
 },
 ],
 }
}
// Sync external value changes to editor
watch( => props.modelValue, (newValue) => {
 if (!editor.value)
 return
 const currentValue = serializeContent
 if (newValue !== currentValue) {
 isUpdatingFromExternal.value = true
 editor.value.commands.setContent(parseContent(newValue))
 // Use nextTick to ensure the flag is reset after the update cycle
 nextTick( => {
 isUpdatingFromExternal.value = false
 })
 }
})
// Update editable state
watch( => props.disabled, (disabled) => {
 editor.value?.setEditable(!disabled)
})
// Update placeholder
watch( => props.placeholder, (placeholder) => {
 editor.value?.extensionManager.extensions
 .find(ext => ext.name === 'placeholder')
 ?.configure({ placeholder })
})
onBeforeUnmount( => {
 editor.value?.destroy
})
</script>
<template>
 <div
 class="rounded-lg border border-border/50 bg-background/50 px-3 py-2 text-sm
 focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2
 focus-within:ring-offset-background transition-shadow":class="{ 'opacity-50 cursor-not-allowed': disabled }"
 >
 <EditorContent:editor="editor" />
 </div>
</template>
<style>
/* Placeholder styling */
.tiptap p.is-editor-empty:first-child:before {
 content: attr(data-placeholder);
 float: left;
 color: var(--muted-foreground);
 opacity: 0.5;
 pointer-events: none;
 height: 0;
}
/* Variable chip spacing - ensure chips don't touch each other */
.tiptap .node-variable + .node-variable {
 margin-left: 0.5rem;
}
</style>
