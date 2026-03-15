<script setup lang="ts">
import { Button } from '~/components/ui/button'
import PageHeader from '~/components/common/PageHeader.vue'
defineEmits<{
 (e: 'create'): void
}>
</script>
<template>
 <PageHeader
 icon="lucide--workflow"
 icon-gradient="from-amber-500/20 to-orange-500/10"
 icon-color="text-amber-500"
 title="工作流"
 description="管理和自动化您的开发工作流"
 >
 <template #actions>
 <Button class="group relative overflow-hidden" @click="$emit('create')">
 <span class="absolute inset-0 bg-gradient-to-r from-white/0 via-white/20 to-white/0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700" />
 <span class="icon-[lucide--plus] mr-2" />
 新建工作流
 </Button>
 </template>
 </PageHeader>
</template>
