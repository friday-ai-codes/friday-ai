/**
 * blueprintBlocks.ts 契约单测（Phase 115-02，形态照 `utils/__tests__/variableRef.test.ts`）。
 *
 * 这一层锁的是**前后端坐标系同源**的三条硬约束，任一被改回错误形态都必须转红：
 * 1. `blockText` 的四分支字段优先级（P-13）——头号靶子，错了不报错只圈错字；
 * 2. `iterBlocks` 的 13 处 collect 与「四段不走查」（P-14）；
 * 3. `canonicalBlockFingerprint` 的递归键排序（No Analog #6）。
 */
import { describe, expect, it } from 'vitest'
import {
  blockText,
  BLUEPRINT_EVENT_NAMES,
  BLUEPRINT_STAGES,
  buildStageTimeline,
  canonicalBlockFingerprint,
  classifyBlockDiff,
  itemKey,
  iterBlocks,
  progressKeyForEvent,
  sectionKeyForEvent,
  stageForEvent,
  summaryText,
  timelineIndexOfSessionStage,
} from '../blueprintBlocks'

describe('blockText —— 四分支字段优先级（P-13）', () => {
  // 期望值按后端 `blueprint_anchor.py:34-64` `_block_text` 的实现逐行推导：
  //   ① text 是非空 str → 直取
  //   ② text 是 list → "\n".join(str(item))
  //   ③ code.source 是非空 str → 取它
  //   ④ rows 是 list → 逐行（行是 list 则逐格）str() 扁平后 "\n".join
  //   ⑤ 其余 → ""
  it('paragraph：非空 text 直取', () => {
    expect(blockText({ block_id: 'b1', type: 'paragraph', text: '第一段正文' })).toBe('第一段正文')
  })

  it('list：数组 text 逐条 \\n 连接（后端 "\\n".join(str(item))）', () => {
    expect(blockText({ block_id: 'b2', type: 'list', text: ['甲', '乙', '丙'] })).toBe('甲\n乙\n丙')
  })

  it('⭐ pseudocode 同时带非空 text 与 code.source ⇒ 取 text，不取 code.source', () => {
    // ⚠️ 变异提示：若把实现改成按 `block.type` 分派（pseudocode → code.source），本条即转红。
    // schema 对 `text` 无任何类型约束 ⇒ 这个组合完全合法，而后端取的是 text。
    const block = {
      block_id: 'b3',
      type: 'pseudocode' as const,
      text: '这段伪代码的自然语言说明',
      code: { language: 'python', source: 'def f():\n    pass' },
    }
    expect(blockText(block)).toBe('这段伪代码的自然语言说明')
    expect(blockText(block)).not.toBe('def f():\n    pass')
  })

  it('pseudocode 只有 code.source ⇒ 取 code.source', () => {
    expect(blockText({ block_id: 'b4', type: 'pseudocode', code: { source: 'x = 1' } })).toBe('x = 1')
  })

  it('table：两行三列逐格扁平后 \\n 连接', () => {
    const block = { block_id: 'b5', type: 'table' as const, rows: [['a', 'b', 'c'], ['d', 'e', 'f']] }
    expect(blockText(block)).toBe('a\nb\nc\nd\ne\nf')
  })

  it('table：非数组的行整行 str()（后端 else 分支）', () => {
    expect(blockText({ block_id: 'b6', type: 'table', rows: ['整行' as unknown as string[], ['x']] })).toBe('整行\nx')
  })

  it('空块 / 空字符串 text / 非 dict 一律得空串', () => {
    expect(blockText({ block_id: 'b7', type: 'paragraph' })).toBe('')
    expect(blockText({ block_id: 'b8', type: 'paragraph', text: '' })).toBe('')
    expect(blockText({ block_id: 'b9', type: 'list', text: [] })).toBe('')
    expect(blockText(null)).toBe('')
    expect(blockText('不是块')).toBe('')
  })

  it('text 是空字符串但 code.source 非空 ⇒ 落到 code.source（「非空」判据不可省）', () => {
    expect(blockText({ block_id: 'b10', type: 'pseudocode', text: '', code: { source: 'y' } })).toBe('y')
  })
})

