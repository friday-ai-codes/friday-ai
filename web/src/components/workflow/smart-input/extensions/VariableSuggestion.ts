import type { SuggestionKeyDownProps, SuggestionProps as TipTapSuggestionProps } from '@tiptap/suggestion'
import type { App } from 'vue'
import type { DesignTimeVariable } from '~/composables/useDesignTimeVariables'
import type { VariableNodeAttrs } from '~/types/smart-input'
import { Extension } from '@tiptap/core'
import { PluginKey } from '@tiptap/pm/state'
import Suggestion from '@tiptap/suggestion'
import { createApp, h, ref } from 'vue'
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
 // If query is empty, return all items (max 50)
 if (!query) {
 return allItems.slice(0, 50)
 }
 // JSONPath mode: query starts with $
 // Strip the $ prefix for filtering, but we'll add it back when inserting
 let filterQuery = query
 if (query.startsWith('$')) {
 // Remove $ and optional . prefix for filtering
 filterQuery = query.replace(/^\$\.?/, '')
 }
 // If filterQuery is empty after stripping $, return all items
 if (!filterQuery) {
 return allItems.slice(0, 50)
 }
 // Fuzzy filter by label and path (case-insensitive)
 const lowerQuery = filterQuery.toLowerCase
 return allItems
 .filter(
 item =>
 item.label.toLowerCase.includes(lowerQuery)
 || item.path.toLowerCase.includes(lowerQuery),
 )
 .slice(0, 50)
 },
 // Command to execute when item is selected
 command: ({ editor, range, props }) => {
 // Check if user was in JSONPath mode (query started with $)
 // We detect this by checking the text before the range
 const { state } = editor
 const textBefore = state.doc.textBetween(range.from, range.to, '')
 const isJsonPathMode = textBefore.startsWith('$')
 // Build the path - add $ prefix for JSONPath mode
 const finalPath = isJsonPathMode ? `$.${props.path}`: props.path
 // Delete the trigger range (removes `{{` and any typed query)
 // Then insert the variable node with attributes from props
 editor
 .chain
 .focus
 .deleteRange(range)
 .insertContent({
 type: 'variable',
 attrs: {
 path: finalPath,
 label: isJsonPathMode ? `$ ${props.label}`: props.label,
 nodeId: props.nodeId,
 outputName: props.outputName,
 } satisfies VariableNodeAttrs,
 })
 .run
 },
 // Render lifecycle - mounts Vue popup component
 render: options.render ?? ( => {
 let popup: HTMLElement | null = null
 let app: App | null = null
 let componentRef: { onKeyDown: (event: KeyboardEvent) => boolean } | null = null
 let currentProps: SuggestionProps | null = null
 let scrollHandler: ( => void) | null = null
 // Position popup relative to cursor with auto flip (vertical & horizontal)
 function updatePosition(props: SuggestionProps) {
 if (!popup)
 return
 const clientRect = props.clientRect?.
 if (!clientRect) {
 popup.style.visibility = 'hidden'
 return
 }
 const popupWidth = popup.offsetWidth || 256 // min-w-64 = 256px
 const popupHeight = popup.offsetHeight || 288 // max- = 288px
 const gap = 8
 const viewportWidth = window.innerWidth
 const viewportHeight = window.innerHeight
 // Check if cursor is visible in viewport
 const cursorVisible
 = clientRect.top >= 0
 && clientRect.bottom <= viewportHeight
 && clientRect.left >= 0
 && clientRect.right <= viewportWidth
 if (!cursorVisible) {
 popup.style.visibility = 'hidden'
 return
 }
 popup.style.visibility = 'visible'
 // Vertical positioning: check space below vs above
 const spaceBelow = viewportHeight - clientRect.bottom - gap
 const spaceAbove = clientRect.top - gap
 let top: number
 if (spaceBelow >= popupHeight || spaceBelow >= spaceAbove) {
 top = clientRect.bottom + gap
 }
 else {
 top = clientRect.top - popupHeight - gap
 }
 // Horizontal positioning: check space right vs left
 const spaceRight = viewportWidth - clientRect.left
 const spaceLeft = clientRect.right
 let left: number
 if (spaceRight >= popupWidth) {
 // Align to cursor left
 left = clientRect.left
 }
 else if (spaceLeft >= popupWidth) {
 // Align to cursor right, popup extends left
 left = clientRect.right - popupWidth
 }
 else {
 // Center in viewport if neither side has enough space
 left = Math.max(gap, (viewportWidth - popupWidth) / 2)
 }
 // Clamp to viewport bounds
 left = Math.max(gap, Math.min(left, viewportWidth - popupWidth - gap))
 top = Math.max(gap, Math.min(top, viewportHeight - popupHeight - gap))
 Object.assign(popup.style, {
 position: 'fixed',
 left: `${left}px`,
 top: `${top}px`,
 zIndex: '9999',
 })
 }
 // Handle scroll events to update position
 function onScroll {
 if (currentProps) {
 updatePosition(currentProps)
 }
 }
 return {
 onStart(props: SuggestionProps) {
 currentProps = props
 // Create popup container on body
 popup = document.createElement('div')
 popup.className = 'variable-suggestion-popup'
 // Set width constraints: content-based with min/max limits
 Object.assign(popup.style, {
 width: 'max-content',
 minWidth: '256px',
 maxWidth: '400px',
 })
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
 // Position after mount so we can measure popup height
 requestAnimationFrame( => updatePosition(props))
 // Listen to scroll events on all scrollable ancestors
 scrollHandler = onScroll
 window.addEventListener('scroll', scrollHandler, true)
 },
 onUpdate(props: SuggestionProps) {
 currentProps = props
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
 requestAnimationFrame( => updatePosition(props))
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
 // Remove scroll listener
 if (scrollHandler) {
 window.removeEventListener('scroll', scrollHandler, true)
 scrollHandler = null
 }
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
 currentProps = null
 },
 }
 }),
 }),
 ]
 },
 })
}
