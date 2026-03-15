<script setup lang="ts">
import PageHeader from '~/components/common/PageHeader.vue'
defineEmits<{
 (e: 'create'): void
}>
</script>
<template>
 <PageHeader
 icon="lucide--workflow"
 icon-gradient="from-teal-500/20 to-cyan-500/10"
 icon-color="text-teal-500"
 title="工作流"
 description="管理和自动化您的开发工作流"
 >
 <template #actions>
 <button class="btn btn-primary" @click="$emit('create')">
 <span class="icon-[lucide--plus]" />
 新建工作流
 </button>
 </template>
 </PageHeader>
</template>