/** 一份把 13 处 collect 全部填满的 content（每处一个块，`block_id` 用序号便于断言）。 */
function fullContent(): Record<string, unknown> {
  const blk = (id: string, text: string) => [{ block_id: id, type: 'paragraph', text }]
  return {
    schema_version: 'blueprint/v1',
    meta: { title: 'T', project_id: 'p', summary: blk('m1', '摘要') },
    requirement_spec: {
      goal: blk('r1', '目标'),
      background: blk('r2', '背景'),
      feature_points: [{ id: 'fp_01', title: 'F', intent: 'greenfield', description: blk('r3', '功能点') }],
    },
    repo_associations: [{
      repository_id: 'repo_a',
      repository_name: 'A',
      role: 'direct',
      rationale: { text: blk('a1', '理由') },
      responsibility: blk('a2', '职责'),
      fitness: { reasons: blk('a3', '适配依据') },
      planned_change_summary: blk('a4', '计划改动'),
      support_needed: blk('a5', '需要支撑'),
    }],
    current_state_analysis: [{
      repository_id: 'repo_a',
      summary: blk('c1', '现状摘要'),
      findings: [{ id: 'find_01', text: blk('c2', '发现'), kind: 'gap', citations: [] }],
    }],
    implementation_overview: {
      requirement_narrative: blk('i1', '需求叙述'),
      modules: [{ id: 'mod_01', narrative: blk('i2', '模块叙述') }],
      items: [{
        id: 'impl_01',
        feature_point_id: 'fp_01',
        repository_id: 'repo_a',
        change_type: 'create',
        title: 'X',
        how: blk('i3', '怎么做'),
        existing_integration: blk('i4', '既有整合'),
        test_strategy: blk('i5', '测试策略'),
      }],
    },
    api_contracts: [{
      id: 'api_01',
      name: 'N',
      kind: 'http',
      direction: 'provided',
      description: blk('p1', '接口说明'),
      data_source: { notes: blk('p2', '数据来源说明') },
    }],
    impact_analysis: {
      business_impact: blk('x1', '业务影响'),
      affected_features: [{ feature: 'feat_a', kind: 'compat', description: blk('x2', '受影响说明') }],
      compat_risks: blk('x3', '兼容风险'),
      rollback_plan: blk('x4', '回滚'),
    },
    interaction_flows: [{
      id: 'flow_01',
      name: 'F',
      steps: [{ seq: 1, actor: 'user', action: 'click', note: blk('f1', '步骤说明') }],
    }],
    must_haves: { truths: [], artifacts: [], key_links: [] },
    citations: {},
  }
}

describe('iterBlocks —— 13 处 collect 逐段对齐后端 iter_blocks', () => {
  it('全填的 content 产出 23 个块，sectionPath 逐条与后端拼法一致', () => {
    const results = iterBlocks(fullContent())
    expect(results.map(r => r.sectionPath)).toEqual([
      'meta.summary',
      'requirement_spec.goal',
      'requirement_spec.background',
      'requirement_spec.feature_points[fp_01].description',
      'repo_associations[repo_a].rationale.text',
      'repo_associations[repo_a].responsibility',
      'repo_associations[repo_a].fitness.reasons',
      'repo_associations[repo_a].planned_change_summary',
      'repo_associations[repo_a].support_needed',
      'current_state_analysis[repo_a].summary',
      'current_state_analysis[repo_a].findings[find_01].text',
      'implementation_overview.requirement_narrative',
      'implementation_overview.modules[mod_01].narrative',
      'implementation_overview.items[impl_01].how',
      'implementation_overview.items[impl_01].existing_integration',
      'implementation_overview.items[impl_01].test_strategy',
      'api_contracts[api_01].description',
      'api_contracts[api_01].data_source.notes',
      'impact_analysis.business_impact',
      'impact_analysis.affected_features[feat_a].description',
      'impact_analysis.compat_risks',
      'impact_analysis.rollback_plan',
      'interaction_flows[flow_01].steps[1].note',
    ])
  })

  it('⭐ must_haves / decision_log / deferred_ideas / execution_plan 填满也不被走查（P-14）', () => {
    const content = fullContent()
    const stray = [{ block_id: 'STRAY', type: 'paragraph', text: '不该被走查到' }]
    content.must_haves = { truths: ['t'], artifacts: stray, key_links: stray }
    content.decision_log = stray
    content.deferred_ideas = stray
    content.execution_plan = stray
    const ids = iterBlocks(content).map(r => r.block.block_id)
    expect(ids).not.toContain('STRAY')
    expect(ids).toHaveLength(23)
  })

  it('缺标识字段的条目回退位置下标字符串化（_item_key 同款）', () => {
    const content = {
      requirement_spec: {
        goal: [],
        feature_points: [
          { title: '无 id', description: [{ block_id: 'z1', type: 'paragraph', text: 'q' }] },
        ],
      },
    }
    expect(iterBlocks(content)[0].sectionPath).toBe('requirement_spec.feature_points[0].description')
  })

  it('只收带非空 block_id 的 dict，非法条目静默跳过且不抛', () => {
    const content = {
      meta: { summary: [{ type: 'paragraph', text: '无 id' }, { block_id: '', text: '空 id' }, 'not-a-dict'] },
    }
    expect(iterBlocks(content)).toEqual([])
    expect(iterBlocks(null)).toEqual([])
    expect(iterBlocks('x')).toEqual([])
  })

  it('sectionKey 归到十段之一，供批注按段汇总', () => {
    const bySection = new Set(iterBlocks(fullContent()).map(r => r.sectionKey))
    expect(bySection).toEqual(new Set([
      'meta',
      'requirement_spec',
      'repo_associations',
      'current_state_analysis',
      'implementation_overview',
      'api_contracts',
      'impact_analysis',
      'interaction_flows',
    ]))
  })

  it('itemKey：空串 / null / undefined 都回退下标', () => {
    expect(itemKey({ id: 'x' }, 'id', 3)).toBe('x')
    expect(itemKey({ id: '' }, 'id', 3)).toBe('3')
    expect(itemKey({ id: null }, 'id', 3)).toBe('3')
    expect(itemKey({}, 'id', 3)).toBe('3')
    expect(itemKey({ seq: 0 }, 'seq', 7)).toBe('0')
  })
})

