/**
 * blueprintAnnotations.ts 契约单测（Phase 115-02）。
 *
 * 三个靶子：
 * 1. 区间切分的**六类边界** + 「拼接回原文」不变式（任何切点算术错误都逃不掉）；
 * 2. 两段式 offset 里**纯数据那半**（`offsetInFlatText`）恒可单测；触 DOM 那半
 *    （`collectTextNodes`）按能力锁结论走自动化（happy-dom 20.10.2 支持 TreeWalker）；
 * 3. ⭐ **P-7 三态不混**的三条并列断言（越界降级 / 后端失锚 / 无 anchor 的系统线程）。
 */
import type { BlueprintThreadDetail } from '~/types/blueprint'
import { describe, expect, it } from 'vitest'
import {
  annotationCounts,
  collectTextNodes,
  degradedThreadIds,
  groupThreadsByBlock,
  hasAnchorLocator,
  isUnresolvedBlocker,
  isValidAnchor,
  offsetInFlatText,
  sidebarGroups,
  sidebarKindGroups,
  sliceBlockText,
} from '../blueprintAnnotations'

const TEXT = '0123456789'

describe('isValidAnchor —— 越界降级的判据', () => {
  it.each([
    [{ start: 0, end: 10 }, true],
    [{ start: 2, end: 5 }, true],
    [{ start: 0, end: 11 }, false],
    [{ start: 5, end: 5 }, false],
    [{ start: 6, end: 3 }, false],
    [{ start: -1, end: 3 }, false],
    [{ start: 1.5, end: 3 }, false],
    [{ start: 1, end: 3.5 }, false],
    [{ start: '1' as unknown as number, end: 3 }, false],
    [{ start: undefined, end: 3 }, false],
  ])('%j → %s', (anchor, expected) => {
    expect(isValidAnchor(anchor, TEXT.length)).toBe(expected)
  })
})

describe('sliceBlockText —— 六类边界 + 拼接还原', () => {
  it('越界（end > text.length）⇒ 该区间被剔除，退化成单段全文', () => {
    const result = sliceBlockText(TEXT, [{ threadId: 't1', start: 0, end: 99 }])
    expect(result).toEqual([{ text: TEXT, threadIds: [] }])
  })

  it('反序（start >= end）⇒ 被剔除', () => {
    expect(sliceBlockText(TEXT, [{ threadId: 't1', start: 6, end: 3 }])).toEqual([
      { text: TEXT, threadIds: [] },
    ])
  })

  it('⭐ 重叠 ⇒ 切成三段不合并，中间段携带两条 threadId', () => {
    const result = sliceBlockText(TEXT, [
      { threadId: 't1', start: 1, end: 5 },
      { threadId: 't2', start: 3, end: 8 },
    ])
    expect(result).toEqual([
      { text: '0', threadIds: [] },
      { text: '12', threadIds: ['t1'] },
      { text: '34', threadIds: ['t1', 't2'] },
      { text: '567', threadIds: ['t2'] },
      { text: '89', threadIds: [] },
    ])
    expect(result[2].threadIds).toHaveLength(2)
  })

  it('非整数 offset ⇒ 被剔除', () => {
    expect(sliceBlockText(TEXT, [{ threadId: 't1', start: 1.5, end: 4 }])).toEqual([
      { text: TEXT, threadIds: [] },
    ])
  })

  it('空 anchors ⇒ 单段全文', () => {
    expect(sliceBlockText(TEXT, [])).toEqual([{ text: TEXT, threadIds: [] }])
  })

  it('全覆盖（0..length）⇒ 单段且带 threadId', () => {
    expect(sliceBlockText(TEXT, [{ threadId: 't1', start: 0, end: 10 }])).toEqual([
      { text: TEXT, threadIds: ['t1'] },
    ])
  })

  it('⭐ 不变式：拼接回原文（任何切点算术错误都会破坏它）', () => {
    const cases: Parameters<typeof sliceBlockText>[1][] = [
      [],
      [{ threadId: 'a', start: 0, end: 1 }],
      [{ threadId: 'a', start: 9, end: 10 }],
      [{ threadId: 'a', start: 1, end: 5 }, { threadId: 'b', start: 3, end: 8 }],
      [{ threadId: 'a', start: 2, end: 4 }, { threadId: 'b', start: 4, end: 6 }],
      [{ threadId: 'a', start: 0, end: 10 }, { threadId: 'b', start: 2, end: 3 }],
      [{ threadId: 'a', start: 1, end: 99 }, { threadId: 'b', start: 2, end: 3 }],
    ]
    for (const anchors of cases) {
      const joined = sliceBlockText(TEXT, anchors).map(s => s.text).join('')
      expect(joined, `anchors=${JSON.stringify(anchors)}`).toBe(TEXT)
    }
  })

  it('相邻不重叠区间 ⇒ 两段各带一条，无空段', () => {
    const result = sliceBlockText(TEXT, [
      { threadId: 'a', start: 0, end: 5 },
      { threadId: 'b', start: 5, end: 10 },
    ])
    expect(result).toEqual([
      { text: '01234', threadIds: ['a'] },
      { text: '56789', threadIds: ['b'] },
    ])
  })

  it('空文本 ⇒ 空数组（拼接仍等于原文）', () => {
    expect(sliceBlockText('', [{ threadId: 'a', start: 0, end: 1 }])).toEqual([])
    expect(sliceBlockText('', []).map(s => s.text).join('')).toBe('')
  })

  it('非字符串 / 非数组入参恒不抛', () => {
    expect(sliceBlockText(null as unknown as string, [])).toEqual([])
    expect(sliceBlockText(TEXT, null as unknown as [])).toEqual([{ text: TEXT, threadIds: [] }])
  })
})

