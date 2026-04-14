<script setup lang="ts">
import type { DialogContentEmits, DialogContentProps } from 'reka-ui'
import type { HTMLAttributes } from 'vue'
import { reactiveOmit } from '@vueuse/core'
import { X } from 'lucide-vue-next'
import {
 DialogClose,
 DialogContent,
 DialogOverlay,
 DialogPortal,
 useForwardPropsEmits,
} from 'reka-ui'
import { computed } from 'vue'
import { cn } from '~/lib/utils'
interface SheetContentProps extends DialogContentProps {
 class?: HTMLAttributes['class']
 side?: 'top' | 'bottom' | 'left' | 'right'
}
const props = withDefaults(defineProps<SheetContentProps>, {
 side: 'right',
})
const emits = defineEmits<DialogContentEmits>
const delegatedProps = reactiveOmit(props, 'class', 'side')
const forwarded = useForwardPropsEmits(delegatedProps, emits)
const sideClasses = computed( => {
 const map: Record<string, string> = {
 top: 'inset-x-0 top-0 border-b data-[state=closed]:slide-out-to-top data-[state=open]:slide-in-from-top',
 bottom: 'inset-x-0 bottom-0 border-t data-[state=closed]:slide-out-to-bottom data-[state=open]:slide-in-from-bottom',
 left: 'inset-y-0 left-0 h-full w-3/4 border-r sm:max-w-sm data-[state=closed]:slide-out-to-left data-[state=open]:slide-in-from-left',
 right: 'inset-y-0 right-0 h-full w-3/4 border-l sm:max-w-sm data-[state=closed]:slide-out-to-right data-[state=open]:slide-in-from-right',
 }
 return map[props.side] ?? map.right
})
</script>
<template>
 <DialogPortal>
 <DialogOverlay
 class="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0"
 />
 <DialogContent
 v-bind="forwarded":class="cn('fixed z-50 gap-4 bg-background shadow-lg transition ease-in-out data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:duration-300 data-[state=open]:duration-500', sideClasses, props.class)"
 >
 <slot />
 <DialogClose
 class="absolute right-4 top-4 rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:pointer-events-none data-[state=open]:bg-secondary"
 >
 <X class="w-4 " />
 <span class="sr-only">Close</span>
 </DialogClose>
 </DialogContent>
 </DialogPortal>
</template>
