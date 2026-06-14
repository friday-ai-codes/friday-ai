<script setup lang="ts">
import type { RelatedEntity } from '~/api/knowledge'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { Badge } from '~/components/ui/badge'
import EntityKindBadge from './EntityKindBadge.vue'

const props = defineProps<{
  related: RelatedEntity[]
  currentEntityId: string
}>()

const { t, te } = useI18n()

interface TreeNode {
  entity: RelatedEntity
  children: TreeNode[]
}

const tree = computed<TreeNode[]>(() =>
  props.related
    .filter(item => item.entity_id !== props.currentEntityId)
    .map(entity => ({ entity, children: [] })),
)

function relationLabel(relation: string): string {
  const key = `knowledge.relation.${relation}`
  return te(key) ? t(key) : relation
}
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
        <Badge
          v-if="node.entity.relation"
          variant="secondary"
          class="text-xs"
          data-testid="relation-badge"
        >
          {{ relationLabel(node.entity.relation) }}
        </Badge>
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
