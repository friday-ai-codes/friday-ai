import { Extension } from '@tiptap/core'
import Suggestion, {
 type SuggestionProps as TipTapSuggestionProps,
 type SuggestionKeyDownProps,
} from '@tiptap/suggestion'
import { PluginKey } from '@tiptap/pm/state'
import { createApp, ref, h, type App } from 'vue'
import { computePosition, flip, offset, shift } from '@floating-ui/dom'
import type { DesignTimeVariable } from '~/composables/useDesignTimeVariables'
import type { VariableNodeAttrs } from '~/types/smart-input'
import VariableSuggestionList from '../VariableSuggestionList.vue'
/**
 * Plugin key for the variable suggestion plugin
 * Used to access the plugin state from outside
 */
export const variableSuggestionPluginKey = new PluginKey('variableSuggestion')
/**
 * Suggestion props with our specific types
 */
export type SuggestionProps = TipTapSuggestionProps<DesignTimeVariable, VariableNodeAttrs>
/**
 * Options for creating the variable suggestion extension
 */
export interface VariableSuggestionOptions {
 /** Function to get available variables for autocomplete */
 items: => DesignTimeVariable
 /** Callback when no variables are available */
 onEmpty?: => void
 /** Custom render function for the suggestion popup */
 render?: => {
 onStart?: (props: SuggestionProps) => void
 onUpdate?: (props: SuggestionProps) => void
 onKeyDown?: (props: SuggestionKeyDownProps) => boolean
 onExit?: (props: SuggestionProps) => void
 }
}
/**
 * Create a variable suggestion extension for TipTap
 *
 * This extension triggers autocomplete when the user types `{{` and
 * shows a list of available upstream variables from the workflow DAG.
 *
 * @example
 * ```ts
 * const editor = useEditor({
 * extensions: [
 * createVariableSuggestion({
 * items: => designTimeVariables.value,
 * }),
 * ],
 * })
 * ```
 */
export function createVariableSuggestion(options: VariableSuggestionOptions): Extension {
 return Extension.create({
 name: 'variableSuggestion',
 addProseMirrorPlugins {
 return [
 Suggestion<DesignTimeVariable, VariableNodeAttrs>({
 pluginKey: variableSuggestionPluginKey,
 editor: this.editor,
 // Trigger on `{{` - multi-character trigger
 char: '{{',
 // Don't allow spaces in the query (variable paths don't have spaces)
 allowSpaces: false,
 // Can trigger anywhere in text, not just at start of line
 startOfLine: false,
 // Filter items based on query
 items: ({ query }): DesignTimeVariable => {
 const allItems = options.items
 // If no items available, call onEmpty callback
 if (allItems.length === 0) {
 options.onEmpty?.
 return
 }
 // If query is empty, return first 10 items
 if (!query) {
 return allItems.slice(0, 10)
 }
 // Fuzzy filter by label and path (case-insensitive)
 const lowerQuery = query.toLowerCase
 return allItems
 .filter(
 item =>
 item.label.toLowerCase.includes(lowerQuery) ||
 item.path.toLowerCase.includes(lowerQuery),
 )
 .slice(0, 10)
 },
 // Command to execute when item is selected
 command: ({ editor, range, props }) => {
 // Delete the trigger range (removes `{{` and any typed query)
 // Then insert the variable node with attributes from props
 editor
 .chain
 .focus
 .deleteRange(range)
 .insertContent({
 type: 'variable',
 attrs: {
 path: props.path,
 label: props.label,
 nodeId: props.nodeId,
 outputName: props.outputName,
 } satisfies VariableNodeAttrs,
 })
 .run
 },
 // Render lifecycle - mounts Vue popup component with Floating UI positioning
 render: options.render ?? ( => {
 let popup: HTMLElement | null = null
 let app: App | null = null
 let componentRef: { onKeyDown: (event: KeyboardEvent) => boolean } | null = null
 return {
 onStart(props: SuggestionProps) {
 // Create popup container
 popup = document.createElement('div')
 popup.className = 'variable-suggestion-popup'
 document.body.appendChild(popup)
 // Create reactive props for the Vue component
 const items = ref(props.items)
 const command = (item: DesignTimeVariable) => {
 props.command({
 path: item.path,
 label: item.label,
 nodeId: item.nodeId,
 outputName: item.key,
 })
 }
 // Mount Vue component
 app = createApp({
 setup {
 return => h(VariableSuggestionList, {
 items: items.value,
 command,
 ref: (el: any) => {
 componentRef = el
 },
 })
 },
 })
 app.mount(popup)
 // Position popup using Floating UI
 const updatePosition = async => {
 if (!popup || !props.clientRect) return
 // Create a virtual element from clientRect
 const virtualEl = {
 getBoundingClientRect: => props.clientRect! ?? new DOMRect,
 }
 const { x, y } = await computePosition(virtualEl, popup, {
 placement: 'bottom-start',
 middleware: [
 offset(8),
 flip,
 shift({ padding: 8 }),
 ],
 })
 Object.assign(popup.style, {
 position: 'fixed',
 left: `${x}px`,
 top: `${y}px`,
 zIndex: '9999',
 })
 }
 updatePosition
 },
 onUpdate(props: SuggestionProps) {
 // Update items reactively - remount with new props
 if (app && popup) {
 app.unmount
 const items = ref(props.items)
 const command = (item: DesignTimeVariable) => {
 props.command({
 path: item.path,
 label: item.label,
 nodeId: item.nodeId,
 outputName: item.key,
 })
 }
 app = createApp({
 setup {
 return => h(VariableSuggestionList, {
 items: items.value,
 command,
 ref: (el: any) => {
 componentRef = el
 },
 })
 },
 })
 app.mount(popup)
 // Update position
 const updatePosition = async => {
 if (!popup || !props.clientRect) return
 const virtualEl = {
 getBoundingClientRect: => props.clientRect! ?? new DOMRect,
 }
 const { x, y } = await computePosition(virtualEl, popup, {
 placement: 'bottom-start',
 middleware: [
 offset(8),
 flip,
 shift({ padding: 8 }),
 ],
 })
 Object.assign(popup.style, {
 position: 'fixed',
 left: `${x}px`,
 top: `${y}px`,
 zIndex: '9999',
 })
 }
 updatePosition
 }
 },
 onKeyDown({ event }: SuggestionKeyDownProps): boolean {
 // Forward keyboard events to the Vue component
 if (componentRef?.onKeyDown) {
 return componentRef.onKeyDown(event)
 }
 // Handle Escape to close popup
 if (event.key === 'Escape') {
 return true
 }
 return false
 },
 onExit {
 // Cleanup: unmount Vue app and remove popup from DOM
 if (app) {
 app.unmount
 app = null
 }
 if (popup) {
 popup.remove
 popup = null
 }
 componentRef = null
 },
 }
 }),
 }),
 ]
 },
 })
}
