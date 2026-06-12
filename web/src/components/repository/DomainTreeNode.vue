<script setup lang="ts">
import type { DomainNode } from '~/api/repoTree'

const props = defineProps<{
  node: DomainNode
  depth: number
  selectedId: string | null
}>()

const emit = defineEmits<{
  (e: 'select', node: DomainNode): void
}>()

const expanded = ref(props.depth < 1)

const repoCountDeep = computed(() => {
  let count = 0
  const walk = (n: DomainNode) => {
    count += n.repo_ids.length
    n.children.forEach(walk)
  }
  walk(props.node)
  return count
})
</script>

<template>
  <div :class="depth > 0 ? 'ml-3 border-l border-border/60 pl-2' : ''">
    <div
      class="flex cursor-pointer items-center gap-1.5 rounded-md px-2 py-1.5 transition-colors"
      :class="selectedId === node.id ? 'bg-primary/10 text-primary' : 'hover:bg-muted/60'"
      @click="emit('select', node)"
    >
      <button
        v-if="node.children.length"
        class="shrink-0 text-muted-foreground transition-transform"
        :class="expanded ? 'rotate-90' : ''"
        @click.stop="expanded = !expanded"
      >
        <span class="icon-[lucide--chevron-right] block h-3.5 w-3.5" />
      </button>
      <span v-else class="h-3.5 w-3.5 shrink-0" />
      <span class="icon-[lucide--folder-tree] h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      <span class="min-w-0 flex-1 truncate text-sm">{{ node.title }}</span>
      <span class="shrink-0 rounded-full bg-muted px-1.5 text-[10px] text-muted-foreground">
        {{ repoCountDeep }}
      </span>
    </div>

    <div v-if="expanded && node.children.length" class="mt-0.5 space-y-0.5">
      <DomainTreeNode
        v-for="child in node.children"
        :key="child.id"
        :node="child"
        :depth="depth + 1"
        :selected-id="selectedId"
        @select="emit('select', $event)"
      />
    </div>
  </div>
</template>
