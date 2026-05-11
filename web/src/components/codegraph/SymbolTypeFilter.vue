<script setup lang="ts">
import { Input } from '~/components/ui/input'
import { ToggleGroup, ToggleGroupItem } from '~/components/ui/toggle-group'
const props = defineProps<{
 modelValue: string
 nameQuery?: string
 filePathQuery?: string
}>
const emit = defineEmits<{
 'update:modelValue': [types: string]
 'update:nameQuery': [name: string]
 'update:filePathQuery': [path: string]
}>
const SYMBOL_TYPES = [
 { value: 'FUNCTION', label: '函数', icon: 'icon-[lucide--function-square]' },
 { value: 'CLASS', label: '类', icon: 'icon-[lucide--box]' },
 { value: 'METHOD', label: '方法', icon: 'icon-[lucide--braces]' },
 { value: 'VARIABLE', label: '变量', icon: 'icon-[lucide--variable]' },
]
</script>
<template>
 <div class="flex flex-wrap items-center gap-3">
 <ToggleGroup
 type="multiple":model-value="props.modelValue"
 class="gap-1"
 @update:model-value="emit('update:modelValue', $event as string)"
 >
 <ToggleGroupItem
 v-for="type in SYMBOL_TYPES":key="type.value":value="type.value"
 class="min-h-[36px] text-xs gap-1.5 px-2.5"
 >
 <span:class="[type.icon, 'w-3.5 .5']" />
 {{ type.label }}
 </ToggleGroupItem>
 </ToggleGroup>
 <Input:model-value="props.nameQuery ?? ''"
 placeholder="搜索名称..."
 class="w-48 text-sm"
 @update:model-value="emit('update:nameQuery', String($event))"
 />
 <Input:model-value="props.filePathQuery ?? ''"
 placeholder="所有文件"
 class="w-48 text-sm font-mono"
 @update:model-value="emit('update:filePathQuery', String($event))"
 >
 <template #prefix>
 <span class="icon-[lucide--folder] text-muted-foreground w-3.5 .5" />
 </template>
 </Input>
 </div>
</template>
