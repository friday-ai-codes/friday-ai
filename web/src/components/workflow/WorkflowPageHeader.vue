<script setup lang="ts">
import { Plus, Search } from 'lucide-vue-next'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
defineEmits<{
 (e: 'create'): void
 (e: 'search', value: string): void
}>
</script>
<template>
 <div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
 <div>
 <h2 class="text-2xl font-bold tracking-tight">工作流</h2>
 <p class="text-muted-foreground text-sm">
 管理和自动化您的开发工作流
 </p>
 </div>
 <div class="flex items-center gap-2">
 <div class="relative w-full sm:w-64">
 <Search class="text-muted-foreground absolute left-2.5 top-2.5 w-4" />
 <Input
 type="search"
 placeholder="搜索工作流..."
 class="pl-9"
 @input="$emit('search', ($event.target as HTMLInputElement).value)"
 />
 </div>
 <Button @click="$emit('create')">
 <Plus class="mr-2 w-4" />
 新建工作流
 </Button>
 </div>
 </div>
</template>
