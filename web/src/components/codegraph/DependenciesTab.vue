<script setup lang="ts">
import type { Edge, Node } from '@vue-flow/core'
import type { NeighborsData } from '~/api/codegraph'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MarkerType, Panel, useVueFlow, VueFlow } from '@vue-flow/core'
import { computed, nextTick, ref, watch } from 'vue'
import { getNeighbors } from '~/api/codegraph'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { useDagreLayout } from '~/composables/useDagreLayout'
import '@vue-flow/controls/dist/style.css'
import '@vue-flow/core/dist/style.css'

interface FocusTarget {
  nodeType: 'file' | 'component'
  id: string
  label: string
}

const props = defineProps<{
  repositoryId: string
  focus?: FocusTarget | null
}>()

const emit = defineEmits<{
  (e: 'selectSymbol', id: string): void
}>()

const { applyLayout } = useDagreLayout()
const { fitView } = useVueFlow()

const focusType = ref<'file' | 'component'>(props.focus?.nodeType ?? 'file')
const fileInput = ref('')
const focusTarget = ref<FocusTarget | null>(props.focus ?? null)

const flowNodes = ref<Node[]>([])
const flowEdges = ref<Edge[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const hasLoaded = ref(false)

const isComponentFocus = computed(() => focusTarget.value?.nodeType === 'component')
const isEmpty = computed(() => hasLoaded.value && flowEdges.value.length === 0)

function basename(path: string): string {
  return path.includes('/') ? path.slice(path.lastIndexOf('/') + 1) : path
}

/** 由边方向推断每个节点相对焦点的角色（上游/下游/焦点）。 */
function buildRoles(data: NeighborsData, focusId: string): Record<string, string> {
  const roles: Record<string, string> = { [focusId]: 'focus' }
  for (const edge of data.edges) {
    if (edge.source === focusId && edge.target !== focusId)
      roles[edge.target] = 'downstream'
    if (edge.target === focusId && edge.source !== focusId)
      roles[edge.source] = 'upstream'
  }
  return roles
}

function roleClass(role: string): string {
  if (role === 'focus')
    return 'rounded-lg border-2 border-primary bg-primary/10 px-3 py-2 text-xs font-semibold'
  if (role === 'upstream')
    return 'rounded-lg border border-sky-500/50 bg-sky-500/10 px-3 py-2 text-xs'
  return 'rounded-lg border border-emerald-500/50 bg-emerald-500/10 px-3 py-2 text-xs'
}

function toFlow(data: NeighborsData, focusId: string): { nodes: Node[], edges: Edge[] } {
  const roles = buildRoles(data, focusId)
  const nodes: Node[] = data.nodes.map(n => ({
    id: n.id,
    position: { x: 0, y: 0 },
    label: n.label,
    class: roleClass(roles[n.id] ?? 'downstream'),
    data: { ...n, role: roles[n.id] ?? 'downstream' },
    ariaLabel: `${roles[n.id] ?? 'neighbor'}: ${n.label}`,
  }))
  const edges: Edge[] = data.edges.map(e => ({
    id: `${e.source}-${e.target}-${e.kind}`,
    source: e.source,
    target: e.target,
    type: 'smoothstep',
    markerEnd: MarkerType.ArrowClosed,
    label: e.count && e.count > 1 ? `${e.kind} ×${e.count}` : e.kind,
    ariaLabel: `${e.kind}: ${e.source} → ${e.target}`,
  }))
  return { nodes, edges }
}

async function fetchNeighbors() {
  const target = focusTarget.value
  if (!target)
    return
  try {
    loading.value = true
    error.value = null
    const data = await getNeighbors(props.repositoryId, target.nodeType, target.id, 'both')
    const { nodes, edges } = toFlow(data, target.id)
    flowNodes.value = applyLayout(nodes, edges, { rankdir: 'LR' })
    flowEdges.value = edges
    hasLoaded.value = true
    await nextTick()
    fitView({ padding: 0.3, duration: 400 })
  }
  catch (err) {
    error.value = err instanceof Error ? err.message : '加载失败'
  }
  finally {
    loading.value = false
  }
}

function submitFile() {
  const value = fileInput.value.trim()
  if (!value)
    return
  focusTarget.value = { nodeType: 'file', id: value, label: basename(value) }
  fetchNeighbors()
}

function switchFocus(nodeId: string, label: string) {
  if (!focusTarget.value || nodeId === focusTarget.value.id)
    return
  // 同 node_type 下切换焦点继续探索（file→file / component→component）。
  focusTarget.value = { nodeType: focusTarget.value.nodeType, id: nodeId, label }
  fetchNeighbors()
}

function onNodeClick(event: { node: Node }) {
  const node = event.node
  switchFocus(node.id, (node.label as string) ?? node.id)
}

function drillDown() {
  if (focusTarget.value?.nodeType === 'component')
    emit('selectSymbol', focusTarget.value.id)
}

watch(
  () => props.focus,
  (next) => {
    if (next) {
      focusType.value = next.nodeType
      focusTarget.value = next
      fetchNeighbors()
    }
  },
  { immediate: true },
)
</script>

<template>
  <div class="space-y-3">
    <!-- 焦点控制栏 -->
    <div class="flex flex-wrap items-center gap-2">
      <div class="flex rounded-lg border border-border/50 p-0.5">
        <button
          type="button"
          class="rounded-md px-2.5 py-1 text-xs transition-colors"
          :class="focusType === 'file' ? 'bg-primary/15 text-primary' : 'text-muted-foreground'"
          @click="focusType = 'file'"
        >
          文件
        </button>
        <button
          type="button"
          class="rounded-md px-2.5 py-1 text-xs transition-colors"
          :class="focusType === 'component' ? 'bg-primary/15 text-primary' : 'text-muted-foreground'"
          @click="focusType = 'component'"
        >
          组件
        </button>
      </div>

      <Input
        v-if="focusType === 'file'"
        v-model="fileInput"
        placeholder="输入文件路径（如 src/views/Home.vue）后回车"
        class="h-8 max-w-md text-xs"
        @keyup.enter="submitFile"
      />
      <span v-else class="text-xs text-muted-foreground">
        从 Symbols 列表选择组件（CLASS）作为焦点
      </span>

      <span v-if="focusTarget" class="text-xs text-muted-foreground">
        焦点：<span class="font-medium text-foreground">{{ focusTarget.label }}</span>
      </span>

      <Button
        v-if="isComponentFocus"
        size="sm"
        variant="outline"
        class="ml-auto h-8 text-xs"
        @click="drillDown"
      >
        <span class="icon-[lucide--git-fork] mr-1.5 h-3.5 w-3.5" />
        下钻符号级 DAG
      </Button>
    </div>

    <div class="relative h-[440px]">
      <!-- 未选焦点 -->
      <div
        v-if="!focusTarget"
        class="flex h-full flex-col items-center justify-center text-center"
      >
        <span class="icon-[lucide--folder-tree] mb-3 text-3xl text-muted-foreground" />
        <p class="text-sm text-muted-foreground">
          输入文件路径，或从 Symbols 选择组件作为焦点
        </p>
      </div>

      <!-- 错误 -->
      <div
        v-else-if="error"
        class="flex h-full flex-col items-center justify-center gap-3 text-center"
      >
        <p class="text-xs text-destructive">
          加载依赖关系失败：{{ error }}
        </p>
        <Button variant="outline" size="sm" @click="fetchNeighbors">
          重试
        </Button>
      </div>

      <!-- Vue Flow 双向依赖画布 -->
      <VueFlow
        v-else
        :nodes="flowNodes"
        :edges="flowEdges"
        :min-zoom="0.2"
        :max-zoom="2.0"
        :fit-view-on-init="true"
        :pan-on-scroll="false"
        :prevent-scrolling="true"
        :nodes-draggable="true"
        @node-click="onNodeClick"
      >
        <Background />
        <Controls />

        <!-- 空依赖（区分真无 / 未解析） -->
        <Panel v-if="isEmpty" position="top-center">
          <div class="flex flex-col items-center gap-2 pt-8">
            <span class="icon-[lucide--unplug] text-3xl text-muted-foreground" />
            <p class="text-sm text-muted-foreground">
              未发现依赖关系
            </p>
            <p class="max-w-xs text-center text-xs text-muted-foreground/70">
              该节点尚无调用/导入，或符号解析未覆盖（重建图谱后可能更完整）
            </p>
          </div>
        </Panel>

        <!-- 方向图例 -->
        <Panel position="top-left" class="flex items-center gap-3 rounded-lg bg-card/80 px-3 py-2 backdrop-blur-sm">
          <span class="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span class="h-2.5 w-2.5 rounded-sm border border-sky-500/50 bg-sky-500/10" />
            上游（被谁用）
          </span>
          <span class="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span class="h-2.5 w-2.5 rounded-sm border-2 border-primary bg-primary/10" />
            焦点
          </span>
          <span class="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span class="h-2.5 w-2.5 rounded-sm border border-emerald-500/50 bg-emerald-500/10" />
            下游（用了谁）
          </span>
        </Panel>
      </VueFlow>

      <!-- 加载 -->
      <div
        v-if="loading"
        class="absolute inset-0 flex items-center justify-center bg-background/50"
      >
        <span class="icon-[lucide--loader-circle] h-8 w-8 animate-spin text-primary" />
      </div>
    </div>
  </div>
</template>