describe('degradedThreadIds —— 整块降级集合', () => {
  it('只报不合法的那几条', () => {
    const ids = degradedThreadIds(TEXT, [
      { threadId: 'ok', start: 1, end: 3 },
      { threadId: 'oob', start: 0, end: 99 },
      { threadId: 'rev', start: 5, end: 2 },
    ])
    expect(ids).toEqual(['oob', 'rev'])
  })
})

describe('offsetInFlatText —— 纯数据、恒可单测', () => {
  // 构造三个「假文本节点」，⛔ 不依赖真实 DOM。
  const nodes = [{ length: 3 }, { length: 3 }, { length: 3 }]

  it.each([
    [0, 0, 0],
    [0, 2, 2],
    [1, 0, 3],
    [1, 2, 5],
    [2, 3, 9],
  ])('第 %i 个节点内 offset %i → 扁平 %i', (nodeIdx, offset, expected) => {
    expect(offsetInFlatText(nodes, nodes[nodeIdx], offset)).toBe(expected)
  })

  it('局部 offset 超出该节点长度时被夹住，⛔ 不溢出到下一节点', () => {
    expect(offsetInFlatText(nodes, nodes[0], 99)).toBe(3)
    expect(offsetInFlatText(nodes, nodes[0], -5)).toBe(0)
  })

  it('container 不在 nodes 里 ⇒ -1（调用方据此走整块降级）', () => {
    expect(offsetInFlatText(nodes, { length: 3 }, 1)).toBe(-1)
    expect(offsetInFlatText([], nodes[0], 0)).toBe(-1)
  })

  it('用 textContent 表达长度的节点同样可算', () => {
    const textual = [{ textContent: 'ab' }, { textContent: 'cde' }]
    expect(offsetInFlatText(textual, textual[1], 2)).toBe(4)
  })
})

describe('collectTextNodes —— 触 DOM 的薄函数（能力锁判定 happy-dom 支持 TreeWalker）', () => {
  it('收集到三个文本节点且顺序正确', () => {
    const host = document.createElement('div')
    host.innerHTML = 'abc<span>def</span>ghi'
    const nodes = collectTextNodes(host)
    expect(nodes).toHaveLength(3)
    expect(nodes.map(n => n.textContent).join('')).toBe('abcdefghi')
  })

  it('与 offsetInFlatText 组合出 block 坐标系', () => {
    const host = document.createElement('div')
    host.innerHTML = 'abc<span>def</span>ghi'
    const nodes = collectTextNodes(host)
    // <span> 里的 'def' 的第 1 个字符 = 扁平坐标 4
    expect(offsetInFlatText(nodes, nodes[1], 1)).toBe(4)
  })

  it('null root ⇒ 空数组', () => {
    expect(collectTextNodes(null)).toEqual([])
  })
})

