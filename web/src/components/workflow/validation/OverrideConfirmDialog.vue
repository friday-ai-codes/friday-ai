<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Button } from '~/components/ui/button'
import { Checkbox } from '~/components/ui/checkbox'
import {
 Dialog,
 DialogContent,
 DialogDescription,
 DialogFooter,
 DialogHeader,
 DialogTitle,
} from '~/components/ui/dialog'
export interface OverrideField {
 key: string
 label: string
 currentValue: string
 newValue: string
}
const props = defineProps<{
 open: boolean
 fields: OverrideField
}>
const emit = defineEmits<{
 'update:open': [value: boolean]
 'confirm': [selectedKeys: string]
 'cancel':
}>
// Track selected fields
const selectedKeys = ref<Set<string>>(new Set)
// Initialize all fields as selected when dialog opens
watch( => props.open, (isOpen) => {
 if (isOpen) {
 selectedKeys.value = new Set(props.fields.map(f => f.key))
 }
})
// Count of selected fields
const selectedCount = computed( => selectedKeys.value.size)
// Toggle field selection
function toggleField(key: string, checked: boolean) {
 if (checked) {
 selectedKeys.value.add(key)
 } else {
 selectedKeys.value.delete(key)
 }
 // Force reactivity
 selectedKeys.value = new Set(selectedKeys.value)
}
// Handle confirm
function handleConfirm {
 emit('confirm', Array.from(selectedKeys.value))
 emit('update:open', false)
}
// Handle cancel
function handleCancel {
 emit('cancel')
 emit('update:open', false)
}
</script>
<template>
 <Dialog:open="open" @update:open="$emit('update:open', $event)">
 <DialogContent class="sm:max-w-md">
 <DialogHeader>
 <DialogTitle>确认覆盖字段</DialogTitle>
 <DialogDescription>
 以下字段已有值，选择要覆盖的字段：
 </DialogDescription>
 </DialogHeader>
 <div class="space-y-3 py-4">
 <div
 v-for="field in fields":key="field.key"
 class="flex items-start gap-3 rounded-xl bg-muted/50 border border-border/50"
 >
 <Checkbox:id="`field-${field.key}`":checked="selectedKeys.has(field.key)"
 class="mt-0.5"
 @update:checked="toggleField(field.key, $event)"
 />
 <label:for="`field-${field.key}`" class="flex-1 cursor-pointer space-y-1.5">
 <div class="text-sm font-medium">{{ field.label }}</div>
 <div class="text-xs space-y-1">
 <div class="flex items-center gap-2">
 <span class="text-muted-foreground shrink-0">当前:</span>
 <code class="px-1.5 py-0.5 rounded bg-background/80 text-destructive/80 truncate max-w-[200px]">
 {{ field.currentValue }}
 </code>
 </div>
 <div class="flex items-center gap-2">
 <span class="text-muted-foreground shrink-0">新值:</span>
 <code class="px-1.5 py-0.5 rounded bg-background/80 text-primary truncate max-w-[200px]">
 {{ field.newValue }}
 </code>
 </div>
 </div>
 </label>
 </div>
 </div>
 <DialogFooter class="gap-2 sm:gap-0">
 <Button variant="outline" @click="handleCancel">
 取消
 </Button>
 <Button:disabled="selectedCount === 0" @click="handleConfirm">
 确认覆盖 ({{ selectedCount }})
 </Button>
 </DialogFooter>
 </DialogContent>
 </Dialog>
</template>
