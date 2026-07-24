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
  toolAction,
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
    expect(repoInitial('example-app')).toBe('S')
    expect(repoInitial('')).toBe('?')
  })
})
