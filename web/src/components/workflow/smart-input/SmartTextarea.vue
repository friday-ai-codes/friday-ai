<script setup lang="ts">
import { ref, watch, onBeforeUnmount, computed } from 'vue'
import { useEditor, EditorContent } from '@tiptap/vue-3'
import Document from '@tiptap/extension-document'
import Paragraph from '@tiptap/extension-paragraph'
import Text from '@tiptap/extension-text'
import History from '@tiptap/extension-history'
import Placeholder from '@tiptap/extension-placeholder'
import type { Node as VueFlowNode, Edge } from '@vue-flow/core'
import { useDesignTimeVariables } from '~/composables/useDesignTimeVariables'
import { VariableNode, createVariableSuggestion } from './extensions'
interface Props {
 modelValue: string
 workflowNodes: VueFlowNode
 workflowEdges: Edge
 currentNodeId: string
 placeholder?: string
 disabled?: boolean
 minRows?: number
}
const props = withDefaults(defineProps<Props>, {
 placeholder: '',
 disabled: false,
 minRows: 4,
})
const emit = defineEmits<{
 'update:modelValue': [value: string]
}>
// Design-time variables from upstream nodes
const workflowNodesRef = computed( => props.workflowNodes)
const workflowEdgesRef = computed( => props.workflowEdges)
const currentNodeIdRef = computed( => props.currentNodeId)
const { designTimeVariables } = useDesignTimeVariables(
 workflowNodesRef,
 workflowEdgesRef,
 currentNodeIdRef,
)
// Track if we're updating from external source to prevent loops
const isUpdatingFromExternal = ref(false)
/**
 * Serialize editor content to string with {{path}} syntax
 */
function serializeContent: string {
 if (!editor.value) return ''
 const doc = editor.value.getJSON
 const paragraphs: string =
 // Traverse document nodes
 for (const node of doc.content ?? ) {
 if (node.type === 'paragraph') {
 let paragraphText = ''
 for (const child of node.content ?? ) {
 if (child.type === 'text') {
 paragraphText += child.text ?? ''
 } else if (child.type === 'variable') {
 paragraphText += `{{${child.attrs?.path ?? ''}}}`
 }
 }
 paragraphs.push(paragraphText)
 }
 }
 return paragraphs.join('\n')
}
/**
 * Parse string with {{path}} syntax to editor content
 */
function parseContent(value: string): object {
 const lines = value.split('\n')
 const paragraphs: object =
 for (const line of lines) {
 const content: object =
 const regex = /\{\{([^}]+)\}\}/g
 let lastIndex = 0
 let match
 while ((match = regex.exec(line)) !== null) {
 // Add text before the match
 if (match.index > lastIndex) {
 content.push({
 type: 'text',
 text: line.slice(lastIndex, match.index),
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
 lastIndex = regex.lastIndex
 }
 // Add remaining text
 if (lastIndex < line.length) {
 content.push({
 type: 'text',
 text: line.slice(lastIndex),
 })
 }
 paragraphs.push({
 type: 'paragraph',
 content: content.length > 0 ? content: undefined,
 })
 }
 return {
 type: 'doc',
 content: paragraphs.length > 0 ? paragraphs: [{ type: 'paragraph' }],
 }
}
const editor = useEditor({
 extensions: [
 Document,
 Paragraph,
 Text,
 History,
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
 emit('update:modelValue', serializeContent)
 }
 },
 editorProps: {
 attributes: {
 class: 'outline-none min-',
 },
 },
})
// Sync external value changes to editor
watch( => props.modelValue, (newValue) => {
 if (!editor.value) return
 const currentValue = serializeContent
 if (newValue !== currentValue) {
 isUpdatingFromExternal.value = true
 editor.value.commands.setContent(parseContent(newValue))
 isUpdatingFromExternal.value = false
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
 focus-within:ring-offset-background transition-shadow
 max- overflow-y-auto":class="{ 'opacity-50 cursor-not-allowed': disabled }"
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
</style>