function thread(overrides: Partial<BlueprintThreadDetail>): BlueprintThreadDetail {
  return {
    thread_id: 't',
    kind: 'ai_clarification',
    severity: '',
    status: 'open',
    blocking: false,
    anchor_status: 'anchored',
    anchor: { block_id: 'b1', start_offset: 0, end_offset: 3 },
    return_stage: 'drafting',
    created_at: '2026-07-01T00:00:00Z',
    options: [],
    last_reminded_at: null,
    messages: [],
    ...overrides,
  }
}

describe('sidebarGroups —— 四组互斥 + P-7 三态不混（三条并列）', () => {
  it('⭐ (a) 一条 open 的失锚线程只出现在失锚组，四组总数 == 线程总数（§20 断言 11）', () => {
    const orphan = thread({ thread_id: 'orphan', status: 'open', anchor_status: 'orphaned' })
    const groups = sidebarGroups([orphan], [orphan])
    const total = groups.open.length + groups.answered.length + groups.closed.length + groups.orphaned.length
    expect(total).toBe(1)
    expect(groups.orphaned.map(t => t.thread_id)).toEqual(['orphan'])
    // 变异提示：去掉前三组的 `&& anchor_status !== 'orphaned'` ⇒ total 变 2，本条转红。
    expect(groups.open).toHaveLength(0)
  })

  it('⭐ (b) anchor === null 且 anchor_status === anchored 的系统线程仍进 status 组（P-7 第三态）', () => {
    const systemThread = thread({
      thread_id: 'sys',
      kind: 'repo_confirmation',
      status: 'open',
      anchor: null,
      anchor_status: 'anchored',
    })
    const groups = sidebarGroups([systemThread], [])
    expect(groups.open.map(t => t.thread_id)).toEqual(['sys'])
    expect(groups.orphaned).toHaveLength(0)
    // 但正文里没有任何标记：它进不了任何 block 分组。
    expect(groupThreadsByBlock([systemThread])).toEqual({})
  })

  it('⭐ (c) end_offset 越界的 anchored 线程走降级但不进失锚组（§20 断言 8）', () => {
    const oob = thread({
      thread_id: 'oob',
      status: 'open',
      anchor: { block_id: 'b1', start_offset: 0, end_offset: 999 },
      anchor_status: 'anchored',
    })
    const groups = sidebarGroups([oob], [])
    expect(groups.open.map(t => t.thread_id)).toEqual(['oob'])
    expect(groups.orphaned).toHaveLength(0)
    // 同一条线程被降级判据认出来 —— 降级与失锚是两回事。
    expect(degradedThreadIds('abc', [{ threadId: 'oob', start: 0, end: 999 }])).toEqual(['oob'])
  })

  it('四组判据两两互斥，任一线程恰好落入一组', () => {
    const list = [
      thread({ thread_id: 'o', status: 'open' }),
      thread({ thread_id: 'a', status: 'answered' }),
      thread({ thread_id: 'r', status: 'resolved' }),
      thread({ thread_id: 'd', status: 'dismissed' }),
      thread({ thread_id: 'orph', status: 'answered', anchor_status: 'orphaned' }),
    ]
    const orphaned = list.filter(t => t.anchor_status === 'orphaned')
    const groups = sidebarGroups(list, orphaned)
    expect(groups.open.map(t => t.thread_id)).toEqual(['o'])
    expect(groups.answered.map(t => t.thread_id)).toEqual(['a'])
    expect(groups.closed.map(t => t.thread_id).sort()).toEqual(['d', 'r'])
    expect(groups.orphaned.map(t => t.thread_id)).toEqual(['orph'])
    const total = groups.open.length + groups.answered.length + groups.closed.length + groups.orphaned.length
    expect(total).toBe(list.length)
  })

  it('⭐ 失锚组原样渲染快照的 orphaned_threads，前端不二次过滤（§20 断言 5）', () => {
    // 快照给了两条：一条真失锚有 anchor、一条失锚但 anchor 为 null。
    const withAnchor = thread({ thread_id: 'o1', anchor_status: 'orphaned' })
    const withoutAnchor = thread({ thread_id: 'o2', anchor_status: 'orphaned', anchor: null })
    const groups = sidebarGroups([], [withAnchor, withoutAnchor])
    // 变异提示：加一道 `.filter(t => t.anchor?.block_id)` ⇒ 只剩一条，本条转红。
    expect(groups.orphaned).toHaveLength(2)
  })

  it('快照未就绪（orphanedThreads 为 undefined）时按 anchor_status 从 threads 派生', () => {
    const list = [thread({ thread_id: 'x', anchor_status: 'orphaned' }), thread({ thread_id: 'y' })]
    const groups = sidebarGroups(list)
    expect(groups.orphaned.map(t => t.thread_id)).toEqual(['x'])
    expect(groups.open.map(t => t.thread_id)).toEqual(['y'])
  })

  it('组内排序：severity（blocker → warning → info → 无）→ created_at 升序', () => {
    const list = [
      thread({ thread_id: 'none', severity: '', created_at: '2026-01-01T00:00:00Z' }),
      thread({ thread_id: 'info', severity: 'info', created_at: '2026-01-01T00:00:00Z' }),
      thread({ thread_id: 'warn', severity: 'warning', created_at: '2026-01-01T00:00:00Z' }),
      thread({ thread_id: 'blk2', severity: 'blocker', created_at: '2026-01-02T00:00:00Z' }),
      thread({ thread_id: 'blk1', severity: 'blocker', created_at: '2026-01-01T00:00:00Z' }),
    ]
    expect(sidebarGroups(list, []).open.map(t => t.thread_id)).toEqual([
      'blk1',
      'blk2',
      'warn',
      'info',
      'none',
    ])
  })

  it('非数组入参恒不抛', () => {
    const groups = sidebarGroups(null as unknown as BlueprintThreadDetail[])
    expect(groups).toEqual({ open: [], answered: [], closed: [], orphaned: [] })
  })
})

