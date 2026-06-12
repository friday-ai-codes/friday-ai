<script setup lang="ts">
import type { ProvenanceLinks } from '~/api/knowledge'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Button } from '~/components/ui/button'

const props = defineProps<{
  provenance: ProvenanceLinks
  title?: string
}>()

const { t } = useI18n()

const links = computed(() => {
  const out: Array<{ href: string, label: string }> = []
  if (props.provenance.feishu_url)
    out.push({ href: props.provenance.feishu_url, label: t('knowledge.entity.provenance.feishu') })
  if (props.provenance.mr_url)
    out.push({ href: props.provenance.mr_url, label: t('knowledge.entity.provenance.mr') })
  if (props.provenance.session_link)
    out.push({ href: props.provenance.session_link, label: t('knowledge.entity.provenance.session') })
  return out
})
</script>

<template>
  <div class="flex flex-wrap gap-2">
    <Button
      v-for="link in links"
      :key="link.href"
      variant="outline"
      size="sm"
      as="a"
      :href="link.href"
      target="_blank"
      rel="noopener noreferrer"
      :aria-label="`${link.label}: ${title ?? ''}`"
    >
      {{ link.label }}
    </Button>
  </div>
</template>
