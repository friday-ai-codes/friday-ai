<script setup lang="ts">
import type { GalaxyNode, GalaxySearchResult } from '~/api/galaxy'
import { useEventListener } from '@vueuse/core'
import { computed, nextTick, ref, watch } from 'vue'
import { ScrollArea } from '~/components/ui/scroll-area'
import { useGalaxySearch } from '~/composables/useGalaxySearch'

// ============================================================================
// Props / Emits
// ============================================================================

const props = withDefaults(defineProps<{
  modelValue: boolean
  nodes?: GalaxyNode[]
}>(), {
  nodes: () => [],
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'node-select', node: GalaxySearchResult): void
}>()

// ============================================================================
// 搜索状态
// ============================================================================

const inputRef = ref<HTMLInputElement | null>(null)
const localQuery = ref('')
const selectedIndex = ref(0)

const { results, loading, error, search, setCorpus } = useGalaxySearch()

watch(() => props.nodes, (nodes) => {
  if (nodes && nodes.length > 0)
    setCorpus(nodes)
}, { immediate: true })

watch(localQuery, (q) => {
  selectedIndex.value = 0
  search(q)
})

watch(() => props.modelValue, async (open) => {
  if (open) {
    localQuery.value = ''
    selectedIndex.value = 0
    await nextTick()
    inputRef.value?.focus()
  }
})

// ============================================================================
// 键盘导航
// ============================================================================

const clampedIndex = computed(() =>
  results.value.length > 0
    ? Math.min(selectedIndex.value, results.value.length - 1)
    : 0,
)

function onKeydown(e: KeyboardEvent) {
  if (!props.modelValue)
    return

  if (e.key === 'ArrowDown') {
    e.preventDefault()
    selectedIndex.value = Math.min(selectedIndex.value + 1, results.value.length - 1)
  }
  else if (e.key === 'ArrowUp') {
    e.preventDefault()
    selectedIndex.value = Math.max(selectedIndex.value - 1, 0)
  }
  else if (e.key === 'Enter') {
    e.preventDefault()
    const item = results.value[clampedIndex.value]
    if (item)
      selectNode(item)
  }
  else if (e.key === 'Escape') {
    close()
  }
}

// ============================================================================
// Cmd+K 全局快捷键
// ============================================================================

useEventListener(document, 'keydown', (e: KeyboardEvent) => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault()
    emit('update:modelValue', true)
  }
})

// ============================================================================
// 节点类型颜色
// ============================================================================

const TYPE_COLORS: Record<string, string> = {
  chunk_registry: 'bg-gray-500/20 text-gray-300 border-gray-500/30',
  symbol: 'bg-blue-500/20 text-blue-300 border-blue-500/30',
  endpoint: 'bg-orange-500/20 text-orange-300 border-orange-500/30',
  api_wrapper: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
  api_call_site: 'bg-cyan-500/20 text-cyan-300 border-cyan-500/30',
}

function typeColor(type: string): string {
  return TYPE_COLORS[type] ?? 'bg-white/10 text-white/60 border-white/20'
}

// ============================================================================
// 操作
// ============================================================================

function close() {
  emit('update:modelValue', false)
}

function selectNode(node: GalaxySearchResult) {
  emit('node-select', node)
  close()
}

function onOverlayClick(e: MouseEvent) {
  if ((e.target as HTMLElement).classList.contains('cp-overlay'))
    close()
}
</script>