describe('sidebarKindGroups —— 按 kind 分四组 + status→severity→created_at 排序', () => {
  it('四 kind 各一条 ⇒ 各组恰一条', () => {
    const list = [
      thread({ thread_id: 'k1', kind: 'ai_clarification' }),
      thread({ thread_id: 'k2', kind: 'ai_review_finding' }),
      thread({ thread_id: 'k3', kind: 'human_comment' }),
      thread({ thread_id: 'k4', kind: 'repo_confirmation' }),
    ]
    const groups = sidebarKindGroups(list, [])
    expect(groups.ai_clarification.map(t => t.thread_id)).toEqual(['k1'])
    expect(groups.ai_review_finding.map(t => t.thread_id)).toEqual(['k2'])
    expect(groups.human_comment.map(t => t.thread_id)).toEqual(['k3'])
    expect(groups.repo_confirmation.map(t => t.thread_id)).toEqual(['k4'])
  })

  it('只有部分 kind 时其余组为空数组', () => {
    const groups = sidebarKindGroups([thread({ thread_id: 'only', kind: 'human_comment' })], [])
    expect(groups.human_comment).toHaveLength(1)
    expect(groups.ai_clarification).toEqual([])
    expect(groups.ai_review_finding).toEqual([])
    expect(groups.repo_confirmation).toEqual([])
  })

  it('⭐ 排序：open 恒在 answered 前（即便 answered 创建更早），closed 排最后', () => {
    const list = [
      thread({ thread_id: 'ans', status: 'answered', created_at: '2026-01-01T00:00:00Z' }),
      thread({ thread_id: 'dis', status: 'dismissed', created_at: '2026-01-01T00:00:00Z' }),
      thread({ thread_id: 'opn', status: 'open', created_at: '2026-06-01T00:00:00Z' }),
      thread({ thread_id: 'res', status: 'resolved', created_at: '2026-01-02T00:00:00Z' }),
    ]
    expect(sidebarKindGroups(list, []).ai_clarification.map(t => t.thread_id)).toEqual([
      'opn',
      'ans',
      'dis',
      'res',
    ])
  })

  it('同 status 内：blocker 排 warning 前，同 severity 按 created_at 升序', () => {
    const list = [
      thread({ thread_id: 'w1', kind: 'ai_review_finding', status: 'open', severity: 'warning', created_at: '2026-01-01T00:00:00Z' }),
      thread({ thread_id: 'b2', kind: 'ai_review_finding', status: 'open', severity: 'blocker', created_at: '2026-01-02T00:00:00Z' }),
      thread({ thread_id: 'b1', kind: 'ai_review_finding', status: 'open', severity: 'blocker', created_at: '2026-01-01T00:00:00Z' }),
    ]
    expect(sidebarKindGroups(list, []).ai_review_finding.map(t => t.thread_id)).toEqual([
      'b1',
      'b2',
      'w1',
    ])
  })

  it('⭐ 失锚并组：失锚线程进自己的 kind 组，且同 id 全量只出现一次（threads 里不另占坑）', () => {
    const orphan = thread({ thread_id: 'orph', kind: 'ai_clarification', status: 'open', anchor_status: 'orphaned' })
    const groups = sidebarKindGroups([orphan, thread({ thread_id: 'plain', kind: 'human_comment' })], [orphan])
    expect(groups.ai_clarification.map(t => t.thread_id)).toEqual(['orph'])
    const total = groups.ai_clarification.length + groups.ai_review_finding.length
      + groups.human_comment.length + groups.repo_confirmation.length
    expect(total).toBe(2)
  })

  it('orphanedThreads 为 undefined 时从 threads 按 anchor_status 派生', () => {
    const list = [
      thread({ thread_id: 'x', kind: 'ai_review_finding', anchor_status: 'orphaned' }),
      thread({ thread_id: 'y', kind: 'ai_review_finding' }),
    ]
    const groups = sidebarKindGroups(list)
    expect(groups.ai_review_finding.map(t => t.thread_id).sort()).toEqual(['x', 'y'])
    expect(groups.ai_review_finding).toHaveLength(2)
  })

  it('非数组入参恒不抛，四组皆空数组', () => {
    const groups = sidebarKindGroups(null as unknown as BlueprintThreadDetail[])
    expect(groups).toEqual({
      ai_clarification: [],
      ai_review_finding: [],
      human_comment: [],
      repo_confirmation: [],
    })
  })
})