describe('canonicalBlockFingerprint —— 递归排序键（No Analog #6）', () => {
  it('⭐ 同一对象两种键序 ⇒ 同一指纹', () => {
    const a = { block_id: 'b', type: 'paragraph', text: 'x' }
    const b = { text: 'x', type: 'paragraph', block_id: 'b' }
    expect(canonicalBlockFingerprint(a)).toBe(canonicalBlockFingerprint(b))
  })

  it('嵌套 dict 与数组内的 dict 同样生效', () => {
    const a = { block_id: 'b', code: { language: 'py', source: 's' }, citations: [{ x: 1, y: 2 }] }
    const b = { citations: [{ y: 2, x: 1 }], code: { source: 's', language: 'py' }, block_id: 'b' }
    expect(canonicalBlockFingerprint(a)).toBe(canonicalBlockFingerprint(b))
  })

  it('值不同 ⇒ 指纹不同；数组顺序不同 ⇒ 指纹不同（顺序是内容的一部分）', () => {
    expect(canonicalBlockFingerprint({ a: 1 })).not.toBe(canonicalBlockFingerprint({ a: 2 }))
    expect(canonicalBlockFingerprint({ a: [1, 2] })).not.toBe(canonicalBlockFingerprint({ a: [2, 1] }))
  })
})

describe('classifyBlockDiff —— 三分类 + 按段分组', () => {
  const base = {
    meta: { summary: [{ block_id: 'keep', type: 'paragraph', text: '不变' }] },
    requirement_spec: {
      goal: [{ block_id: 'gone', type: 'paragraph', text: '将被删' }],
      feature_points: [],
    },
    impact_analysis: {
      business_impact: [{ block_id: 'edit', type: 'paragraph', text: '旧文' }],
      affected_features: [],
    },
  }
  const target = {
    meta: { summary: [{ type: 'paragraph', block_id: 'keep', text: '不变' }] },
    requirement_spec: {
      goal: [{ block_id: 'fresh', type: 'paragraph', text: '新增' }],
      feature_points: [],
    },
    impact_analysis: {
      business_impact: [{ block_id: 'edit', type: 'paragraph', text: '新文' }],
      affected_features: [],
    },
  }

  it('added / removed / modified 各一条', () => {
    const diff = classifyBlockDiff(base, target)
    expect(diff.added).toEqual(['fresh'])
    expect(diff.removed).toEqual(['gone'])
    expect(diff.modified).toEqual(['edit'])
  })

  it('⭐ 键序不同但内容相同 ⇒ 不算 modified（上一条的下游证伪）', () => {
    // `keep` 在两版里键序刻意不同（block_id/type 互换）；若指纹不做 canonical 化即转红。
    expect(classifyBlockDiff(base, target).modified).not.toContain('keep')
  })

  it('按段分组，供未变化的段整段折叠', () => {
    const { bySection } = classifyBlockDiff(base, target)
    expect(bySection.requirement_spec).toEqual({ added: ['fresh'], removed: ['gone'], modified: [] })
    expect(bySection.impact_analysis).toEqual({ added: [], removed: [], modified: ['edit'] })
    expect(bySection.meta).toBeUndefined()
  })
})

