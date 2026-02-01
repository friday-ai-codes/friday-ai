<script setup lang="ts">
import { Button } from '~/components/ui/button'
import { GitBranch } from 'lucide-vue-next'
defineEmits<{
 (e: 'create'): void
}>
</script>
<template>
 <div class="flex min-h-[400px] flex-col items-center justify-center rounded-lg border border-dashed text-center animate-in fade-in-50">
 <div class="mx-auto flex w-12 items-center justify-center rounded-full bg-muted/50 mb-4">
 <GitBranch class=" w-6 text-muted-foreground" />
 </div>
 <h3 class="text-lg font-semibold tracking-tight">No workflows found</h3>
 <p class="mb-6 mt-2 text-sm text-muted-foreground max-w-sm">
 Get started by creating your first automation workflow. Streamline your development process with custom automation.
 </p>
 <Button @click="$emit('create')">
 Create Workflow
 </Button>
 </div>
</template>
