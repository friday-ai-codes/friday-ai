import type { NodeViewProps } from '@tiptap/vue-3'
import type { Component } from 'vue'
import type { FunctionNodeAttrs } from '~/types/smart-input'
import { InputRule, mergeAttributes, Node } from '@tiptap/core'
import { VueNodeViewRenderer } from '@tiptap/vue-3'
import FunctionChip from '../FunctionChip.vue'
declare module '@tiptap/core' {
 interface Commands<ReturnType> {
 function: {
 /**
 * Insert a function node
 */
 insertFunction: (attrs: FunctionNodeAttrs) => ReturnType
 }
 }
}
/**
 * FunctionNode - TipTap Node extension for function call chips
 *
 * Renders function calls as atomic inline chips that cannot be
 * partially selected or edited. The node stores the function name
 * and arguments for serialization.
 *
 * @example
 * ```ts
 * editor.commands.insertFunction({
 * name: 'concat',
 * args: ['Hello ', '{{user.name}}'],
 * })
 * ```
 */
export const FunctionNode = Node.create({
 name: 'function',
 group: 'inline',
 inline: true,
 atom: true,
 selectable: true,
 draggable: false,
 addAttributes {
 return {
 name: {
 default: '',
 parseHTML: (element: HTMLElement) => element.getAttribute('data-name') || '',
 renderHTML: (attributes: Record<string, unknown>) => ({
 'data-name': attributes.name,
 }),
 },
 args: {
 default:,
 parseHTML: (element: HTMLElement) => {
 const raw = element.getAttribute('data-args')
 if (!raw)
 return
 try {
 return JSON.parse(raw)
 }
 catch {
 return
 }
 },
 renderHTML: (attributes: Record<string, unknown>) => ({
 'data-args': JSON.stringify(attributes.args ?? ),
 }),
 },
 }
 },
 parseHTML {
 return [
 {
 tag: 'span[data-function]',
 },
 ]
 },
 renderHTML({ HTMLAttributes }: { HTMLAttributes: Record<string, string> }) {
 return [
 'span',
 mergeAttributes(
 {
 'data-function': '',
 'class': 'function-chip',
 },
 HTMLAttributes,
 ),
 `${HTMLAttributes['data-name'] ?? ''}`,
 ]
 },
 addCommands {
 return {
 insertFunction:
 (attrs: FunctionNodeAttrs) =>
 ({ commands }) => {
 return commands.insertContent({
 type: this.name,
 attrs,
 })
 },
 }
 },
 addNodeView {
 return VueNodeViewRenderer(FunctionChip as Component<NodeViewProps>)
 },
 addInputRules {
 const type = this.type
 return [
 new InputRule({
 find: /\{\{(\w+)\(([^)]*)\)\}\}$/,
 handler: ({ state, range, match }) => {
 const name = match[1]
 const argsRaw = match[2].trim
 const args = argsRaw ? argsRaw.split(',').map(s => s.trim):
 const { tr } = state
 const node = type.create({
 name,
 args,
 } satisfies FunctionNodeAttrs)
 tr.replaceWith(range.from, range.to, node)
 },
 }),
 ]
 },
})