describe('sectionKeyForEvent —— 21 事件穷举（UI-SPEC §8.1 逐行）', () => {
  const CASES: Array<[string, string[]]> = [
    ['blueprint.status.transitioned', []],
    ['blueprint.stage.started', []],
    ['blueprint.stage.completed', []],
    ['blueprint.stage.failed', []],
    ['blueprint.spec_gate.scored', ['requirement_spec']],
    ['blueprint.spec_gate.clarification_asked', ['requirement_spec']],
    ['blueprint.spec_gate.locked', ['requirement_spec', 'decision_log']],
    ['blueprint.route.scored', ['repo_associations']],
    ['blueprint.repo_research.started', ['repo_associations', 'current_state_analysis']],
    ['blueprint.repo_research.completed', ['repo_associations', 'current_state_analysis']],
    ['blueprint.repo_research.failed', ['repo_associations', 'current_state_analysis']],
    ['blueprint.reroute.triggered', ['repo_associations']],
    ['blueprint.confirmation.opened', []],
    ['blueprint.confirmation.action', []],
    ['blueprint.confirmation.locked', []],
    ['blueprint.context.entry_appended', ['implementation_overview']],
    ['blueprint.context.waiter_registered', ['api_contracts']],
    ['blueprint.context.waiter_satisfied', ['api_contracts']],
    ['blueprint.review.started', []],
    ['blueprint.review.completed', []],
    ['blueprint.review.failed', []],
  ]

  it('恰好 21 个事件被登记（与后端 BLUEPRINT_EVENTS 同集）', () => {
    expect(BLUEPRINT_EVENT_NAMES).toHaveLength(21)
    expect(new Set(BLUEPRINT_EVENT_NAMES)).toEqual(new Set(CASES.map(([name]) => name)))
  })

  it.each(CASES)('%s → %j', (eventName, sections) => {
    expect(sectionKeyForEvent(eventName)).toEqual(sections)
  })

  it('恰好 5 个事件映射空数组（确认门三条 + 审查三条 + 状态/阶段四条里的…按表核算）', () => {
    const empty = CASES.filter(([, sections]) => sections.length === 0).map(([name]) => name)
    // 四条状态/阶段 + 三条确认门 + 三条审查 = 10 条不驱动段级进度，只喂阶段时间线。
    expect(empty).toHaveLength(10)
  })

  it('两个事件映射两段（repo_research 三条 + spec_gate.locked）', () => {
    const multi = CASES.filter(([, sections]) => sections.length === 2).map(([name]) => name)
    expect(multi).toEqual([
      'blueprint.spec_gate.locked',
      'blueprint.repo_research.started',
      'blueprint.repo_research.completed',
      'blueprint.repo_research.failed',
    ])
  })

  it('未知事件返回空数组，且返回的是副本（改它不污染映射表）', () => {
    expect(sectionKeyForEvent('blueprint.unknown.event')).toEqual([])
    const first = sectionKeyForEvent('blueprint.spec_gate.locked')
    first.push('污染')
    expect(sectionKeyForEvent('blueprint.spec_gate.locked')).toEqual(['requirement_spec', 'decision_log'])
  })

  it('每个已登记事件都有进度文案 key', () => {
    for (const name of BLUEPRINT_EVENT_NAMES)
      expect(progressKeyForEvent(name)).toMatch(/^knowledge\.blueprints\.progress\./)
    expect(progressKeyForEvent('blueprint.unknown.event')).toBe('')
  })
})

describe('stageForEvent —— 事件 → 阶段', () => {
  it.each([
    ['blueprint.spec_gate.scored', 'spec_gate'],
    ['blueprint.route.scored', 'route'],
    ['blueprint.reroute.triggered', 'route'],
    ['blueprint.repo_research.completed', 'repo_research'],
    ['blueprint.confirmation.locked', 'confirmation'],
    ['blueprint.context.entry_appended', 'repo_plan'],
    ['blueprint.context.waiter_satisfied', 'merge'],
    ['blueprint.review.started', 'ai_review'],
  ])('%s → %s', (eventName, stage) => {
    expect(stageForEvent(eventName)).toBe(stage)
  })

  it('状态/阶段四条与未知事件返回空串（它们不归任何 stage 节点）', () => {
    for (const name of [
      'blueprint.status.transitioned',
      'blueprint.stage.started',
      'blueprint.stage.completed',
      'blueprint.stage.failed',
      'blueprint.unknown.event',
    ])
      expect(stageForEvent(name)).toBe('')
  })
})

