<script setup lang="ts">
import type { GalaxyEdgeType, GalaxyMeta, GalaxyNodeType } from '~/api/galaxy'
import { ref } from 'vue'
import { EDGE_COLORS, NODE_COLORS, NODE_TYPE_LABELS } from '~/lib/galaxy/graph-adapter'

const props = defineProps<{
  maxNodes: number
  fps: number
  meta: GalaxyMeta | null
  activeNodeTypes: Set<GalaxyNodeType>
  activeEdgeTypes: Set<GalaxyEdgeType>
}>()

const emit = defineEmits<{
  (e: 'update:max-nodes', value: number): void
  (e: 'toggle-node-type', type: GalaxyNodeType): void
  (e: 'toggle-edge-type', type: GalaxyEdgeType): void
  (e: 'set-all-node-types', active: boolean): void
  (e: 'set-all-edge-types', active: boolean): void
  (e: 'refresh'): void
}>()

const panelOpen = ref(true)

const NODE_TYPES: GalaxyNodeType[] = [
  'chunk_registry',
  'symbol',
  'endpoint',
  'api_wrapper',
  'api_call_site',
]

const EDGE_TYPES: GalaxyEdgeType[] = [
  'CALL',
  'IMPORT',
  'SAME_FILE',
  'TEST_OF',
  'CO_CHANGED',
  'SEMANTIC',
  'API_CALLS',
  'IMPLEMENTS',
]

function fpsBadgeClass(fps: number): string {
  if (fps >= 50)
    return 'text-emerald-400'
  if (fps >= 30)
    return 'text-amber-400'
  return 'text-red-400'
}

function onMaxNodesChange(event: Event): void {
  const value = Number((event.target as HTMLInputElement).value)
  emit('update:max-nodes', value)
}
</script>

<template>
  <div class="glass-card rounded-2xl w-64 overflow-hidden">
    <!-- 标题（可折叠） -->
    <button
      type="button"
      class="w-full px-4 py-3 flex items-center gap-2 text-left hover:bg-white/5 transition-colors"
      :aria-expanded="panelOpen"
      aria-controls="galaxy-controls-content"
      @click="panelOpen = !panelOpen"
    >
      <span class="icon-[lucide--sliders-horizontal] text-sm text-primary" />
      <span class="text-sm font-semibold text-white/90">图谱控制</span>
      <span
        class="font-mono text-xs font-bold ml-auto"
        :class="fpsBadgeClass(props.fps)"
        aria-live="polite"
        :aria-label="`当前帧率 ${props.fps} FPS`"
      >
        {{ props.fps }} FPS
      </span>
      <span
        class="icon-[lucide--chevron-down] text-sm text-white/40 transition-transform duration-200"
        :class="{ 'rotate-180': panelOpen }"
      />
    </button>

    <div
      v-if="panelOpen"
      id="galaxy-controls-content"
      class="px-4 pb-4 pt-1 space-y-4 border-t border-white/5"
    >
      <!-- 采样数量 -->
      <div class="space-y-1.5 pt-2">
        <div class="flex items-center justify-between">
          <label class="text-xs text-white/50" for="galaxy-max-nodes">
            最大节点数
          </label>
          <span class="text-xs font-mono text-white/90">{{ props.maxNodes }}</span>
        </div>
        <input
          id="galaxy-max-nodes"
          type="range"
          :value="props.maxNodes"
          min="50"
          max="5000"
          step="50"
          class="w-full h-1.5 accent-primary cursor-pointer"
          :aria-valuemin="50"
          :aria-valuemax="5000"
          :aria-valuenow="props.maxNodes"
          aria-label="最大节点数量"
          @change="onMaxNodesChange"
        >
        <div class="flex justify-between text-xs text-white/30">
          <span>50</span>
          <span>5000</span>
        </div>
      </div>

      <!-- 采样信息 -->
      <div v-if="props.meta?.sampled" class="text-xs text-amber-300/80 bg-amber-400/10 rounded-lg px-2.5 py-2">
        共 {{ props.meta.total_nodes }} 节点，已采样 top-{{ props.maxNodes }}
      </div>

      <!-- 节点类型过滤 -->
      <div class="space-y-1.5">
        <div class="flex items-center justify-between">
          <span class="text-xs text-white/50">节点类型</span>
          <div class="flex gap-1">
            <button type="button" class="text-xs text-primary/80 hover:text-primary" @click="emit('set-all-node-types', true)">
              全选
            </button>
            <span class="text-white/20">/</span>
            <button type="button" class="text-xs text-white/40 hover:text-white/80" @click="emit('set-all-node-types', false)">
              清空
            </button>
          </div>
        </div>
        <div class="grid grid-cols-1 gap-0.5">
          <label
            v-for="t in NODE_TYPES"
            :key="t"
            class="flex items-center gap-2 text-xs cursor-pointer transition-colors py-0.5"
            :class="props.activeNodeTypes.has(t) ? 'text-white/85 hover:text-white' : 'text-white/30 hover:text-white/60'"
          >
            <input
              type="checkbox"
              :checked="props.activeNodeTypes.has(t)"
              class="accent-primary w-3 h-3"
              @change="emit('toggle-node-type', t)"
            >
            <span
              class="inline-block w-2.5 h-2.5 rounded-full shrink-0"
              :style="{ backgroundColor: NODE_COLORS[t], opacity: props.activeNodeTypes.has(t) ? 1 : 0.3 }"
            />
            {{ NODE_TYPE_LABELS[t] }}
          </label>
        </div>
      </div>

      <!-- 边类型过滤 -->
      <div class="space-y-1.5">
        <div class="flex items-center justify-between">
          <span class="text-xs text-white/50">边类型</span>
          <div class="flex gap-1">
            <button type="button" class="text-xs text-primary/80 hover:text-primary" @click="emit('set-all-edge-types', true)">
              全选
            </button>
            <span class="text-white/20">/</span>
            <button type="button" class="text-xs text-white/40 hover:text-white/80" @click="emit('set-all-edge-types', false)">
              清空
            </button>
          </div>
        </div>
        <div class="grid grid-cols-2 gap-x-2 gap-y-0.5">
          <label
            v-for="t in EDGE_TYPES"
            :key="t"
            class="flex items-center gap-1.5 text-[11px] cursor-pointer transition-colors py-0.5"
            :class="props.activeEdgeTypes.has(t) ? 'text-white/85 hover:text-white' : 'text-white/30 hover:text-white/60'"
          >
            <input
              type="checkbox"
              :checked="props.activeEdgeTypes.has(t)"
              class="accent-primary w-3 h-3"
              @change="emit('toggle-edge-type', t)"
            >
            <span
              class="inline-block w-3 h-0.5 rounded-full shrink-0"
              :style="{ backgroundColor: EDGE_COLORS[t], opacity: props.activeEdgeTypes.has(t) ? 1 : 0.3 }"
            />
            {{ t }}
          </label>
        </div>
      </div>

      <!-- 刷新按钮 -->
      <button
        type="button"
        class="w-full text-xs py-1.5 px-3 rounded-lg border border-white/10 text-white/60 hover:text-white/90 hover:border-white/25 hover:bg-white/5 transition-colors flex items-center justify-center gap-1.5"
        @click="emit('refresh')"
      >
        <span class="icon-[lucide--refresh-cw] text-xs" />
        重新加载图谱
      </button>
    </div>
  </div>
</template>
