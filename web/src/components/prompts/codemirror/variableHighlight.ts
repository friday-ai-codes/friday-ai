/**
 * CodeMirror 6 自定义扩展：装饰所有 {{var}} 占位符。
 *
 * ⚠️⚠️⚠️ 同步约束 ⚠️⚠️⚠️
 * 此处 regex 必须与 server/prompts/services.py::_PLACEHOLDER_RE 字符级一致。
 * 后端定义（server/prompts/services.py:39-41）：
 *     r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}"
 *
 * 修改此处时必须同步修改后端。契约测试位于
 * web/src/components/prompts/codemirror/__tests__/variableHighlight.test.ts
 * （描述块「PLACEHOLDER_RE 契约」读后端文件字面量比对，drift 会导致 CI 红）。
 *
 * 参考：https://codemirror.net/examples/decoration/
 */

import type { DecorationSet, EditorView, ViewUpdate } from '@codemirror/view'
import { Decoration, MatchDecorator, ViewPlugin } from '@codemirror/view'

/**
 * 占位符正则 —— 与后端 _PLACEHOLDER_RE 字符级一致。
 *
 * 语义：`{{var}}` 或 `{{ var }}`，变量名必须为 Python 标识符
 * （字母或下划线开头，后跟字母/数字/下划线）。
 *
 * 禁用 regexp/prefer-w / regexp/use-ignore-case：这两条规则会把字面量简化为 `\w`
 * 或添加 `/i` flag，与后端 `server/prompts/services.py::_PLACEHOLDER_RE` 字面偏差，
 * 导致本文件的契约测试失败（readFileSync 字面比对）。
 */
// eslint-disable-next-line regexp/prefer-w, regexp/use-ignore-case
export const PLACEHOLDER_RE = /\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}/g

/**
 * 从 body 文本中抽取所有声明变量，返回字母序去重列表。
 *
 * 陷阱：JavaScript 全局正则的 `exec` 维护 `lastIndex` 状态，
 * 必须在函数开头重置为 0，否则连续调用会漏匹配。
 */
export function extractVariables(body: string): string[] {
  const found = new Set<string>()
  PLACEHOLDER_RE.lastIndex = 0
  let match: RegExpExecArray | null = PLACEHOLDER_RE.exec(body)
  while (match !== null) {
    found.add(match[1])
    match = PLACEHOLDER_RE.exec(body)
  }
  return [...found].sort()
}

/**
 * MatchDecorator 实例：装饰类名由 variableHighlight() 的调用点动态决定。
 *
 * 注意：
 * - MatchDecorator 的 regex 要求 /g flag 并且仅单行内匹配，对 {{var}} 这类单行占位符契合
 * - `boundary: /\s/` 作为增量匹配边界优化提示
 */
const variableMatcher = new MatchDecorator({
  regexp: PLACEHOLDER_RE,
  decoration: () => Decoration.mark({ class: 'cm-prompt-variable' }),
  boundary: /\s/,
})

/**
 * 装饰 {{var}} 占位符的 ViewPlugin。
 *
 * 使用 MatchDecorator + ViewPlugin.fromClass 组合（CodeMirror 官方 placeholder 模板），
 * 性能 O(viewport) 而非 O(body)，32KB body 无压力。
 */
export function variableHighlight() {
  return ViewPlugin.fromClass(
    class {
      decorations: DecorationSet

      constructor(view: EditorView) {
        this.decorations = variableMatcher.createDeco(view)
      }

      update(update: ViewUpdate) {
        this.decorations = variableMatcher.updateDeco(update, this.decorations)
      }
    },
    {
      decorations: instance => instance.decorations,
    },
  )
}
