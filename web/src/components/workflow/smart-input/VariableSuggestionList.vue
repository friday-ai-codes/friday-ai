<script setup lang="ts">
import type { SuggestionItem } from './extensions/VariableSuggestion'
import type { DesignTimeVariable } from '~/composables/useDesignTimeVariables'
import { computed, nextTick, ref, watch } from 'vue'

interface Props {
  items: SuggestionItem[]
  command: (item: SuggestionItem) => void
}

const props = defineProps<Props>()

const selectedIndex = ref(0)
const scrollContainer = ref<HTMLElement | null>(null)

// Separate variables and functions
const variables = computed(() =>
  props.items.filter((item): item is { type: 'variable', data: DesignTimeVariable } => item.type === 'variable'),
)

const functions = computed(() =>
  props.items.filter(item => item.type === 'function'),
)

// Group variables by path prefix (input vs nodes.xxx)
const groupedVariables = computed(() => {
  const inputGroup: DesignTimeVariable[] = []
  const nodeGroups = new Map<string, { nodeLabel: string, items: DesignTimeVariable[] }>()

  for (const item of variables.value) {
    if (item.data.path.startsWith('input.')) {
      inputGroup.push(item.data)
    }
    else {
      if (!nodeGroups.has(item.data.nodeId)) {
        nodeGroups.set(item.data.nodeId, {
          nodeLabel: item.data.nodeLabel,
          items: [],
        })
      }
      nodeGroups.get(item.data.nodeId)!.items.push(item.data)
    }
  }

  const result: Array<{ groupKey: string, groupLabel: string, groupIcon: string, items: DesignTimeVariable[] }> = []

  // Add input group first
  if (inputGroup.length > 0) {
    result.push({
      groupKey: 'input',
      groupLabel: '输入变量',
      groupIcon: 'icon-[lucide--arrow-left-from-line]',
      items: inputGroup,
    })
  }

  // Add node groups
  for (const [nodeId, group] of nodeGroups) {
    result.push({
      groupKey: nodeId,
      groupLabel: group.nodeLabel,
      groupIcon: 'icon-[lucide--box]',
      items: group.items,
    })
  }

  return result
})

// Flatten all items for consistent indexing: functions first, then variables.
// 变量必须按「分组后的顺序」（输入组在前，再各节点组）展开，与模板渲染顺序及
// getVariableFlatIndex 的下标计算保持一致；否则点击/键盘选中会取到错位的变量
// （历史 bug：按 variables.value 原始顺序展开，导致选「输入变量」插成首个节点变量）。
const flatItems = computed(() => {
  const result: SuggestionItem[] = []
  functions.value.forEach(f => result.push(f))
  groupedVariables.value.forEach((group) => {
    group.items.forEach(v => result.push({ type: 'variable', data: v }))
  })
  return result
})

// Compute flat index for an item position
function getFunctionIndex(index: number): number {
  return index
}

function getVariableFlatIndex(groupIndex: number, itemIndex: number): number {
  let index = functions.value.length
  for (let g = 0; g < groupIndex; g++) {
    index += groupedVariables.value[g].items.length
  }
  return index + itemIndex
}

// Check if item at position is selected
function isFunctionSelected(index: number): boolean {
  return selectedIndex.value === index
}

function isVariableSelected(groupIndex: number, itemIndex: number): boolean {
  return selectedIndex.value === getVariableFlatIndex(groupIndex, itemIndex)
}

// Select item by flat index
function selectItem(index: number) {
  const item = flatItems.value[index]
  if (item) {
    props.command(item)
  }
}

// Scroll selected item into view
function scrollIntoView() {
  nextTick(() => {
    const selected = scrollContainer.value?.querySelector('[data-selected="true"]')
    selected?.scrollIntoView({ block: 'nearest' })
  })
}

// Reset selection when items change
watch(() => props.items, () => {
  selectedIndex.value = 0
})

// Keyboard navigation handler
function onKeyDown(event: KeyboardEvent): boolean {
  if (event.key === 'ArrowUp') {
    selectedIndex.value = Math.max(0, selectedIndex.value - 1)
    scrollIntoView()
    return true
  }

  if (event.key === 'ArrowDown') {
    selectedIndex.value = Math.min(flatItems.value.length - 1, selectedIndex.value + 1)
    scrollIntoView()
    return true
  }

  if (event.key === 'Enter' || event.key === 'Tab') {
    selectItem(selectedIndex.value)
    return true
  }

  // Let Esc be handled by TipTap
  return false
}

// Get color class for type
function getTypeColor(type: string): string {
  const colors: Record<string, string> = {
    string: 'text-green-600 bg-green-500/10',
    number: 'text-primary bg-primary/10',
    integer: 'text-primary bg-primary/10',
    boolean: 'text-amber-600 bg-amber-500/10',
    object: 'text-purple-600 bg-purple-500/10',
    array: 'text-cyan-600 bg-cyan-500/10',
  }
  return colors[type] || 'text-muted-foreground bg-muted'
}

defineExpose({ onKeyDown })
</script>

