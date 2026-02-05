import { mergeAttributes, Node } from '@tiptap/core'
import { VueNodeViewRenderer, type NodeViewProps } from '@tiptap/vue-3'
import type { Component } from 'vue'
import type { VariableNodeAttrs } from '~/types/smart-input'
import VariableChip from '../VariableChip.vue'
declare module '@tiptap/core' {
 interface Commands<ReturnType> {
 variable: {
 /**
 * Insert a variable node
 */
 insertVariable: (attrs: VariableNodeAttrs) => ReturnType
 }
 }
}
/**
 * VariableNode - TipTap Node extension for variable chips
 *
 * Renders variable references as atomic inline chips that cannot be
 * partially selected or edited. The node stores the full variable path
 * and metadata for serialization.
 *
 * @example
 * ```ts
 * editor.commands.insertVariable({
 * path: 'nodes.xxx.output_name',
 * label: '召回上下文.检索结果',
 * nodeId: 'xxx',
 * outputName: 'output_name',
 * })
 * ```
 */
export const VariableNode = Node.create({
 name: 'variable',
 group: 'inline',
 inline: true,
 // Treat as single indivisible unit - critical for chip behavior
 atom: true,
 // Allow selecting entire chip
 selectable: true,
 // Prevent drag to avoid confusion
 draggable: false,
 addAttributes {
 return {
 path: {
 default: '',
 parseHTML: (element: HTMLElement) => element.getAttribute('data-path') || '',
 renderHTML: (attributes: Record<string, string>) => ({
 'data-path': attributes.path,
 }),
 },
 label: {
 default: '',
 parseHTML: (element: HTMLElement) => element.getAttribute('data-label') || '',
 renderHTML: (attributes: Record<string, string>) => ({
 'data-label': attributes.label,
 }),
 },
 nodeId: {
 default: '',
 parseHTML: (element: HTMLElement) => element.getAttribute('data-node-id') || '',
 renderHTML: (attributes: Record<string, string>) => ({
 'data-node-id': attributes.nodeId,
 }),
 },
 outputName: {
 default: '',
 parseHTML: (element: HTMLElement) => element.getAttribute('data-output-name') || '',
 renderHTML: (attributes: Record<string, string>) => ({
 'data-output-name': attributes.outputName,
 }),
 },
 }
 },
 parseHTML {
 return [
 {
 tag: 'span[data-variable]',
 },
 ]
 },
 renderHTML({ HTMLAttributes }: { HTMLAttributes: Record<string, string> }) {
 return [
 'span',
 mergeAttributes(
 {
 'data-variable': '',
 'class': 'variable-chip',
 },
 HTMLAttributes,
 ),
 HTMLAttributes['data-label'] || '',
 ]
 },
 addCommands {
 return {
 insertVariable:
 (attrs: VariableNodeAttrs) =>
 ({ commands }) => {
 return commands.insertContent({
 type: this.name,
 attrs,
 })
 },
 }
 },
 addNodeView {
 return VueNodeViewRenderer(VariableChip as Component<NodeViewProps>)
 },
})
