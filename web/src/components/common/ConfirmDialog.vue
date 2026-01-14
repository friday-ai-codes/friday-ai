<script setup lang="ts">
import {
 AlertDialog,
 AlertDialogCancel,
 AlertDialogContent,
 AlertDialogDescription,
 AlertDialogFooter,
 AlertDialogHeader,
 AlertDialogTitle
} from '~/components/ui/alert-dialog';
import { Button } from '~/components/ui/button';
const props = withDefaults(defineProps<{
 open: boolean
 title?: string
 description?: string
 confirmText?: string
 cancelText?: string
 variant?: 'default' | 'destructive'
 loading?: boolean
}>, {
 title: '确认操作',
 description: '确定要执行此操作吗？',
 confirmText: '确认',
 cancelText: '取消',
 variant: 'default',
 loading: false,
})
const emit = defineEmits<{
 'update:open': [value: boolean]
 confirm:
 cancel:
}>
function handleConfirm {
 emit('confirm')
}
function handleCancel {
 emit('cancel')
 emit('update:open', false)
}
function handleOpenChange(value: boolean) {
 emit('update:open', value)
 if (!value) {
 emit('cancel')
 }
}
</script>
<template>
 <AlertDialog:open="open" @update:open="handleOpenChange">
 <AlertDialogContent>
 <AlertDialogHeader>
 <AlertDialogTitle>{{ title }}</AlertDialogTitle>
 <AlertDialogDescription>
 {{ description }}
 </AlertDialogDescription>
 </AlertDialogHeader>
 <AlertDialogFooter>
 <AlertDialogCancel:disabled="loading" @click="handleCancel">
 {{ cancelText }}
 </AlertDialogCancel>
 <Button:variant="variant":disabled="loading"
 @click="handleConfirm"
 >
 <span v-if="loading" class="mr-2 animate-spin">⏳</span>
 {{ confirmText }}
 </Button>
 </AlertDialogFooter>
 </AlertDialogContent>
 </AlertDialog>
</template>