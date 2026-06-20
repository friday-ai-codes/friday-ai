import type { Ref } from 'vue'
/**
 * 知识能力聚合（低维 / 真实业务维度）
 *
 * 由全局知识树拿到仓库清单后，并行拉取每个仓库的能力树（`ai_summary_tree`：
 * 子应用 → 模块 → 能力，含 keywords），聚合成两种总览物料：
 * - 星图节点 / 连线：仓库 → 子应用 → 模块 → 能力 的真实业务网络（带预算上限）
 * - 词云词条：能力 / 模块标题 + 关键词（按出现频次加权）
 *
 * 相比业务域 / 分面（高度抽象），这里下钻到“具体能做什么”的业务粒度。
 */
import type { CapabilityNode, RepoCard } from '~/api/repoTree'
import { useQuery } from '@tanstack/vue-query'
import { computed } from 'vue'
import repoTreeApi from '~/api/repoTree'

export interface StarNode {
  id: string
  label: string
  val: number
  color: string
  group: 'repo' | 'sub_app' | 'module' | 'capability'
  repoId?: string
  /** 详情浮层用 */
  repoName?: string
  nodeType?: string
  summary?: string
  keywords?: string[]
  paths?: string[]
  /** 仓库内的祖先标题路径（不含仓库本身） */
  trail?: string[]
  /** 直接子项（标题 + 层级），用于详情浮层完整展示 */
  children?: { title: string, group: StarNode['group'] }[]
  /** 子孙能力总数 */
  descendantCount?: number
}

export interface StarLink {
  source: string
  target: string
  color: string
  flow: number
}

export interface CloudTerm {
  text: string
  weight: number
  /** title：业务能力/模块名；keyword：能力关键词 */
  kind: 'title' | 'keyword'
}

/** 全量搜索条目（不受星图节点预算限制，覆盖所有仓库 / 能力节点） */
export interface KnowledgeSearchItem {
  id: string
  kind: StarNode['group']
  title: string
  repoId: string
  repoName: string
  summary: string
  keywords: string[]
  trail: string[]
}

const LEVEL_COLOR: Record<StarNode['group'], string> = {
  repo: '#818cf8', // indigo-400
  sub_app: '#c084fc', // purple-400
  module: '#2dd4bf', // teal-400
  capability: '#fbbf24', // amber-400
}
const LEVEL_VAL: Record<StarNode['group'], number> = {
  repo: 9,
  sub_app: 5,
  module: 3.2,
  capability: 1.8,
}

// 星图节点预算：超出后停止深入（避免 3D 帧率劣化）
const NODE_BUDGET = 320

function nodeGroup(t: CapabilityNode['node_type']): StarNode['group'] {
  return t === 'sub_app' ? 'sub_app' : t === 'module' ? 'module' : 'capability'
}

function countDescendants(n: CapabilityNode): number {
  return (n.children ?? []).reduce((s, c) => s + 1 + countDescendants(c), 0)
}

function childSummaries(children: CapabilityNode[] | undefined): { title: string, group: StarNode['group'] }[] {
  return (children ?? []).map(c => ({ title: c.title, group: nodeGroup(c.node_type) }))
}

interface Aggregated {
  nodes: StarNode[]
  links: StarLink[]
  terms: CloudTerm[]
  items: KnowledgeSearchItem[]
  capabilityCount: number
}

