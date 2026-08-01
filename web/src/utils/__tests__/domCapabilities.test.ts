/**
 * happy-dom 能力锁（115-02 Task 1，settle 115-RESEARCH 的 A2 假设）。
 *
 * **本用例的作用是锁住测试环境能力，不是测业务。** 任一项转红 = happy-dom 升级后
 * 丢了（或补上了）能力 ⇒ `utils/blueprintAnnotations.ts` 的 `collectTextNodes` 单测
 * 要改走注入 fixture 的路径（而 `offsetInFlatText` 那半是纯数据、恒可单测，不受影响）。
 *
 * 形态刻意是 `toMatchInlineSnapshot()` 而不是一串 `expect(...).toBe(true)`：
 * 快照**记录现实而非期望**，所以本 plan 的全绿门不会被环境事实卡住，而任何一项能力
 * 在 happy-dom 升级后发生变化仍会立刻转红。
 * ⛔ 不用 `expect.soft`（它只是失败后继续跑，用例照样红，与全绿门直接冲突）。
 * ⛔ 不删本用例。
 *
 * 已知且可接受的限制：happy-dom 无真实布局引擎 ⇒ `Range.prototype.getBoundingClientRect`
 * 即便存在也恒返 0 矩形。故只锁**存在性**，⛔ 不断言数值——选区 popover 的定位精度
 * 归 UAT。
 */
import { describe, expect, it } from 'vitest'

/** 四项能力的存在性 + 三项最小行为的实测结论（`true` = 该能力在本环境可用）。 */
function probeCapabilities(): Record<string, boolean> {
  const host = document.createElement('div')
  host.innerHTML = 'abc<span>def</span>ghi'
  document.body.append(host)

  const hasTreeWalker = typeof document.createTreeWalker === 'function'
  const hasRange = typeof document.createRange === 'function'
  const hasGetSelection = typeof window.getSelection === 'function'
  const hasRangeRect
    = typeof Range !== 'undefined' && typeof Range.prototype?.getBoundingClientRect === 'function'

  let treeWalkerFlattensText = false
  if (hasTreeWalker) {
    try {
      const walker = document.createTreeWalker(host, NodeFilter.SHOW_TEXT)
      let flat = ''
      let node = walker.nextNode()
      while (node) {
        flat += node.textContent ?? ''
        node = walker.nextNode()
      }
      treeWalkerFlattensText = flat === 'abcdefghi'
    }
    catch {
      treeWalkerFlattensText = false
    }
  }

  let rangeSelectsNodeContents = false
  if (hasRange) {
    try {
      const range = document.createRange()
      range.selectNodeContents(host)
      rangeSelectsNodeContents = range.toString() === host.textContent
    }
    catch {
      rangeSelectsNodeContents = false
    }
  }

  let selectionReturnsObject = false
  if (hasGetSelection) {
    try {
      selectionReturnsObject = window.getSelection() !== null
    }
    catch {
      selectionReturnsObject = false
    }
  }

  host.remove()

  return {
    createTreeWalker: hasTreeWalker,
    treeWalkerFlattensText,
    createRange: hasRange,
    rangeSelectsNodeContents,
    rangeGetBoundingClientRect: hasRangeRect,
    getSelection: hasGetSelection,
    selectionReturnsObject,
  }
}

describe('happy-dom 能力锁（A2 假设的正式 settle 记录）', () => {
  it('锁住 TreeWalker / Range / getSelection 的实测支持度', () => {
    // ⚠️ 快照值变化 = 测试环境能力变了，不是业务回归。改快照前先确认
    //    `collectTextNodes` / `rangeOffsets` 的单测策略是否需要跟着改（见文件头 docstring）。
    expect(probeCapabilities()).toMatchInlineSnapshot(`
      {
        "createRange": true,
        "createTreeWalker": true,
        "getSelection": true,
        "rangeGetBoundingClientRect": true,
        "rangeSelectsNodeContents": true,
        "selectionReturnsObject": true,
        "treeWalkerFlattensText": true,
      }
    `)
  })
})
