<script setup lang="ts">
import { ref } from 'vue'
import { EDGE_COLORS, NODE_COLORS, NODE_TYPE_LABELS } from '~/lib/galaxy/graph-adapter'

const legendOpen = ref(true)

// 视觉编码来自 graph-adapter 单一来源，保证图例与画布完全一致
const NODE_TYPES = (
  ['chunk_registry', 'symbol', 'endpoint', 'api_wrapper', 'api_call_site'] as const
).map(type => ({ type, label: NODE_TYPE_LABELS[type], color: NODE_COLORS[type] }))

const EDGE_TYPES = (
  ['CALL', 'IMPORT', 'SAME_FILE', 'TEST_OF', 'CO_CHANGED', 'SEMANTIC', 'API_CALLS', 'IMPLEMENTS'] as const
).map(type => ({ type, label: type, color: EDGE_COLORS[type] }))
</script>

<template>
  <div class="glass-card rounded-2xl overflow-hidden w-48">
    <!-- 折叠 toggle -->
    <button
      type="button"
      class="px-4 py-2.5 flex items-center gap-2 w-full text-left hover:bg-white/5 transition-colors"
      :aria-expanded="legendOpen"
      aria-controls="galaxy-legend-content"
      @click="legendOpen = !legendOpen"
    >
      <span class="icon-[lucide--layers] text-sm text-primary" />
      <span class="text-sm font-medium text-white/90">图例</span>
      <span
        class="icon-[lucide--chevron-down] ml-auto text-sm text-white/40 transition-transform duration-200"
        :class="{ 'rotate-180': legendOpen }"
      />
    </button>

    <!-- 折叠内容 -->
    <div
      v-if="legendOpen"
      id="galaxy-legend-content"
      class="px-4 pb-3 border-t border-white/5 space-y-3"
    >
      <!-- 节点类型 -->
      <div class="pt-2">
        <p class="text-[10px] text-white/40 uppercase tracking-wider mb-1.5">
          节点类型
        </p>
        <ul class="space-y-1">
          <li
            v-for="n in NODE_TYPES"
            :key="n.type"
            class="flex items-center gap-2 text-xs text-white/75"
          >
            <span
              class="inline-block w-3 h-3 rounded-full shrink-0"
              :style="{ backgroundColor: n.color }"
            />
            {{ n.label }}
          </li>
        </ul>
      </div>

      <!-- 边类型 -->
      <div>
        <p class="text-[10px] text-white/40 uppercase tracking-wider mb-1.5">
          边类型
        </p>
        <ul class="space-y-1">
          <li
            v-for="e in EDGE_TYPES"
            :key="e.type"
            class="flex items-center gap-2 text-xs text-white/75"
          >
            <span
              class="inline-block w-5 h-0.5 shrink-0 rounded-full"
              :style="{ backgroundColor: e.color }"
            />
            {{ e.label }}
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>
