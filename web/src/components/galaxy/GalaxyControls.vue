<script setup lang="ts">
import type { GalaxyEdgeType, GalaxyMeta, GalaxyNodeType } from '~/api/galaxy'
import type { GalaxyRenderMode } from '~/composables/useGalaxyGraph'

const props = defineProps<{
  maxNodes: number
  fps: number
  lowFpsDetected: boolean
  renderMode: GalaxyRenderMode
  meta: GalaxyMeta | null
  activeNodeTypes: Set<GalaxyNodeType>
  activeEdgeTypes: Set<GalaxyEdgeType>
}>()

const emit = defineEmits<{
  (e: 'update:max-nodes', value: number): void
  (e: 'update:render-mode', mode: GalaxyRenderMode): void
  (e: 'toggle-node-type', type: GalaxyNodeType): void
  (e: 'toggle-edge-type', type: GalaxyEdgeType): void
  (e: 'set-all-node-types', active: boolean): void
  (e: 'set-all-edge-types', active: boolean): void
  (e: 'refresh'): void
}>()

const NODE_TYPES: Array<{ type: GalaxyNodeType, label: string }> = [
  { type: 'chunk_registry', label: 'Chunk' },
  { type: 'symbol', label: 'Symbol' },
  { type: 'endpoint', label: 'Endpoint' },
  { type: 'api_wrapper', label: 'API Wrapper' },
  { type: 'api_call_site', label: 'Call Site' },
]

const EDGE_TYPES: Array<{ type: GalaxyEdgeType, label: string }> = [
  { type: 'CALL', label: 'CALL' },
  { type: 'IMPORT', label: 'IMPORT' },
  { type: 'SAME_FILE', label: 'SAME_FILE' },
  { type: 'TEST_OF', label: 'TEST_OF' },
  { type: 'CO_CHANGED', label: 'CO_CHANGED' },
  { type: 'SEMANTIC', label: 'SEMANTIC' },
  { type: 'API_CALLS', label: 'API_CALLS' },
  { type: 'IMPLEMENTS', label: 'IMPLEMENTS' },
]

function fpsBadgeClass(fps: number): string {
  if (fps >= 60)
    return 'text-emerald-400'
  if (fps >= 30)
    return 'text-amber-400'
  return 'text-destructive'
}

function onMaxNodesChange(event: Event): void {
  const value = Number((event.target as HTMLInputElement).value)
  emit('update:max-nodes', value)
}
</script>

