import { Extension } from '@tiptap/core'
import Suggestion, {
 type SuggestionProps as TipTapSuggestionProps,
 type SuggestionKeyDownProps,
} from '@tiptap/suggestion'
import { PluginKey } from '@tiptap/pm/state'
import type { DesignTimeVariable } from '~/composables/useDesignTimeVariables'
import type { VariableNodeAttrs } from '~/types/smart-input'
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
 // Render lifecycle - stub implementation for now
 // Will be replaced with actual Vue component rendering in Plan
 render: options.render ?? ( => {
 return {
 onStart(props: SuggestionProps) {
 // eslint-disable-next-line no-console
 console.debug('[VariableSuggestion] onStart', {
 query: props.query,
 itemCount: props.items.length,
 })
 },
 onUpdate(props: SuggestionProps) {
 // eslint-disable-next-line no-console
 console.debug('[VariableSuggestion] onUpdate', {
 query: props.query,
 itemCount: props.items.length,
 })
 },
 onKeyDown({ event }: SuggestionKeyDownProps): boolean {
 // Handle keyboard navigation
 // Return true if event was handled, false to let editor handle it
 if (event.key === 'Escape') {
 return true
 }
 return false
 },
 onExit {
 // eslint-disable-next-line no-console
 console.debug('[VariableSuggestion] onExit')
 },
 }
 }),
 }),
 ]
 },
 })
}
