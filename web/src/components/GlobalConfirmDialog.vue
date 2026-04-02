<script setup lang="ts">
import { useConfirmDialog } from '~/composables/useConfirmDialog'
import {
 AlertDialog,
 AlertDialogAction,
 AlertDialogCancel,
 AlertDialogContent,
 AlertDialogDescription,
 AlertDialogFooter,
 AlertDialogHeader,
 AlertDialogTitle,
} from '~/components/ui/alert-dialog'
const { isOpen, options, handleConfirm, handleCancel } = useConfirmDialog
</script>
<template>
 <AlertDialog:open="isOpen" @update:open="(v) => { if (!v) handleCancel }">
 <AlertDialogContent>
 <AlertDialogHeader>
 <AlertDialogTitle>{{ options.title || '确认操作' }}</AlertDialogTitle>
 <AlertDialogDescription>{{ options.description }}</AlertDialogDescription>
 </AlertDialogHeader>
 <AlertDialogFooter>
 <AlertDialogCancel @click="handleCancel">
 {{ options.cancelText || '取消' }}
 </AlertDialogCancel>
 <AlertDialogAction:class="options.variant === 'destructive' ? 'bg-destructive text-destructive-foreground hover:bg-destructive/90': ''"
 @click="handleConfirm"
 >
 {{ options.confirmText || '确认' }}
 </AlertDialogAction>
 </AlertDialogFooter>
 </AlertDialogContent>
 </AlertDialog>
</template>
