<script setup lang="ts">
import { ref } from 'vue'

const legendOpen = ref(true)

const NODE_TYPES = [
  { type: 'chunk_registry', label: 'Chunk', color: '#c0c0c0' },
  { type: 'symbol', label: 'Symbol', color: '#4a90e2' },
  { type: 'endpoint', label: 'Endpoint', color: '#ff8c42' },
  { type: 'api_wrapper', label: 'API Wrapper', color: '#50e3a4' },
  { type: 'api_call_site', label: 'API Call Site', color: '#00d4ff' },
]

const EDGE_TYPES = [
  { type: 'CALL', label: 'CALL', color: '#4a90e2' },
  { type: 'IMPORT', label: 'IMPORT', color: '#50e3a4' },
  { type: 'SAME_FILE', label: 'SAME_FILE', color: '#555555' },
  { type: 'TEST_OF', label: 'TEST_OF', color: '#ff8c42' },
  { type: 'CO_CHANGED', label: 'CO_CHANGED', color: '#9b59b6' },
  { type: 'SEMANTIC', label: 'SEMANTIC', color: '#e91e63' },
  { type: 'API_CALLS', label: 'API_CALLS ✦', color: '#ff4444' },
  { type: 'IMPLEMENTS', label: 'IMPLEMENTS', color: '#7c3aed' },
]
</script>

<template>
  <div class="glass-card rounded-2xl overflow-hidden">
    <!-- 折叠 toggle -->
    <button
      class="px-4 py-2.5 flex items-center gap-2 w-full text-left hover:bg-white/5 transition-colors"
      :aria-expanded="legendOpen"
      aria-controls="galaxy-legend-content"
      @click="legendOpen = !legendOpen"
    >
      <span class="icon-[lucide--layers] text-sm text-primary" />
      <span class="text-sm font-medium text-foreground">图例</span>
      <span
        class="icon-[lucide--chevron-down] ml-auto text-sm text-muted-foreground transition-transform duration-200"
        :class="{ 'rotate-180': legendOpen }"
      />
    </button>

    <!-- 折叠内容 -->
    <div
      v-if="legendOpen"
      id="galaxy-legend-content"
      class="px-4 pb-3 border-t border-border/30 space-y-3"
    >
      <!-- 节点类型 -->
      <div class="pt-2">
        <p class="text-xs text-muted-foreground uppercase tracking-wider mb-1.5">
          节点类型
        </p>
        <ul class="space-y-1">
          <li
            v-for="n in NODE_TYPES"
            :key="n.type"
            class="flex items-center gap-2 text-xs text-foreground/80"
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
        <p class="text-xs text-muted-foreground uppercase tracking-wider mb-1.5">
          边类型
        </p>
        <ul class="space-y-1">
          <li
            v-for="e in EDGE_TYPES"
            :key="e.type"
            class="flex items-center gap-2 text-xs text-foreground/80"
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