describe('summaryText —— 首个非空块的纯文本截断', () => {
  it('跳过空块取首个非空块', () => {
    const blocks = [
      { block_id: 'a', type: 'paragraph', text: '' },
      { block_id: 'b', type: 'paragraph', text: '真正的摘要' },
    ]
    expect(summaryText(blocks)).toBe('真正的摘要')
  })

  it('超长按 maxLen 截断并补省略号', () => {
    const long = 'x'.repeat(250)
    expect(summaryText([{ block_id: 'a', type: 'paragraph', text: long }], 200)).toBe(`${'x'.repeat(200)}…`)
  })

  it('非数组 / 全空 ⇒ 空串', () => {
    expect(summaryText(undefined)).toBe('')
    expect(summaryText([])).toBe('')
    expect(summaryText([{ block_id: 'a', type: 'paragraph' }])).toBe('')
  })
})

describe('buildStageTimeline —— 末态推断（MJ-02）', () => {
  let seq = 0
  const ev = (event: string, ts: string) => {
    seq += 1
    return { id: `e-${seq}`, event, ts, payload: {} } as never
  }
  const stateOf = (nodes: ReturnType<typeof buildStageTimeline>) =>
    Object.fromEntries(nodes.map(node => [node.stage, node.state]))

  it('⭐ 三个无终态出边的阶段靠位序到达 done（route / repo_plan / merge）', () => {
    const nodes = buildStageTimeline(
      [
        ev('blueprint.route.scored', '2026-08-01T00:00:01Z'),
        ev('blueprint.context.entry_appended', '2026-08-01T00:00:02Z'),
        ev('blueprint.context.waiter_satisfied', '2026-08-01T00:00:03Z'),
      ],
      'ai_review',
      'pending_review',
    )
    const states = stateOf(nodes)
    expect([states.route, states.repo_plan, states.merge]).toEqual(['done', 'done', 'done'])
    // 非恒真对照：位序**之后**的阶段没有事件 ⇒ 不得被判 done
    expect(states.pending_review).toBe('running')
  })

  it('编排终态（四值）把发过事件的阶段一律收成 done，failed / superseded 不在其列', () => {
    const events = [ev('blueprint.route.scored', '2026-08-01T00:00:01Z')]
    for (const status of ['confirmed', 'implementing', 'implemented', 'archived'])
      expect(stateOf(buildStageTimeline(events, '', status)).route).toBe('done')
    // 对照：失败 / 被取代不推断完成，否则等于把失败讲成成功
    for (const status of ['failed', 'superseded'])
      expect(stateOf(buildStageTimeline(events, '', status)).route).toBe('running')
  })

  it('⭐ pending_review 收敛前序 running 阶段（续驱中断留下的僵尸会话不得让规格门永远转圈）', () => {
    // 实测形状：会话事件流停在 clarification_asked（作答后的续驱被进程重启打断），
    // 蓝图却已由后续链路推到 pending_review ⇒ 规格门必须收成 done，而不是挂着「等待作答」。
    const states = stateOf(buildStageTimeline(
      [ev('blueprint.spec_gate.clarification_asked', '2026-08-01T00:00:01Z')],
      'spec_gate',
      'pending_review',
    ))
    expect(states.spec_gate).toBe('done')
    // 「待人类审查」节点本身仍点亮为进行中（等的是人，不是机器）
    expect(states.pending_review).toBe('running')
    // 非恒真对照：仍在等澄清（needs_clarification）时规格门必须保持 running
    const waiting = stateOf(buildStageTimeline(
      [ev('blueprint.spec_gate.clarification_asked', '2026-08-01T00:00:02Z')],
      'spec_gate',
      'needs_clarification',
    ))
    expect(waiting.spec_gate).toBe('running')
  })

  it('.failed 后缀优先于位序与终态推断', () => {
    const states = stateOf(buildStageTimeline(
      [ev('blueprint.repo_research.failed', '2026-08-01T00:00:01Z')],
      'ai_review',
      'confirmed',
    ))
    expect(states.repo_research).toBe('failed')
  })

  it('⭐ 会话 stage 名走别名表换算位序（两侧不同名）', () => {
    expect(timelineIndexOfSessionStage('repo_confirmation')).toBe(BLUEPRINT_STAGES.indexOf('confirmation'))
    expect(timelineIndexOfSessionStage('reroute')).toBe(BLUEPRINT_STAGES.indexOf('route'))
    // spec_gate 之前的准备 stage 与未知值一律 -1（位序规则整条不生效，而不是误判成 0）
    for (const raw of ['intake', 'decompose', '', 'nonsense'])
      expect(timelineIndexOfSessionStage(raw)).toBe(-1)
  })

  it('八个节点恒全量返回，顺序与 BLUEPRINT_STAGES 逐字一致', () => {
    expect(buildStageTimeline(undefined, '', '').map(node => node.stage)).toEqual([...BLUEPRINT_STAGES])
  })
})
