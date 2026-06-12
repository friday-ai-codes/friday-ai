<script setup lang="ts">
import { computed } from 'vue'
import type { RelatedEntity } from '~/api/knowledge'
import { RouterLink } from 'vue-router'
import { Badge } from '~/components/ui/badge'
import EntityKindBadge from './EntityKindBadge.vue'

const props = defineProps<{
  related: RelatedEntity[]
  currentEntityId: string
}>()

interface TreeNode {
  entity: RelatedEntity
  children: TreeNode[]
}

function buildTree(items: RelatedEntity[]): TreeNode[] {
  const byId = new Map(items.map(r => [r.entity_id, r]))
  const roots: TreeNode[] = []
  const childIds = new Set<string>()

  for (const item of items) {
    if (item.depth === 0 || item.entity_id === props.currentEntityId)
      continue
    const parentCandidate = items.find(p => p.depth === item.depth - 1)
    if (!parentCandidate || !byId.has(parentCandidate.entity_id)) {
      roots.push({ entity: item, children: [] })
    }
    else {
      childIds.add(item.entity_id)
    }
  }

  if (roots.length === 0)
    return items.filter(i => i.entity_id !== props.currentEntityId).map(e => ({ entity: e, children: [] }))

  return roots
}

const tree = computed(() => buildTree(props.related))
</script>

<template>
  <div class="card p-5 space-y-3">
    <div
      v-for="node in tree"
      :key="node.entity.entity_id"
      class="rounded border border-border/60 p-3 hover:bg-muted/30"
      :style="{ marginLeft: `${node.entity.depth * 12}px` }"
    >
      <div class="flex items-center gap-2">
        <EntityKindBadge :kind="node.entity.kind" />
        <RouterLink
          :to="`/knowledge/entities/${node.entity.entity_id}`"
          class="text-sm font-medium hover:text-primary"
        >
          {{ node.entity.metadata?.title ?? node.entity.entity_id }}
        </RouterLink>
        <Badge v-if="node.entity.depth > 0" variant="outline" class="text-xs">
          {{ node.entity.depth }} 跳
        </Badge>
      </div>
    </div>
  </div>
</template>
