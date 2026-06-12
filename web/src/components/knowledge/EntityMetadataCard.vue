<script setup lang="ts">
import type { EntityMetadata } from '~/api/knowledge'
import { Badge } from '~/components/ui/badge'
import EntityKindBadge from './EntityKindBadge.vue'
import ProvenanceLinkButton from './ProvenanceLinkButton.vue'
import { useI18n } from 'vue-i18n'

defineProps<{
  entity: EntityMetadata
}>()

const { t } = useI18n()
</script>

<template>
  <div class="card p-5 space-y-4">
    <div class="flex flex-wrap items-center gap-2">
      <h1 class="text-xl font-semibold">
        {{ entity.title }}
      </h1>
      <EntityKindBadge :kind="entity.kind" />
      <Badge v-if="!entity.invalid_at" variant="default">
        {{ t('knowledge.entity.badges.currentVersion') }}
      </Badge>
    </div>
    <p v-if="entity.superseded_hint" class="text-xs text-amber-700 bg-amber-500/8 border border-amber-500/15 rounded px-3 py-2">
      {{ entity.superseded_hint }}
    </p>
    <dl class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 text-sm">
      <div>
        <dt class="font-medium text-muted-foreground">{{ t('knowledge.entity.fields.version') }}</dt>
        <dd>{{ entity.version }}</dd>
      </div>
      <div>
        <dt class="font-medium text-muted-foreground">{{ t('knowledge.entity.fields.entityId') }}</dt>
        <dd class="font-mono text-xs">{{ entity.entity_id }}</dd>
      </div>
      <div v-if="entity.valid_at">
        <dt class="font-medium text-muted-foreground">{{ t('knowledge.entity.fields.validAt') }}</dt>
        <dd>{{ entity.valid_at }}</dd>
      </div>
      <div v-if="entity.event_time">
        <dt class="font-medium text-muted-foreground">{{ t('knowledge.entity.fields.eventTime') }}</dt>
        <dd>{{ entity.event_time }}</dd>
      </div>
    </dl>
    <ProvenanceLinkButton :provenance="entity.provenance" :title="entity.title" />
  </div>
</template>
