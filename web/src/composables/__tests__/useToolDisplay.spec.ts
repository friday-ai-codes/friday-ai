/**
 * useToolDisplay 单元测试：聚焦「仓库名称而非裸 UUID」的展示逻辑（诉求 2/3）。
 */
import { describe, expect, it } from 'vitest'
import {
  collectRepoNames,
  humanizeDuration,
  relevanceCandidates,
  repoInitial,
  searchedRepoLabel,
  TOOL_ICONS,
  TOOL_LABELS,
  toolAction,
  toolIcon,
  toolLabel,
} from '~/composables/useToolDisplay'

const RELEVANCE_RESULT = JSON.stringify({
  data: {
    candidates: [
      { repository_id: 'uuid-a', repository_name: 'example-app', score: 0.82, level: 'high', evidence: '命中 2 个文件' },
      { repository_id: 'uuid-b', repository_name: 'question-bank', score: 0.55, level: 'medium', evidence: '语义相关' },
    ],
    threshold: 0.5,
  },
})

describe('useToolDisplay', () => {
  it('toolLabel 去除 mcp__ 前缀并映射中文', () => {
    expect(toolLabel('mcp__chat-tools__search_repository_code')).toBe('RAG 代码检索')
    expect(toolLabel('analyze_repository_relevance')).toBe('仓库分级路由')
    expect(toolLabel('find_related_code')).toBe('关联代码查找召回')
  })

  it('relevanceCandidates 解析 {data:{candidates}} 结构', () => {
    const cands = relevanceCandidates(RELEVANCE_RESULT)
    expect(cands).toHaveLength(2)
    expect(cands[0]).toMatchObject({ id: 'uuid-a', name: 'example-app', level: 'high' })
  })

  it('collectRepoNames 从相关性结果抽取 id→name', () => {
    const map = collectRepoNames('analyze_repository_relevance', {}, RELEVANCE_RESULT)
    expect(map).toEqual({ 'uuid-a': 'example-app', 'uuid-b': 'question-bank' })
  })

  it('collectRepoNames 从 coding plan 推荐仓库抽取 id→name', () => {
    const result = JSON.stringify({ recommended_repositories: [{ id: 'uuid-c', name: 'web' }] })
    expect(collectRepoNames('create_coding_plan', {}, result)).toEqual({ 'uuid-c': 'web' })
  })

  it('searchedRepoLabel：指定 repository_id → 仓库名称', () => {
    expect(searchedRepoLabel({ repository_id: 'uuid-a' }, { 'uuid-a': 'example-app' })).toBe('example-app')
  })

  it('searchedRepoLabel：无 repository_id（全空间）→ 全部仓库', () => {
    expect(searchedRepoLabel({}, {})).toBe('全部仓库')
  })

  it('searchedRepoLabel：拿不到名称时退化为短 id（不暴露整段 UUID）', () => {
    const label = searchedRepoLabel({ repository_id: 'abcdef0123456789' }, {})
    expect(label).toBe('abcdef01…')
  })

  it('toolAction(search)：把 repository_id 渲染成仓库名称 + 点明 RAG 检索', () => {
    const action = toolAction(
      'search_repository_code',
      { query: 'entrance', repository_id: 'uuid-a' },
      'ok',
      { 'uuid-a': 'example-app' },
    )
    expect(action).toContain('example-app')
    expect(action).toContain('entrance')
    expect(action).toContain('RAG')
    expect(action).not.toContain('uuid-a')
  })

  it('toolAction(find_related_code)：点明关联代码查找召回 + 锚点符号', () => {
    expect(toolAction('find_related_code', { symbol_name: 'UserService' })).toBe('关联代码查找召回：UserService')
    expect(toolAction('find_related_code', {})).toBe('关联代码查找召回')
  })

  it('toolAction(relevance)：摘要列出关联到的仓库名称', () => {
    const action = toolAction('analyze_repository_relevance', { query: 'entrance' }, RELEVANCE_RESULT)
    expect(action).toContain('example-app')
    expect(action).toContain('question-bank')
  })

  it('humanizeDuration 中文人性化时长', () => {
    expect(humanizeDuration(0)).toBe('')
    expect(humanizeDuration(0.4)).toBe('不到 1 秒')
    expect(humanizeDuration(8)).toBe('8 秒')
    expect(humanizeDuration(90)).toBe('1 分 30 秒')
    expect(humanizeDuration(120)).toBe('2 分')
  })

  it('repoInitial 取仓库名首字符大写', () => {
    expect(repoInitial('example-app')).toBe('E')
    expect(repoInitial('')).toBe('?')
  })

  // ---------------------------------------------------------------------------
  // 109-04：编排工具三处登记（label / icon / action）。缺任一处用户就看不出
  // 这一步做了什么 —— 摘要会落到 default 分支，产出裸入参串。
  // ---------------------------------------------------------------------------
  describe('编排工具登记（start_plan_research / start_feature_solution）', () => {
    it('label 登记：两个工具各有中文标签（含 mcp__ 前缀形态）', () => {
      expect(TOOL_LABELS.start_plan_research).toBe('方案编排调研')
      expect(TOOL_LABELS.start_feature_solution).toBe('功能方案编排')
      expect(toolLabel('mcp__chat-tools__start_plan_research')).toBe('方案编排调研')
      expect(toolLabel('start_feature_solution')).toBe('功能方案编排')
    })

    it('icon 登记：两个工具均为 workflow 图标', () => {
      expect(TOOL_ICONS.start_plan_research).toBe('icon-[lucide--workflow]')
      expect(TOOL_ICONS.start_feature_solution).toBe('icon-[lucide--workflow]')
      expect(toolIcon('mcp__chat-tools__start_feature_solution')).toBe('icon-[lucide--workflow]')
    })

    it('toolAction 终态分支：status=done → 跨仓方案编排已完成', () => {
      const done = JSON.stringify({
        session_id: 's1',
        artifact_version_id: 'av-1',
        status: 'done',
        message: '跨仓方案编排已完成，已产出技术方案产物（ArtifactVersion）。',
      })
      expect(toolAction('start_plan_research', { requirement: '做个东西' }, done))
        .toBe('跨仓方案编排已完成')
      expect(toolAction('mcp__chat-tools__start_feature_solution', {}, done))
        .toBe('跨仓方案编排已完成')
    })

    it('toolAction 在途分支：__blocking_task__ → 方案编排调研进行中，且不回显后端 placeholder', () => {
      const placeholder = '已发起跨仓方案编排调研（session=s1，状态=waiting_event）；深入调研容器运行中，调研完成后将自动融合并返回 canonical 主方案。'
      const blocking = JSON.stringify({
        __blocking_task__: true,
        task_type: 'plan_research',
        task_id: 's1',
        session_id: 's1',
        params: { session_id: 's1' },
        placeholder,
      })
      for (const name of ['start_plan_research', 'start_feature_solution']) {
        const action = toolAction(name, { requirement: '做个东西' }, blocking)
        expect(action).toBe('方案编排调研进行中')
        // 后端自由文本不得进渲染路径
        expect(action).not.toContain('已发起')
        expect(action).not.toContain('容器')
        expect(action).not.toContain('session=')
      }
    })

    it('toolAction 兜底分支：无 result → 回退截断后的需求文本', () => {
      expect(toolAction('start_plan_research', { requirement: '打通编排产出到编码执行' }))
        .toBe('编排「打通编排产出到编码执行」')
      // 需求缺失 → 回退工具标签，而非 default 分支的裸入参串
      expect(toolAction('start_feature_solution', { space_id: 7 }))
        .toBe('功能方案编排')
    })
  })
})