describe('groupThreadsByBlock —— 只收 anchored 且有 block_id 的线程', () => {
  it('anchor === null 与 block_id 不匹配的线程都不进 block 分组', () => {
    const grouped = groupThreadsByBlock([
      thread({ thread_id: 'in', anchor: { block_id: 'b1', start_offset: 0, end_offset: 1 } }),
      thread({ thread_id: 'nullAnchor', anchor: null }),
      thread({ thread_id: 'other', anchor: { block_id: 'b2', start_offset: 0, end_offset: 1 } }),
      thread({ thread_id: 'orph', anchor_status: 'orphaned' }),
    ])
    expect(Object.keys(grouped).sort()).toEqual(['b1', 'b2'])
    expect(grouped.b1.map(t => t.thread_id)).toEqual(['in'])
    expect(grouped.b2.map(t => t.thread_id)).toEqual(['other'])
  })

  it('失锚线程正文不渲染 ⇒ 即便有 block_id 也不进分组', () => {
    const orph = thread({
      thread_id: 'orph',
      anchor_status: 'orphaned',
      anchor: { block_id: 'b1', start_offset: 0, end_offset: 1 },
    })
    expect(groupThreadsByBlock([orph])).toEqual({})
  })
})

describe('annotationCounts —— 侧栏三个计数', () => {
  it('待澄清只数 anchored 的 open ai_clarification；失锚计数取失锚组', () => {
    const list = [
      thread({ thread_id: 'b1', kind: 'ai_review_finding', severity: 'blocker', blocking: true }),
      thread({ thread_id: 'c1', kind: 'ai_clarification' }),
      thread({ thread_id: 'o1', anchor_status: 'orphaned' }),
    ]
    expect(annotationCounts(sidebarGroups(list, [thread({ thread_id: 'o1', anchor_status: 'orphaned' })]), list)).toEqual({
      unresolvedBlocker: 1,
      pendingClarification: 1,
      orphaned: 1,
      total: 3,
    })
  })

  /**
   * ⭐ UI-REVIEW M-1：`total` 是**四组之和**，⛔ 不是三个语义计数相加。
   *
   * 三个语义计数口径不正交（`unresolvedBlocker` 含失锚、`pendingClarification` 排除失锚），
   * 相加会**重复计数**失锚的未决 blocker，又**漏计**人工评论 / 已作答 / 已关闭线程。
   */
  it('⭐ total == 四组之和：既不重复计失锚 blocker，也不漏计已作答/已关闭/人工评论', () => {
    const orphanedBlocker = thread({
      thread_id: 'ob',
      kind: 'ai_review_finding',
      severity: 'blocker',
      status: 'open',
      anchor_status: 'orphaned',
    })
    const list = [
      orphanedBlocker,
      thread({ thread_id: 'hc', kind: 'human_comment', status: 'open' }),
      thread({ thread_id: 'an', kind: 'ai_clarification', status: 'answered' }),
      thread({ thread_id: 'rs', kind: 'ai_review_finding', severity: 'warning', status: 'resolved' }),
    ]
    const groups = sidebarGroups(list, [orphanedBlocker])
    const result = annotationCounts(groups, list)

    // 四条线程 ⇒ 总数就是 4（每条恰好落进一组）。
    expect(result.total).toBe(4)
    // 非恒真对照：老口径（三者相加）会算成 1 + 0 + 1 = 2 —— 与 4 不同才证明这条断言有效。
    expect(result.unresolvedBlocker + result.pendingClarification + result.orphaned).not.toBe(result.total)
  })

  it('⭐ total 与侧栏四组条目数逐一对齐（四组互斥且穷尽）', () => {
    const list = [
      thread({ thread_id: 'a', status: 'open' }),
      thread({ thread_id: 'b', status: 'answered' }),
      thread({ thread_id: 'c', status: 'dismissed' }),
    ]
    const groups = sidebarGroups(list)
    const sum = groups.open.length + groups.answered.length + groups.closed.length + groups.orphaned.length
    expect(annotationCounts(groups, list).total).toBe(sum)
    expect(annotationCounts(groups, list).total).toBe(list.length)
  })
})

