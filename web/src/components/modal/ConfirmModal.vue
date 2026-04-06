<script setup lang="ts">
import { ref } from 'vue'
import { VueFinalModal } from 'vue-final-modal'
import { Button } from '~/components/ui/button'
interface Props {
 title?: string
 message: string
 confirmText?: string
 cancelText?: string
 confirmVariant?: 'default' | 'destructive' | 'outline' | 'secondary' | 'ghost' | 'link'
 loading?: boolean
}
const props = withDefaults(defineProps<Props>, {
 title: '确认操作',
 confirmText: '确认',
 cancelText: '取消',
 confirmVariant: 'default',
 loading: false,
})
const emit = defineEmits<{
 confirm: [value: boolean]
 cancel:
 closed:
}>
const isLoading = ref(props.loading)
async function handleConfirm {
 isLoading.value = true
 emit('confirm', true)
}
function handleCancel {
 emit('cancel')
}
</script>
<template>
 <VueFinalModal
 class="flex justify-center items-center"
 content-class="flex flex-col bg-card rounded-2xl shadow-lg border border-border/50 max-w-md w-full mx-4"
 overlay-transition="vfm-fade"
 content-transition="vfm-zoom"
 @closed="emit('closed')"
 >
 <!-- Header -->
 <div class="px-6 py-4 border-b border-border/30">
 <h3 class="text-lg font-semibold text-foreground">
 {{ title }}
 </h3>
 </div>
 <!-- Body -->
 <div class="px-6 py-4">
 <p class="text-muted-foreground">
 {{ message }}
 </p>
 </div>
 <!-- Footer -->
 <div class="flex justify-end gap-3 px-6 py-4 border-t border-border/30">
 <Button variant="outline":disabled="isLoading" @click="handleCancel">
 {{ cancelText }}
 </Button>
 <Button:variant="confirmVariant":disabled="isLoading" @click="handleConfirm">
 <span v-if="isLoading" class="mr-2">
 <svg class="animate-spin w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
 <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
 <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 work-item.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
 </svg>
 </span>
 {{ confirmText }}
 </Button>
 </div>
 </VueFinalModal>
</template>
