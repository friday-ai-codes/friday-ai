<script setup lang="ts">
import { VueFinalModal } from 'vue-final-modal'
interface Props {
 title?: string
 size?: 'sm' | 'md' | 'lg' | 'xl' | '2xl' | 'full'
 showClose?: boolean
 closeOnClickOutside?: boolean
 closeOnEsc?: boolean
 contentPadding?: boolean
}
const props = withDefaults(defineProps<Props>, {
 title: '',
 size: 'md',
 showClose: true,
 closeOnClickOutside: true,
 closeOnEsc: true,
 contentPadding: true,
})
const emit = defineEmits<{
 confirm: [data?: unknown]
 cancel:
 closed:
}>
const sizeClasses: Record<string, string> = {
 'sm': 'max-w-sm',
 'md': 'max-w-md',
 'lg': 'max-w-lg',
 'xl': 'max-w-xl',
 '2xl': 'max-w-2xl',
 'full': 'max-w-4xl',
}
function handleCancel {
 emit('cancel')
}
</script>
<template>
 <VueFinalModal
 class="flex justify-center items-center"
 content-class="flex flex-col bg-card rounded-2xl shadow-lg border border-border/50 w-full mx-4":content-style="{ maxWidth: sizeClasses[props.size] ? undefined: props.size }"
 overlay-transition="vfm-fade"
 content-transition="vfm-zoom":click-to-close="closeOnClickOutside":esc-to-close="closeOnEsc"
 @closed="emit('closed')"
 >
 <!-- Header -->
 <div v-if="title || showClose || $slots.header" class="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700">
 <slot name="header">
 <h3 class="text-lg font-semibold text-gray-900 dark:text-gray-100">
 {{ title }}
 </h3>
 </slot>
 <button
 v-if="showClose"
 type="button"
 class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
 @click="handleCancel"
 >
 <svg class="w-5 " fill="none" stroke="currentColor" viewBox="0 0 24 24">
 <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
 </svg>
 </button>
 </div>
 <!-- Body -->
 <div class="flex-1 overflow-y-auto":class="{ 'px-6 py-4': contentPadding }">
 <slot />
 </div>
 <!-- Footer -->
 <div v-if="$slots.footer" class="px-6 py-4 border-t border-gray-200 dark:border-gray-700">
 <slot name="footer" />
 </div>
 </VueFinalModal>
</template>
<style>
/* shadcn 风格的缩放弹出动画 */
.vfm-zoom-enter-active,
.vfm-zoom-leave-active {
 transition: all 0.15s cubic-bezier(0.16, 1, 0.3, 1);
}
.vfm-zoom-enter-from,
.vfm-zoom-leave-to {
 opacity: 0;
 transform: scale(0.95);
}
.vfm-zoom-enter-to,
.vfm-zoom-leave-from {
 opacity: 1;
 transform: scale(1);
}
</style>