function aggregate(
  trees: Array<{ repoId: string, name: string, overview: string, tree: CapabilityNode[] }>,
): Aggregated {
  const nodes: StarNode[] = []
  const links: StarLink[] = []
  const items: KnowledgeSearchItem[] = []
  const titleWeight = new Map<string, number>()
  const keywordWeight = new Map<string, number>()
  let capabilityCount = 0

  const bump = (map: Map<string, number>, key: string, by = 1) => {
    const k = key.trim()
    if (k)
      map.set(k, (map.get(k) ?? 0) + by)
  }

  for (const { repoId, name, overview, tree } of trees) {
    const repoNodeId = `repo:${repoId}`
    const repoHasBudget = nodes.length < NODE_BUDGET
    if (repoHasBudget) {
      nodes.push({
        id: repoNodeId,
        label: name,
        val: LEVEL_VAL.repo,
        color: LEVEL_COLOR.repo,
        group: 'repo',
        repoId,
        repoName: name,
        nodeType: 'repo',
        summary: overview,
        trail: [],
        children: childSummaries(tree),
        descendantCount: tree.reduce((s, n) => s + 1 + countDescendants(n), 0),
      })
    }
    // 仓库始终进入搜索索引
    items.push({
      id: repoNodeId,
      kind: 'repo',
      title: name,
      repoId,
      repoName: name,
      summary: overview,
      keywords: [],
      trail: [],
    })

    // BFS：始终遍历全部节点（搜索 / 词云需要全量）；仅入图受预算约束
    const queue: Array<{ node: CapabilityNode, parentId: string, trail: string[] }> = tree.map(n => ({
      node: n,
      parentId: repoNodeId,
      trail: [],
    }))
    while (queue.length) {
      const { node, parentId, trail } = queue.shift()!
      const group = nodeGroup(node.node_type)
      const id = `${repoId}:${node.node_id}`
      if (group === 'capability')
        capabilityCount++

      // 词云：标题 + 关键词（全量）
      bump(titleWeight, node.title, group === 'capability' ? 1 : 1.5)
      for (const kw of node.keywords ?? [])
        bump(keywordWeight, kw, 1)

      // 搜索索引（全量）
      items.push({
        id,
        kind: group,
        title: node.title,
        repoId,
        repoName: name,
        summary: node.summary ?? '',
        keywords: node.keywords ?? [],
        trail,
      })

      // 星图节点 / 连线（受预算约束；BFS 顺序保证父节点先入图，连线引用安全）
      if (nodes.length < NODE_BUDGET) {
        nodes.push({
          id,
          label: node.title,
          val: LEVEL_VAL[group],
          color: LEVEL_COLOR[group],
          group,
          repoId,
          repoName: name,
          nodeType: node.node_type,
          summary: node.summary,
          keywords: node.keywords ?? [],
          paths: node.paths ?? [],
          trail,
          children: childSummaries(node.children),
          descendantCount: countDescendants(node),
        })
        links.push({
          source: parentId,
          target: id,
          color: 'rgba(148,163,184,0.22)',
          flow: group === 'sub_app' ? 2 : 0,
        })
      }

      // 始终下钻
      const childTrail = [...trail, node.title]
      for (const child of node.children ?? [])
        queue.push({ node: child, parentId: id, trail: childTrail })
    }
  }

  const terms: CloudTerm[] = []
  for (const [text, weight] of titleWeight)
    terms.push({ text, weight: weight + 1, kind: 'title' })
  for (const [text, weight] of keywordWeight) {
    // 关键词与标题同名时不重复加入（标题优先）
    if (!titleWeight.has(text))
      terms.push({ text, weight, kind: 'keyword' })
  }

  return { nodes, links, terms, items, capabilityCount }
}

/**
 * @param repos    全局知识树返回的仓库卡片（用于筛 has_tree 与命名）
 * @param enabled  是否启用（通常等父查询就绪）
 */
export function useKnowledgeCapabilities(
  repos: Ref<RepoCard[]>,
  enabled: Ref<boolean>,
) {
  const treedRepos = computed(() => repos.value.filter(r => r.has_tree))
  const repoKey = computed(() => treedRepos.value.map(r => r.repo_id).sort().join(','))

  const query = useQuery({
    queryKey: computed(() => ['knowledge', 'capabilities', repoKey.value]),
    enabled: computed(() => enabled.value && treedRepos.value.length > 0),
    staleTime: 5 * 60_000,
    queryFn: async () => {
      const settled = await Promise.allSettled(
        treedRepos.value.map(async (r) => {
          const res = await repoTreeApi.getRepoIndexTree(r.repo_id)
          return {
            repoId: r.repo_id,
            name: res.name || r.name,
            overview: r.overview ?? '',
            tree: res.tree ?? [],
          }
        }),
      )
      const trees = settled
        .filter((s): s is PromiseFulfilledResult<{ repoId: string, name: string, overview: string, tree: CapabilityNode[] }> =>
          s.status === 'fulfilled')
        .map(s => s.value)
      return aggregate(trees)
    },
  })

  const nodes = computed<StarNode[]>(() => query.data.value?.nodes ?? [])
  const links = computed<StarLink[]>(() => query.data.value?.links ?? [])
  const terms = computed<CloudTerm[]>(() => query.data.value?.terms ?? [])
  const items = computed<KnowledgeSearchItem[]>(() => query.data.value?.items ?? [])
  const capabilityCount = computed(() => query.data.value?.capabilityCount ?? 0)
  const isLoading = computed(() => query.isLoading.value)
  const hasData = computed(() => nodes.value.length > 0 || terms.value.length > 0)

  return { nodes, links, terms, items, capabilityCount, isLoading, hasData }
}