<template>
  <div class="glass-card rounded-2xl p-4 w-64 space-y-4">
    <!-- 标题 -->
    <div class="flex items-center justify-between">
      <div class="flex items-center gap-2">
        <span class="icon-[lucide--settings-2] text-sm text-primary" />
        <span class="text-sm font-semibold text-foreground">图谱控制</span>
      </div>
      <!-- FPS -->
      <span
        class="font-mono text-xs font-bold"
        :class="fpsBadgeClass(fps)"
        aria-live="polite"
        :aria-label="`当前帧率 ${fps} FPS`"
      >
        {{ fps }} FPS
      </span>
    </div>

    <!-- 降级提示按钮 -->
    <button
      v-if="lowFpsDetected && renderMode === 'force3d'"
      class="w-full text-xs py-1.5 px-3 rounded-lg border border-amber-400/50 text-amber-400 hover:bg-amber-400/10 transition-colors text-left"
      @click="emit('update:render-mode', 'echarts')"
    >
      ⚡ 切换到 ECharts 高性能模式
    </button>

    <!-- 渲染模式切换 -->
    <div class="flex items-center gap-2">
      <span class="text-xs text-muted-foreground shrink-0">渲染引擎</span>
      <div class="flex gap-1 ml-auto">
        <button
          class="text-xs px-2 py-0.5 rounded transition-colors"
          :class="renderMode === 'force3d' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'"
          @click="emit('update:render-mode', 'force3d')"
        >
          3D
        </button>
        <button
          class="text-xs px-2 py-0.5 rounded transition-colors"
          :class="renderMode === 'echarts' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'"
          @click="emit('update:render-mode', 'echarts')"
        >
          ECharts
        </button>
      </div>
    </div>

    <!-- 采样数量 -->
    <div class="space-y-1.5">
      <div class="flex items-center justify-between">
        <label class="text-xs text-muted-foreground" for="galaxy-max-nodes">
          最大节点数
        </label>
        <span class="text-xs font-mono text-foreground">{{ maxNodes }}</span>
      </div>
      <input
        id="galaxy-max-nodes"
        type="range"
        :value="maxNodes"
        min="50"
        max="5000"
        step="50"
        class="w-full h-1.5 accent-primary cursor-pointer"
        :aria-valuemin="50"
        :aria-valuemax="5000"
        :aria-valuenow="maxNodes"
        aria-label="最大节点数量"
        @change="onMaxNodesChange"
      >
      <div class="flex justify-between text-xs text-muted-foreground/60">
        <span>50</span>
        <span>5000</span>
      </div>
    </div>

    <!-- 采样信息 -->
    <div v-if="meta?.sampled" class="text-xs text-amber-400/80 bg-amber-400/5 rounded-lg px-2.5 py-2">
      ⚠ 共 {{ meta.total_nodes }} 节点，已采样 top-{{ maxNodes }}
    </div>

    <!-- 节点类型过滤 -->
    <div class="space-y-1.5">
      <div class="flex items-center justify-between">
        <span class="text-xs text-muted-foreground">节点类型</span>
        <div class="flex gap-1">
          <button class="text-xs text-primary/70 hover:text-primary" @click="emit('set-all-node-types', true)">
            全选
          </button>
          <span class="text-muted-foreground/40">/</span>
          <button class="text-xs text-muted-foreground hover:text-foreground" @click="emit('set-all-node-types', false)">
            清空
          </button>
        </div>
      </div>
      <div class="grid grid-cols-1 gap-0.5">
        <label
          v-for="n in NODE_TYPES"
          :key="n.type"
          class="flex items-center gap-2 text-xs cursor-pointer hover:text-foreground transition-colors"
          :class="activeNodeTypes.has(n.type) ? 'text-foreground/80' : 'text-muted-foreground/40'"
        >
          <input
            type="checkbox"
            :checked="activeNodeTypes.has(n.type)"
            class="accent-primary w-3 h-3"
            @change="emit('toggle-node-type', n.type)"
          >
          {{ n.label }}
        </label>
      </div>
    </div>

    <!-- 边类型过滤 -->
    <div class="space-y-1.5">
      <div class="flex items-center justify-between">
        <span class="text-xs text-muted-foreground">边类型</span>
        <div class="flex gap-1">
          <button class="text-xs text-primary/70 hover:text-primary" @click="emit('set-all-edge-types', true)">
            全选
          </button>
          <span class="text-muted-foreground/40">/</span>
          <button class="text-xs text-muted-foreground hover:text-foreground" @click="emit('set-all-edge-types', false)">
            清空
          </button>
        </div>
      </div>
      <div class="grid grid-cols-1 gap-0.5">
        <label
          v-for="e in EDGE_TYPES"
          :key="e.type"
          class="flex items-center gap-2 text-xs cursor-pointer hover:text-foreground transition-colors"
          :class="activeEdgeTypes.has(e.type) ? 'text-foreground/80' : 'text-muted-foreground/40'"
        >
          <input
            type="checkbox"
            :checked="activeEdgeTypes.has(e.type)"
            class="accent-primary w-3 h-3"
            @change="emit('toggle-edge-type', e.type)"
          >
          {{ e.label }}
        </label>
      </div>
    </div>

    <!-- 刷新按钮 -->
    <button
      class="w-full text-xs py-1.5 px-3 rounded-lg border border-border/50 text-muted-foreground hover:text-foreground hover:border-border transition-colors"
      @click="emit('refresh')"
    >
      <span class="icon-[lucide--refresh-cw] mr-1.5 text-xs" />
      重新加载图谱
    </button>
  </div>
</template>
