<script setup lang="ts">
import { ref } from 'vue'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Plus, Search } from 'lucide-vue-next'
const emit = defineEmits<{
 (e: 'create'): void
 (e: 'search', value: string): void
}>
const searchQuery = ref('')
function onInput(event: Event) {
 // Input component emits update:modelValue, but native input event is also useful
 // or we can just watch searchQuery.
 // For standard shadcn-vue Input, v-model works.
 emit('search', searchQuery.value)
}
</script>
<template>
 <div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
 <div class="space-y-1">
 <h2 class="text-2xl font-bold tracking-tight">Workflows</h2>
 <p class="text-muted-foreground text-sm">
 Manage and automate your development workflows
 </p>
 </div>
 <div class="flex items-center gap-2">
 <div class="relative w-full sm:w-64">
 <Search class="absolute left-2 top-2.5 w-4 text-muted-foreground pointer-events-none" />
 <Input
 v-model="searchQuery"
 placeholder="Search workflows..."
 class="pl-8"
 @input="onInput"
 />
 </div>
 <Button @click="$emit('create')">
 <Plus class="mr-2 w-4" />
 New Workflow
 </Button>
 </div>
 </div>
</template>
