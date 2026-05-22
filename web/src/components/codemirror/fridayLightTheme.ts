import { EditorView } from '@codemirror/view'
/**
 * Friday 项目专用 CodeMirror 6 浅色主题。
 *
 * 与 web/src/styles/main.css 中的 @theme 令牌对齐：
 * - 背景: 纯白 / slate-50
 * - 前景: slate-800 hsl(215 28% 17%)
 * - 主色: teal-500 hsl(168 76% 42%)
 * - 边框: slate-200 hsl(214 32% 91%)
 * - 弱化: slate-500 hsl(215 16% 47%)
 *
 * 取代 `@codemirror/theme-one-dark`：oneDark 设计目标是 #282c34 暗背景，
 * 叠加在 Friday 的浅色应用背景上会导致 WCAG 4.5:1 不达标（参见 DESIGN.md
 * 「文字层次」与 ui-ux-pro-max 「Color Contrast」规则）。
 */
export const fridayLightTheme = EditorView.theme(
 {
 '&': {
 color: 'hsl(215 28% 17%)',
 backgroundColor: 'hsl(0 0% 100%)',
 fontSize: '13px',
 },
 '.cm-content': {
 caretColor: 'hsl(168 76% 42%)',
 fontFamily:
 'ui-monospace, SFMono-Regular, "JetBrains Mono", "Fira Code", Menlo, Consolas, monospace',
 padding: '8px 0',
 },
 '.cm-cursor, .cm-dropCursor': {
 borderLeftColor: 'hsl(168 76% 42%)',
 borderLeftWidth: '2px',
 },
 '&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground, .cm-content:selection':
 {
 backgroundColor: 'hsl(168 76% 42% / 0.22)',
 },
 '.cm-panels': {
 backgroundColor: 'hsl(210 40% 98%)',
 color: 'hsl(215 28% 17%)',
 },
 '.cm-panels.cm-panels-top': {
 borderBottom: '1px solid hsl(214 32% 91%)',
 },
 '.cm-panels.cm-panels-bottom': {
 borderTop: '1px solid hsl(214 32% 91%)',
 },
 '.cm-searchMatch': {
 backgroundColor: 'hsl(38 92% 50% / 0.28)',
 outline: '1px solid hsl(38 92% 50% / 0.7)',
 },
 '.cm-searchMatch.cm-searchMatch-selected': {
 backgroundColor: 'hsl(168 76% 42% / 0.38)',
 outline: '1px solid hsl(168 76% 42%)',
 },
 '.cm-activeLine': {
 backgroundColor: 'hsl(168 76% 42% / 0.05)',
 },
 '.cm-activeLineGutter': {
 backgroundColor: 'hsl(168 76% 42% / 0.06)',
 },
 '.cm-gutters': {
 backgroundColor: 'hsl(210 40% 98%)',
 color: 'hsl(215 16% 55%)',
 border: 'none',
 borderRight: '1px solid hsl(214 32% 91%)',
 },
 '.cm-lineNumbers .cm-gutterElement': {
 color: 'hsl(215 16% 60%)',
 padding: '0 8px 0 6px',
 },
 '.cm-foldGutter .cm-gutterElement': {
 color: 'hsl(215 16% 55%)',
 },
 '.cm-tooltip': {
 backgroundColor: 'hsl(0 0% 100%)',
 color: 'hsl(215 28% 17%)',
 border: '1px solid hsl(214 32% 91%)',
 borderRadius: '0.5rem',
 boxShadow: '0 8px 24px rgba(15, 23, 42, 0.08), 0 2px 6px rgba(15, 23, 42, 0.05)',
 },
 '.cm-tooltip.cm-tooltip-autocomplete > ul > li[aria-selected]': {
 backgroundColor: 'hsl(168 76% 42% / 0.12)',
 color: 'hsl(168 76% 32%)',
 },
 '.cm-foldPlaceholder': {
 backgroundColor: 'hsl(210 40% 96%)',
 color: 'hsl(215 16% 47%)',
 border: '1px solid hsl(214 32% 91%)',
 padding: '0 4px',
 borderRadius: '4px',
 },
 '.cm-scroller': {
 lineHeight: '1.6',
 },
 /**
 * lint 弹窗与 diagnostic 文案在浅色背景下保持可读
 * （JsonEditor 启用 jsonParseLinter 时使用）。
 */
 '.cm-diagnostic-error': {
 borderLeft: '3px solid hsl(0 72% 51%)',
 backgroundColor: 'hsl(0 72% 51% / 0.06)',
 },
 '.cm-diagnostic-warning': {
 borderLeft: '3px solid hsl(38 92% 50%)',
 backgroundColor: 'hsl(38 92% 50% / 0.06)',
 },
 '.cm-lintRange-error': {
 backgroundImage:
 'url("data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A//www.w3.org/2000/svg%22%20width%3D%226%22%20height%3D%223%22%3E%3Cpath%20d%3D%22m0%203%20l2-2%20l1%201%20l2-2%20l1%201%22%20fill%3D%22none%22%20stroke%3D%22%23dc2626%22/%3E%3C/svg%3E")',
 },
 },
 { dark: false },
)
