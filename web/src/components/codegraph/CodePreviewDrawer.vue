<!-- Plan 占位：完整 Sheet + 内容查找由 Plan 重写 (work item §5.5) -->
<script setup lang="ts">
import type { PlaygroundSearchResponse } from '~/api/codegraph'
import {
 Sheet,
 SheetContent,
 SheetDescription,
 SheetHeader,
 SheetTitle,
} from '~/components/ui/sheet'
const props = defineProps<{
 open: boolean
 chunkId: string | null
 searchResult?: PlaygroundSearchResponse | null
}>
const emit = defineEmits<{
 (e: 'update:open', value: boolean): void
}>
const internalOpen = computed({
 get: => props.open,
 set: (value: boolean) => emit('update:open', value),
})
</script>
<template>
 <Sheet v-model:open="internalOpen">
 <SheetContent side="right" class="w-[560px] max-w-[80vw]">
 <SheetHeader>
 <SheetTitle>代码片段预览</SheetTitle>
 <SheetDescription>
 Plan 落地完整内容预览
 </SheetDescription>
 </SheetHeader>
 <div class="mt-4 text-xs text-muted-foreground font-mono">
 chunk_id: {{ chunkId ?? '—' }}
 </div>
 </SheetContent>
 </Sheet>
</template>
