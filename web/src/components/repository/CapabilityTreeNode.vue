<script setup lang="ts">
import type { CapabilityNode } from '~/api/repoTree'

const props = defineProps<{
  node: CapabilityNode
  depth: number
  staleNodeIds?: string[]
  highlightTitles?: string[]
}>()

const emit = defineEmits<{
  (e: 'action', node: CapabilityNode): void
}>()

const expanded = ref(props.depth < 2)
const rowEl = ref<HTMLElement | null>(null)
const flashing = ref(false)

const isStale = computed(() => (props.staleNodeIds ?? []).includes(props.node.node_id))
// 高亮路径的末级即“目标节点”——需要滚动到位并闪烁提示（仅闪一下，不持续高亮）
const isTarget = computed(() => {
  const titles = props.highlightTitles ?? []
  return titles.length > 0 && titles[titles.length - 1] === props.node.title
})

watch(
  () => props.highlightTitles,
  (titles) => {
    // 搜索定位：命中路径上的节点自动展开
    if (titles?.length && props.node.children.some(c => titles.includes(c.title)))
      expanded.value = true
  },
  { immediate: true },
)

// 目标节点：滚动居中并闪烁一下
watch(
  isTarget,
  async (target) => {
    if (!target)
      return
    await nextTick()
    // 等待祖先展开后元素已在 DOM 中，再滚动到视图中央
    setTimeout(() => {
      rowEl.value?.scrollIntoView({ behavior: 'smooth', block: 'center' })
      flashing.value = false
      nextTick(() => {
        flashing.value = true
        setTimeout(() => { flashing.value = false }, 2200)
      })
    }, 120)
  },
  { immediate: true },
)

const typeBadge: Record<string, { label: string, cls: string }> = {
  sub_app: { label: '子应用', cls: 'bg-violet-500/15 text-violet-600 dark:text-violet-300' },
  module: { label: '模块', cls: 'bg-blue-500/15 text-blue-600 dark:text-blue-300' },
  capability: { label: '能力', cls: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-300' },
}
</script>

<template>
  <div :class="depth > 0 ? 'ml-4 border-l border-border/60 pl-3' : ''">
    <div
      ref="rowEl"
      class="group flex items-start gap-2 rounded-md px-2 py-1.5 transition-colors hover:bg-muted/60"
      :class="flashing ? 'kt-flash' : ''"
    >
      <button
        v-if="node.children.length"
        class="mt-0.5 shrink-0 text-muted-foreground transition-transform"
        :class="expanded ? 'rotate-90' : ''"
        @click="expanded = !expanded"
      >
        <span class="icon-[lucide--chevron-right] block h-4 w-4" />
      </button>
      <span v-else class="mt-0.5 h-4 w-4 shrink-0" />

      <div class="min-w-0 flex-1">
        <div class="flex flex-wrap items-center gap-2">
          <span
            class="rounded px-1.5 py-0.5 text-[10px] font-medium"
            :class="typeBadge[node.node_type]?.cls ?? typeBadge.module.cls"
          >
            {{ typeBadge[node.node_type]?.label ?? node.node_type }}
          </span>
          <span class="text-sm font-medium">{{ node.title }}</span>
          <span
            v-if="isStale"
            class="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] text-amber-600 dark:text-amber-300"
            title="该节点覆盖的代码近期有变更，描述可能过时"
          >
            待刷新
          </span>
          <button
            class="hidden rounded px-1.5 py-0.5 text-[10px] text-muted-foreground hover:bg-muted hover:text-foreground group-hover:inline-block"
            title="复制节点上下文（仓库/路径），用于发起对话或编码任务"
            @click="emit('action', node)"
          >
            复制上下文
          </button>
        </div>
        <p v-if="node.summary" class="mt-0.5 text-xs text-muted-foreground">
          {{ node.summary }}
        </p>
        <div v-if="node.paths?.length" class="mt-1 flex flex-wrap gap-1">
          <code
            v-for="p in node.paths.slice(0, 4)"
            :key="p"
            class="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
          >
            {{ p }}
          </code>
        </div>
      </div>
    </div>

    <div v-if="expanded && node.children.length" class="mt-0.5 space-y-0.5">
      <CapabilityTreeNode
        v-for="child in node.children"
        :key="child.node_id"
        :node="child"
        :depth="depth + 1"
        :stale-node-ids="staleNodeIds"
        :highlight-titles="highlightTitles"
        @action="emit('action', $event)"
      />
    </div>
  </div>
</template>

<style scoped>
/* 目标能力节点定位后的闪烁提示 */
.kt-flash {
  animation: kt-flash-pulse 2.2s ease-out;
}

@keyframes kt-flash-pulse {
  0% {
    background-color: rgba(251, 191, 36, 0.4);
    box-shadow: 0 0 0 2px rgba(251, 191, 36, 0.85);
  }
  30% {
    background-color: rgba(251, 191, 36, 0.28);
    box-shadow: 0 0 0 3px rgba(251, 191, 36, 0.55);
  }
  100% {
    background-color: transparent;
    box-shadow: 0 0 0 0 rgba(251, 191, 36, 0);
  }
}

@media (prefers-reduced-motion: reduce) {
  .kt-flash {
    animation: none;
  }
}
</style>