/**
 * ⭐ MJ-03 回归：未决 BLOCKER 的判据必须与后端 confirm 闸**逐字同口径**。
 *
 * 后端是三条 AND（`blueprint_lifecycle_service.py:441-446`）：
 * `kind=ai_review_finding` + `severity=blocker` + `status ∈ {open, answered}`
 * —— **既不看 `blocking`、也不看 `anchor_status`**。
 *
 * 口径不一致的后果不是「数字差一点」：顶栏说「0 条未决」，用户去点「确认」必吃 409。
 * 信息面在鼓励用户按一个注定失败的按钮。
 */
describe('isUnresolvedBlocker —— 与后端 confirm 闸同口径（MJ-03）', () => {
  const counts = (list: BlueprintThreadDetail[]) =>
    annotationCounts(sidebarGroups(list), list).unresolvedBlocker

  it('⭐ 失锚（orphaned）的 open BLOCKER 仍然计入 —— 失锚是锚定维度，与挡不挡确认正交', () => {
    const orphaned = thread({
      thread_id: 'f1',
      kind: 'ai_review_finding',
      severity: 'blocker',
      status: 'open',
      blocking: true,
      anchor_status: 'orphaned',
    })
    expect(isUnresolvedBlocker(orphaned)).toBe(true)
    expect(counts([orphaned])).toBe(1)
  })

  it('⭐ 已作答（answered）的 BLOCKER 仍然计入 —— 后端把 answered 明确算作未决', () => {
    const answered = thread({
      thread_id: 'f2',
      kind: 'ai_review_finding',
      severity: 'blocker',
      status: 'answered',
    })
    expect(isUnresolvedBlocker(answered)).toBe(true)
    expect(counts([answered])).toBe(1)
  })

  it('blocking=false 的 BLOCKER finding 仍然计入 —— 后端判据里没有这一项', () => {
    expect(counts([thread({
      thread_id: 'f3',
      kind: 'ai_review_finding',
      severity: 'blocker',
      status: 'open',
      blocking: false,
    })])).toBe(1)
  })

  it.each([
    ['已处置（resolved）', { status: 'resolved' as const }],
    ['已忽略（dismissed）', { status: 'dismissed' as const }],
    ['非 blocker 严重度', { severity: 'warning' as const }],
    ['非 finding 通道（澄清）', { kind: 'ai_clarification' as const }],
    ['非 finding 通道（人工评论）', { kind: 'human_comment' as const }],
  ])('对照（非恒真）：%s ⇒ 不计入', (_label, overrides) => {
    const base = {
      kind: 'ai_review_finding',
      severity: 'blocker',
      status: 'open',
      blocking: true,
    } satisfies Partial<BlueprintThreadDetail>
    const one = thread({ thread_id: 'f4', ...base, ...overrides })
    expect(isUnresolvedBlocker(one)).toBe(false)
    expect(counts([one])).toBe(0)
  })
})

describe('hasAnchorLocator —— 第三态识别', () => {
  it.each([
    [null, false],
    [undefined, false],
    [{}, false],
    [{ block_id: '' }, false],
    [{ block_id: 'b1' }, true],
  ])('%j → %s', (anchor, expected) => {
    expect(hasAnchorLocator(anchor as never)).toBe(expected)
  })
})
