<script setup lang="ts">
import type { ProvenanceLinks, TimelineNode } from '~/api/knowledge'
import EntityKindBadge from './EntityKindBadge.vue'
import ProvenanceLinkButton from './ProvenanceLinkButton.vue'

defineProps<{
  nodes: TimelineNode[]
}>()

function hasProvenance(provenance?: ProvenanceLinks): boolean {
  return Boolean(provenance && (provenance.feishu_url || provenance.mr_url || provenance.session_link))
}
</script>

<template>
  <div class="card p-5">
    <ol class="space-y-6">
      <li
        v-for="node in [...nodes].reverse()"
        :key="node.version"
        class="flex gap-3"
        data-testid="timeline-node"
      >
        <div class="flex flex-col items-center pt-1">
          <span class="w-2.5 h-2.5 rounded-full bg-emerald-400" />
          <span class="w-px flex-1 bg-border/60 min-h-4" />
        </div>
        <div class="flex-1 space-y-2 pb-2">
          <div class="flex items-center gap-2">
            <span class="text-sm font-medium">v{{ node.version }} · {{ node.title }}</span>
            <EntityKindBadge :kind="node.kind" />
          </div>
          <p v-if="node.summary" class="text-xs text-muted-foreground line-clamp-3">
            {{ node.summary }}
          </p>
          <ProvenanceLinkButton
            v-if="hasProvenance(node.provenance)"
            :provenance="node.provenance!"
            :title="node.title"
          />
          <ul v-if="node.code_changes?.length" class="pl-4 border-l border-border/50 space-y-2">
            <li v-for="cc in node.code_changes" :key="`${cc.entity_id}-${cc.version}`" class="text-sm">
              <EntityKindBadge :kind="cc.kind" />
              <span class="ml-2">{{ cc.title }}</span>
              <div class="mt-1">
                <ProvenanceLinkButton :provenance="cc.provenance" :title="cc.title" />
              </div>
            </li>
          </ul>
        </div>
      </li>
    </ol>
  </div>
</template>
