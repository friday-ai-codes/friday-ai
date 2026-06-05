import type { SuggestionKeyDownProps, SuggestionProps as TipTapSuggestionProps } from '@tiptap/suggestion'
import type { App } from 'vue'
import type { BuiltInFunction } from './FunctionSuggestion'
import type { DesignTimeVariable } from '~/composables/useDesignTimeVariables'
import type { FunctionNodeAttrs, VariableNodeAttrs } from '~/types/smart-input'
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
 * Union type for suggestion items
 */
export type SuggestionItem
  = | { type: 'variable', data: DesignTimeVariable }
    | { type: 'function', data: BuiltInFunction }

/**
 * Suggestion props with our specific types
 */
export type SuggestionProps = TipTapSuggestionProps<SuggestionItem, VariableNodeAttrs | FunctionNodeAttrs>

/**
 * Options for creating the variable suggestion extension
 */
export interface VariableSuggestionOptions {
  /** Function to get available variables for autocomplete */
  items: () => DesignTimeVariable[]
  /** Function to get available functions for autocomplete */
  functions?: () => BuiltInFunction[]
  /** Callback when no variables are available */
  onEmpty?: () => void
  /** Custom render function for the suggestion popup */
  render?: () => {
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
 * shows a list of available upstream variables from the workflow DAG
 * and built-in expression functions.
 *
 * @example
 * ```ts
 * const editor = useEditor({
 *   extensions: [
 *     createVariableSuggestion({
 *       items: () => designTimeVariables.value,
 *       functions: () => BUILT_IN_FUNCTIONS,
 *     }),
 *   ],
 * })
 * ```
 */
export function createVariableSuggestion(options: VariableSuggestionOptions): Extension {
  return Extension.create({
    name: 'variableSuggestion',

    addStorage() {
      return {
        cleanup: null as (() => void) | null,
      }
    },

    onDestroy() {
      // 扩展销毁时确保清理残留的 scroll listener 和 popup
      this.storage.cleanup?.()
      this.storage.cleanup = null
    },

    addProseMirrorPlugins() {
      const extensionStorage = this.storage
      return [
        Suggestion<SuggestionItem, VariableNodeAttrs | FunctionNodeAttrs>({
          pluginKey: variableSuggestionPluginKey,
          editor: this.editor,

          // Trigger on `{{` - multi-character trigger
          char: '{{',

          // Don't allow spaces in the query (variable paths don't have spaces)
          allowSpaces: false,

          // Can trigger anywhere in text, not just at start of line
          startOfLine: false,

          // Filter items based on query
          items: ({ query }): SuggestionItem[] => {
            const allVariables = options.items()
            const allFunctions = options.functions?.() ?? []
            const result: SuggestionItem[] = []

            // If no items available and no functions, call onEmpty callback
            if (allVariables.length === 0 && allFunctions.length === 0) {
              options.onEmpty?.()
              return []
            }

            // If query is empty, return all items (max 50)
            if (!query) {
              allVariables.slice(0, 50).forEach(v => result.push({ type: 'variable', data: v }))
              allFunctions.forEach(f => result.push({ type: 'function', data: f }))
              return result
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
              allVariables.slice(0, 50).forEach(v => result.push({ type: 'variable', data: v }))
              allFunctions.forEach(f => result.push({ type: 'function', data: f }))
              return result
            }

            const lowerQuery = filterQuery.toLowerCase()

            // Filter variables by label and path (case-insensitive)
            const matchedVariables = allVariables
              .filter(
                item =>
                  item.label.toLowerCase().includes(lowerQuery)
                  || item.path.toLowerCase().includes(lowerQuery),
              )
              .slice(0, 50)

            matchedVariables.forEach(v => result.push({ type: 'variable', data: v }))

            // Filter functions by name and description
            const matchedFunctions = allFunctions
              .filter(
                f =>
                  f.name.toLowerCase().includes(lowerQuery)
                  || f.description.toLowerCase().includes(lowerQuery),
              )

            matchedFunctions.forEach(f => result.push({ type: 'function', data: f }))

            return result
          },

          // Command to execute when item is selected
          command: ({ editor, range, props }) => {
            // Distinguish function vs variable by checking for 'name' attribute
            if ('name' in props) {
              // Function node
              editor
                .chain()
                .focus()
                .deleteRange(range)
                .insertContent({
                  type: 'function',
                  attrs: props,
                })
                .run()
            }
            else {
              // Variable node
              editor
                .chain()
                .focus()
                .deleteRange(range)
                .insertContent({
                  type: 'variable',
                  attrs: props,
                })
                .run()
            }
          },

          // Render lifecycle - mounts Vue popup component
          render: options.render ?? (() => {
            let popup: HTMLElement | null = null
            let app: App | null = null
            let componentRef: { onKeyDown: (event: KeyboardEvent) => boolean } | null = null
            let currentProps: SuggestionProps | null = null
            let scrollHandler: (() => void) | null = null

            // Position popup relative to cursor with auto flip (vertical & horizontal)
            function updatePosition(props: SuggestionProps) {
              if (!popup)
                return

              const clientRect = props.clientRect?.()
              if (!clientRect) {
                popup.style.visibility = 'hidden'
                return
              }

              const popupWidth = popup.offsetWidth || 256 // min-w-64 = 256px
              const popupHeight = popup.offsetHeight || 288 // max-h-72 = 288px
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
            function onScroll() {
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
                const command = (item: SuggestionItem) => {
                  if (item.type === 'variable') {
                    const variable = item.data

                    // Check if user was in JSONPath mode (query started with $)
                    const { state } = props.editor
                    const textBefore = state.doc.textBetween(props.range.from, props.range.to, '')
                    const isJsonPathMode = textBefore.startsWith('$')

                    const finalPath = isJsonPathMode ? `$.${variable.path}` : variable.path

                    props.command({
                      path: finalPath,
                      label: isJsonPathMode ? `$ ${variable.label}` : variable.label,
                      nodeId: variable.nodeId,
                      outputName: variable.key,
                    } satisfies VariableNodeAttrs)
                  }
                  else if (item.type === 'function') {
                    const func = item.data
                    props.command({
                      name: func.name,
                      args: func.params.map(() => ''),
                    } satisfies FunctionNodeAttrs)
                  }
                }

                // Mount Vue component
                app = createApp({
                  setup() {
                    return () => h(VariableSuggestionList, {
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
                requestAnimationFrame(() => updatePosition(props))

                // Listen to scroll events on all scrollable ancestors
                scrollHandler = onScroll
                window.addEventListener('scroll', scrollHandler, true)

                // 将清理函数存入 extension storage，供 onDestroy 调用
                extensionStorage.cleanup = () => {
                  if (scrollHandler) {
                    window.removeEventListener('scroll', scrollHandler, true)
                    scrollHandler = null
                  }
                  if (app) {
                    app.unmount()
                    app = null
                  }
                  if (popup) {
                    popup.remove()
                    popup = null
                  }
                  componentRef = null
                  currentProps = null
                }
              },

              onUpdate(props: SuggestionProps) {
                currentProps = props

                // Update items reactively - remount with new props
                if (app && popup) {
                  app.unmount()

                  const items = ref(props.items)
                  const command = (item: SuggestionItem) => {
                    if (item.type === 'variable') {
                      const variable = item.data

                      const { state } = props.editor
                      const textBefore = state.doc.textBetween(props.range.from, props.range.to, '')
                      const isJsonPathMode = textBefore.startsWith('$')

                      const finalPath = isJsonPathMode ? `$.${variable.path}` : variable.path

                      props.command({
                        path: finalPath,
                        label: isJsonPathMode ? `$ ${variable.label}` : variable.label,
                        nodeId: variable.nodeId,
                        outputName: variable.key,
                      } satisfies VariableNodeAttrs)
                    }
                    else if (item.type === 'function') {
                      const func = item.data
                      props.command({
                        name: func.name,
                        args: func.params.map(() => ''),
                      } satisfies FunctionNodeAttrs)
                    }
                  }

                  app = createApp({
                    setup() {
                      return () => h(VariableSuggestionList, {
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
                  requestAnimationFrame(() => updatePosition(props))
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

              onExit() {
                // Remove scroll listener
                if (scrollHandler) {
                  window.removeEventListener('scroll', scrollHandler, true)
                  scrollHandler = null
                }

                // Cleanup: unmount Vue app and remove popup from DOM
                if (app) {
                  app.unmount()
                  app = null
                }
                if (popup) {
                  popup.remove()
                  popup = null
                }
                componentRef = null
                currentProps = null
                extensionStorage.cleanup = null
              },
            }
          }),
        }),
      ]
    },
  })
}
