<script setup lang="ts">
/**
 * 知识树「力导向缩略图」总览（sigma + graphology + ForceAtlas2，浅色）
 *
 * 节点：业务域（含子域）+ 其下仓库；边：域→子域、域→仓库。
 * 点击域节点下钻进入该域；点击仓库节点直接打开其能力树。
 * 与 Galaxy（深色 WebGL 大图）解耦，专为知识页轻量总览设计。
 */
import type { DomainNode, RepoCard } from '~/api/repoTree'
import Graph from 'graphology'
import forceAtlas2 from 'graphology-layout-forceatlas2'
import Sigma from 'sigma'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps<{
  domains: DomainNode[]
  repoMap: Record<string, RepoCard>
}>()

const emit = defineEmits<{
  (e: 'enter-domain', node: DomainNode): void
  (e: 'open-repo', repoId: string): void
}>()

const container = ref<HTMLDivElement | null>(null)
let sigma: Sigma | null = null
const domainById = new Map<string, DomainNode>()

const STATUS_COLOR: Record<string, string> = {
  indexed: '#10b981',
  indexing: '#3b82f6',
  failed: '#ef4444',
  not_indexed: '#f59e0b',
}

function deepRepoCount(node: DomainNode): number {
  let n = node.repo_ids.length
  node.children.forEach((c) => {
    n += deepRepoCount(c)
  })
  return n
}

function buildGraph(): Graph {
  const graph = new Graph()
  domainById.clear()

  const addDomain = (node: DomainNode, parentId: string | null) => {
    const id = `domain:${node.id}`
    domainById.set(node.id, node)
    if (!graph.hasNode(id)) {
      graph.addNode(id, {
        label: node.title,
        kind: 'domain',
        domainId: node.id,
        size: 8 + Math.sqrt(deepRepoCount(node)) * 2,
        color: '#6366f1',
        x: Math.random(),
        y: Math.random(),
      })
    }
    if (parentId && graph.hasNode(parentId) && !graph.hasEdge(parentId, id))
      graph.addEdge(parentId, id, { color: '#c7d2fe' })

    for (const repoId of node.repo_ids) {
      const card = props.repoMap[repoId]
      if (!card)
        continue
      const rid = `repo:${repoId}`
      if (!graph.hasNode(rid)) {
        graph.addNode(rid, {
          label: card.name,
          kind: 'repo',
          repoId,
          size: 5,
          color: STATUS_COLOR[card.index_status] ?? '#94a3b8',
          x: Math.random(),
          y: Math.random(),
        })
      }
      if (!graph.hasEdge(id, rid))
        graph.addEdge(id, rid, { color: '#e2e8f0' })
    }

    node.children.forEach(child => addDomain(child, id))
  }

  props.domains.forEach(d => addDomain(d, null))
  return graph
}

function render() {
  if (!container.value)
    return
  if (sigma) {
    sigma.kill()
    sigma = null
  }
  const graph = buildGraph()
  if (graph.order === 0)
    return

  // ForceAtlas2 同步精修（节点量级小，主线程可承受）
  forceAtlas2.assign(graph, {
    iterations: 200,
    settings: { ...forceAtlas2.inferSettings(graph), gravity: 2, scalingRatio: 12 },
  })

  sigma = new Sigma(graph, container.value, {
    renderLabels: true,
    labelColor: { color: '#475569' },
    labelFont: 'inherit',
    labelSize: 12,
    defaultEdgeColor: '#e2e8f0',
    minCameraRatio: 0.2,
    maxCameraRatio: 4,
  })

  sigma.on('clickNode', ({ node }) => {
    const attrs = graph.getNodeAttributes(node)
    if (attrs.kind === 'domain') {
      const d = domainById.get(attrs.domainId)
      if (d)
        emit('enter-domain', d)
    }
    else if (attrs.kind === 'repo') {
      emit('open-repo', attrs.repoId)
    }
  })
}

onMounted(render)
watch(() => props.domains, render, { deep: false })

onBeforeUnmount(() => {
  sigma?.kill()
  sigma = null
})
</script>

<template>
  <div class="relative w-full overflow-hidden rounded-xl border border-border bg-card" style="height: 60vh;">
    <div ref="container" class="h-full w-full" />
    <div class="pointer-events-none absolute left-3 top-3 flex items-center gap-3 rounded-lg bg-background/80 px-2.5 py-1 text-[11px] text-muted-foreground backdrop-blur">
      <span class="inline-flex items-center gap-1"><span class="h-2 w-2 rounded-full" style="background:#6366f1" /> 业务域</span>
      <span class="inline-flex items-center gap-1"><span class="h-2 w-2 rounded-full" style="background:#10b981" /> 仓库</span>
      <span>点击节点下钻</span>
    </div>
  </div>
</template>