<template>
  <Teleport to="body">
    <Transition name="palette-fade">
      <div
        v-if="modelValue"
        class="cp-overlay fixed inset-0 z-50 flex items-start justify-center pt-[15vh] bg-black/60 backdrop-blur-sm"
        @click="onOverlayClick"
        @keydown="onKeydown"
      >
        <div
          class="w-full max-w-2xl mx-4 rounded-2xl border border-white/10 bg-[#0a0a1f]/90 backdrop-blur-xl shadow-2xl overflow-hidden"
          role="dialog"
          aria-modal="true"
          aria-label="搜索节点"
        >
          <!-- 搜索输入框 -->
          <div class="flex items-center gap-3 px-4 py-3 border-b border-white/10">
            <span
              v-if="loading"
              class="icon-[lucide--loader-circle] text-white/40 text-lg animate-spin shrink-0"
            />
            <span
              v-else
              class="icon-[lucide--search] text-white/40 text-lg shrink-0"
            />
            <input
              ref="inputRef"
              v-model="localQuery"
              type="text"
              placeholder="搜索节点名称或路径..."
              aria-label="搜索节点名称或路径"
              class="flex-1 bg-transparent text-white text-sm placeholder-white/30 outline-none"
            >
            <kbd class="hidden sm:inline-flex items-center px-1.5 py-0.5 rounded border border-white/20 text-white/30 text-xs">
              Esc
            </kbd>
          </div>

          <!-- 搜索结果 -->
          <ScrollArea class="max-h-[400px]">
            <!-- 错误提示 -->
            <div
              v-if="error"
              class="px-4 py-2 text-xs text-amber-400/80 flex items-center gap-2"
            >
              <span class="icon-[lucide--alert-triangle] text-amber-400 shrink-0" />
              后端搜索失败，仅显示本地结果
            </div>

            <!-- 结果列表 -->
            <ul
              v-if="results.length > 0"
              role="listbox"
              aria-label="搜索结果"
              class="py-2"
            >
              <li
                v-for="(item, idx) in results"
                :key="item.id"
                role="option"
                :aria-selected="idx === clampedIndex"
                class="flex items-center gap-3 px-4 py-2.5 cursor-pointer transition-colors"
                :class="idx === clampedIndex ? 'bg-white/10' : 'hover:bg-white/5'"
                @click="selectNode(item)"
                @mouseenter="selectedIndex = idx"
              >
                <!-- 类型 badge -->
                <span
                  class="shrink-0 inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium border"
                  :class="typeColor(item.type)"
                >
                  {{ item.type.replace(/_/g, ' ') }}
                </span>
                <!-- 标签 -->
                <div class="flex-1 min-w-0">
                  <p class="text-white text-sm font-medium truncate">
                    {{ item.label }}
                  </p>
                  <p class="text-white/40 text-xs truncate">
                    {{ item.file_path }}
                  </p>
                </div>
                <!-- 度数 -->
                <span class="shrink-0 text-white/30 text-xs">
                  ×{{ item.degree }}
                </span>
              </li>
            </ul>

            <!-- 空状态 -->
            <div
              v-else-if="!loading && localQuery"
              class="flex flex-col items-center gap-2 py-12 text-white/30"
            >
              <span class="icon-[lucide--search-x] text-3xl" />
              <p class="text-sm">
                未找到「{{ localQuery }}」相关节点
              </p>
            </div>

            <!-- 初始空状态 -->
            <div
              v-else-if="!loading && !localQuery"
              class="flex flex-col items-center gap-2 py-12 text-white/30"
            >
              <span class="icon-[lucide--search] text-3xl" />
              <p class="text-sm">
                输入节点名称或文件路径搜索
              </p>
              <p class="text-xs text-white/20">
                支持模糊搜索
              </p>
            </div>
          </ScrollArea>

          <!-- 底部快捷键提示 -->
          <div class="flex items-center gap-4 px-4 py-2 border-t border-white/5 text-white/20 text-xs">
            <span><kbd class="font-mono">↑↓</kbd> 导航</span>
            <span><kbd class="font-mono">↵</kbd> 选择</span>
            <span><kbd class="font-mono">Esc</kbd> 关闭</span>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.palette-fade-enter-active,
.palette-fade-leave-active {
  transition: all 0.2s ease;
}

.palette-fade-enter-from,
.palette-fade-leave-to {
  opacity: 0;
}

.palette-fade-enter-to,
.palette-fade-leave-from {
  opacity: 1;
}
</style>