<template>
  <div class="bg-popover/95 backdrop-blur-md border border-border/50 rounded-xl shadow-lg shadow-black/5 overflow-hidden min-w-64">
    <!-- Scrollable content -->
    <div
      ref="scrollContainer"
      class="max-h-72 overflow-y-auto p-1"
    >
      <!-- Empty state -->
      <div
        v-if="items.length === 0"
        class="flex flex-col items-center justify-center py-6 px-4 text-center"
      >
        <div class="p-2.5 rounded-xl bg-muted/50 mb-2">
          <span class="icon-[lucide--variable] text-xl text-muted-foreground" />
        </div>
        <p class="text-xs font-medium text-muted-foreground">
          当前无可用变量
        </p>
        <p class="text-[10px] text-muted-foreground mt-0.5">
          请先连接上游节点
        </p>
      </div>

      <!-- Function group -->
      <div v-if="functions.length > 0" class="mb-0.5">
        <div class="px-2 py-1 text-[10px] font-medium text-muted-foreground flex items-center gap-1">
          <span class="icon-[lucide--function-square] text-[10px] opacity-70" />
          <span>函数</span>
        </div>

        <button
          v-for="(item, index) in functions"
          :key="item.data.name"
          type="button"
          :data-selected="isFunctionSelected(index)"
          class="w-full px-2.5 py-1.5 text-left rounded-lg transition-colors"
          :class="[isFunctionSelected(index) ? 'bg-accent' : 'hover:bg-accent/50']"
          @click="selectItem(getFunctionIndex(index))"
        >
          <div class="flex items-center justify-between gap-2">
            <div class="flex items-center gap-1.5 min-w-0">
              <code class="font-mono text-xs font-medium shrink-0 text-blue-600">{{ item.data.name }}()</code>
              <span class="text-[10px] text-muted-foreground truncate">
                {{ item.data.description }}
              </span>
            </div>
          </div>
          <!-- Parameter hints -->
          <div class="mt-0.5 flex flex-wrap gap-1">
            <span
              v-for="param in item.data.params"
              :key="param.name"
              class="text-[9px] px-1 py-0.5 rounded bg-muted font-mono"
            >
              {{ param.name }}
              <span v-if="param.type" class="text-muted-foreground">: {{ param.type }}</span>
            </span>
          </div>
        </button>
      </div>

      <!-- Grouped variable list -->
      <template v-if="variables.length > 0">
        <div
          v-for="(group, groupIndex) in groupedVariables"
          :key="group.groupKey"
          class="mb-0.5 last:mb-0"
        >
          <!-- Group header -->
          <div class="px-2 py-1 text-[10px] font-medium text-muted-foreground flex items-center gap-1">
            <span :class="group.groupIcon" class="text-[10px] opacity-70" />
            <span>{{ group.groupLabel }}</span>
          </div>

          <!-- Group items -->
          <button
            v-for="(item, itemIndex) in group.items"
            :key="item.path"
            type="button"
            :data-selected="isVariableSelected(groupIndex, itemIndex)"
            class="w-full px-2.5 py-1.5 text-left rounded-lg transition-colors"
            :class="[isVariableSelected(groupIndex, itemIndex) ? 'bg-accent' : 'hover:bg-accent/50']"
            @click="selectItem(getVariableFlatIndex(groupIndex, itemIndex))"
          >
            <div class="flex items-center justify-between gap-2">
              <!-- Variable info: key + description -->
              <div class="flex items-center gap-1.5 min-w-0">
                <code class="font-mono text-xs font-medium shrink-0">{{ item.key }}</code>
                <span v-if="item.description" class="text-[10px] text-muted-foreground truncate">
                  {{ item.description }}
                </span>
              </div>
              <!-- Type badge -->
              <span
                class="text-[9px] px-1 py-0.5 rounded-full shrink-0 font-medium"
                :class="getTypeColor(item.type)"
              >
                {{ item.type }}
              </span>
            </div>
            <!-- Full path (secondary) -->
            <div class="mt-0.5 text-[10px] text-muted-foreground font-mono truncate">
              {{ item.path }}
            </div>
          </button>
        </div>
      </template>
    </div>

    <!-- Keyboard hints footer -->
    <div
      v-if="items.length > 0"
      class="flex items-center gap-3 px-2.5 py-1.5 border-t border-border/50 bg-muted/30"
    >
      <div class="flex items-center gap-1 text-[10px] text-muted-foreground">
        <kbd class="px-1 py-0.5 rounded bg-muted border border-border/50 font-mono text-[9px]">↑</kbd>
        <kbd class="px-1 py-0.5 rounded bg-muted border border-border/50 font-mono text-[9px]">↓</kbd>
        <span>导航</span>
      </div>
      <div class="flex items-center gap-1 text-[10px] text-muted-foreground">
        <kbd class="px-1 py-0.5 rounded bg-muted border border-border/50 font-mono text-[9px]">Tab</kbd>
        <span>选中</span>
      </div>
      <div class="flex items-center gap-1 text-[10px] text-muted-foreground">
        <kbd class="px-1 py-0.5 rounded bg-muted border border-border/50 font-mono text-[9px]">Esc</kbd>
        <span>关闭</span>
      </div>
    </div>
  </div>
</template>
