<script setup lang="ts">
import PageHeader from '~/components/common/PageHeader.vue'
import { Button } from '~/components/ui/button'

defineEmits<{
  (e: 'create'): void
}>()
</script>

<template>
  <PageHeader
    icon="lucide--workflow"
    icon-gradient="from-primary/20 to-primary/10"
    icon-color="text-primary"
    title="工作流"
    description="管理和自动化您的开发工作流"
  >
    <template #actions>
      <Button @click="$emit('create')">
        <span class="icon-[lucide--plus]" />
        新建工作流
      </Button>
    </template>
  </PageHeader>
</template>
