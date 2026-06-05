<script setup lang="ts">
import { GitBranch } from 'lucide-vue-next'
import { Button } from '~/components/ui/button'

defineEmits<{
  (e: 'create'): void
}>()
</script>

<template>
  <div class="bg-background flex min-h-[400px] flex-col items-center justify-center rounded-lg border border-dashed p-8 text-center animate-in fade-in-50">
    <div class="bg-muted/50 mx-auto flex h-20 w-20 items-center justify-center rounded-full">
      <GitBranch class="text-muted-foreground h-10 w-10" />
    </div>
    <h3 class="mt-4 text-lg font-semibold">
      暂无工作流
    </h3>
    <p class="text-muted-foreground mb-4 mt-2 max-w-sm text-sm">
      创建您的第一个工作流，开始自动化开发流程
    </p>
    <Button @click="$emit('create')">
      新建工作流
    </Button>
  </div>
</template>
