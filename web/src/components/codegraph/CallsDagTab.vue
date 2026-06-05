<script setup lang="ts">
import type { Edge, Node, NodeComponent, NodeTypesObject } from '@vue-flow/core'
import type { DagEdge, DagNode } from '~/api/codegraph'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { Panel, useVueFlow, VueFlow } from '@vue-flow/core'
import { MiniMap } from '@vue-flow/minimap'
import { markRaw, nextTick, ref, watch } from 'vue'
import { getCallsForSymbol } from '~/api/codegraph'
import { Button } from '~/components/ui/button'
import { useDagreLayout } from '~/composables/useDagreLayout'
import { CALL_EDGE_COLORS } from '~/lib/callEdgeColors'
import SymbolNode from './SymbolNode.vue'
import '@vue-flow/minimap/dist/style.css'
import '@vue-flow/controls/dist/style.css'
import '@vue-flow/core/dist/style.css'

const props = defineProps<{
  repositoryId: string
  selectedSymbolId: string | null
}>()

const emit = defineEmits<{
  (e: 'select-symbol', id: string): void
}>()

const nodeTypes: NodeTypesObject = { symbol: markRaw(SymbolNode) as NodeComponent }

const flowNodes = ref<Node[]>([])
const flowEdges = ref<Edge[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const currentHop = ref(1)
const loading2hop = ref(false)

const { applyLayout } = useDagreLayout()
const { fitView } = useVueFlow()

function toFlowNodes(dagNodes: DagNode[]): Node[] {
  return dagNodes.map(n => ({
    id: n.symbol.id,
    type: 'symbol',
    position: { x: 0, y: 0 },
    data: n.symbol,
    ariaLabel: `${n.symbol.symbol_type}: ${n.symbol.name}`,
  }))
}

function toFlowEdges(dagEdges: DagEdge[]): Edge[] {
  return dagEdges.map(e => ({
    id: `${e.source}-${e.target}`,
    source: e.source,
    target: e.target,
    type: 'smoothstep',
    style: {
      stroke: CALL_EDGE_COLORS[e.call_type as keyof typeof CALL_EDGE_COLORS] ?? CALL_EDGE_COLORS.DIRECT_CALL,
      strokeWidth: 2,
    },
    ariaLabel: `${e.call_type}: caller → callee`,
  }))
}

async function fetchDag(symbolId: string, hop: number) {
  try {
    if (hop === 2) {
      loading2hop.value = true
    }
    else {
      loading.value = true
    }
    error.value = null

    const data = await getCallsForSymbol(props.repositoryId, symbolId, hop, 5)
    const nodes = toFlowNodes(data.nodes)
    const edges = toFlowEdges(data.edges)
    flowNodes.value = applyLayout(nodes, edges)
    flowEdges.value = edges
  }
  catch (err) {
    error.value = err instanceof Error ? err.message : '加载失败'
  }
  finally {
    loading.value = false
    loading2hop.value = false
  }
}

watch(
  () => props.selectedSymbolId,
  async (id) => {
    if (!id)
      return
    currentHop.value = 1
    await fetchDag(id, 1)
    await nextTick()
    fitView({ nodes: [id], padding: 0.3, duration: 400 })
  },
  { immediate: true },
)

async function expandToHop2() {
  if (!props.selectedSymbolId || currentHop.value === 2)
    return
  currentHop.value = 2
  await fetchDag(props.selectedSymbolId, 2)
  await nextTick()
  if (props.selectedSymbolId) {
    fitView({ nodes: [props.selectedSymbolId], padding: 0.3, duration: 400 })
  }
}
</script>

<template>
  <div class="h-[480px] relative">
    <!-- 未选中 Symbol 空状态 -->
    <div
      v-if="!selectedSymbolId"
      class="flex flex-col items-center justify-center h-full text-center"
    >
      <span class="icon-[lucide--mouse-pointer-click] text-3xl text-muted-foreground mb-3" />
      <p class="text-sm text-muted-foreground">
        在 Symbols 列表中选择一个符号以查看调用关系
      </p>
    </div>

    <!-- 加载失败 -->
    <div
      v-else-if="error"
      class="flex flex-col items-center justify-center h-full text-center gap-3"
    >
      <p class="text-xs text-destructive">
        加载调用关系失败：{{ error }}
      </p>
      <Button variant="outline" size="sm" @click="selectedSymbolId && fetchDag(selectedSymbolId, currentHop)">
        重试
      </Button>
    </div>

    <!-- Vue Flow 画布 -->
    <VueFlow
      v-else
      :nodes="flowNodes"
      :edges="flowEdges"
      :node-types="nodeTypes"
      :min-zoom="0.2"
      :max-zoom="2.0"
      :fit-view-on-init="true"
      :pan-on-scroll="false"
      :prevent-scrolling="true"
      :nodes-draggable="true"
    >
      <Background />
      <Controls />
      <MiniMap />

      <!-- 空节点提示（Symbol 无调用） -->
      <Panel v-if="!loading && flowNodes.length === 0" position="top-center">
        <div class="flex flex-col items-center gap-2 pt-8">
          <span class="icon-[lucide--arrow-right-left] text-3xl text-muted-foreground" />
          <p class="text-sm text-muted-foreground">
            当前 Symbol 无调用关系
          </p>
        </div>
      </Panel>

      <!-- 扩展 2-hop 按钮 -->
      <Panel position="bottom-right" class="flex gap-2">
        <Button
          size="sm"
          variant="outline"
          class="bg-card/90 backdrop-blur-sm text-xs h-8"
          :disabled="loading2hop || currentHop === 2"
          @click="expandToHop2"
        >
          <span v-if="loading2hop" class="icon-[lucide--loader-circle] animate-spin mr-1.5 w-3.5 h-3.5" />
          {{ currentHop === 2 ? '已展示 2-hop' : '扩展 2-hop' }}
        </Button>
      </Panel>

      <!-- 调用类型图例 -->
      <Panel position="top-left" class="bg-card/80 backdrop-blur-sm rounded-lg px-3 py-2 flex items-center gap-3">
        <span class="text-xs text-muted-foreground flex items-center gap-1.5">
          <svg width="10" height="10" viewBox="0 0 10 10"><circle cx="5" cy="5" r="5" :fill="CALL_EDGE_COLORS.DIRECT_CALL" /></svg>
          DIRECT
        </span>
        <span class="text-xs text-muted-foreground flex items-center gap-1.5">
          <svg width="10" height="10" viewBox="0 0 10 10"><circle cx="5" cy="5" r="5" :fill="CALL_EDGE_COLORS.METHOD_CALL" /></svg>
          METHOD
        </span>
        <span class="text-xs text-muted-foreground flex items-center gap-1.5">
          <svg width="10" height="10" viewBox="0 0 10 10"><circle cx="5" cy="5" r="5" :fill="CALL_EDGE_COLORS.ATTRIBUTE_ACCESS" /></svg>
          ATTRIBUTE
        </span>
      </Panel>
    </VueFlow>

    <!-- 加载 skeleton -->
    <div
      v-if="loading"
      class="absolute inset-0 flex items-center justify-center bg-background/50"
    >
      <span class="icon-[lucide--loader-circle] animate-spin w-8 h-8 text-primary" />
    </div>
  </div>
</template>
