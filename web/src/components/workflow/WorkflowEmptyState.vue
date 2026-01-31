<script setup lang="ts">
import { GitBranch } from 'lucide-vue-next'
import { Button } from '~/components/ui/button'
defineEmits<{
 (e: 'create'): void
}>
</script>
<template>
 <div class="bg-background flex min-h-[400px] flex-col items-center justify-center rounded-lg border border-dashed text-center animate-in fade-in-50">
 <div class="bg-muted/50 mx-auto flex w-20 items-center justify-center rounded-full">
 <GitBranch class="text-muted-foreground w-10" />
 </div>
 <h3 class="mt-4 text-lg font-semibold">No workflows found</h3>
 <p class="text-muted-foreground mb-4 mt-2 max-w-sm text-sm">
 Get started by creating your first automation workflow.
 </p>
 <Button @click="$emit('create')">
 Create Workflow
 </Button>
 </div>
</template>
