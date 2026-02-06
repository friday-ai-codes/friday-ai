<script setup lang="ts">
import { Button } from '~/components/ui/button'
import {
 Tooltip,
 TooltipContent,
 TooltipProvider,
 TooltipTrigger,
} from '~/components/ui/tooltip'
import { Separator } from '~/components/ui/separator'
/**
 * EditorToolbar Component
 *
 * A glassmorphism-styled toolbar for the X6 workflow editor.
 * Provides undo/redo controls with keyboard shortcut hints,
 * and zoom controls for canvas navigation.
 */
interface Props {
 /** Whether undo is available */
 canUndo: boolean
 /** Whether redo is available */
 canRedo: boolean
}
defineProps<Props>
const emit = defineEmits<{
 /** Emitted when undo button is clicked */
 undo:
 /** Emitted when redo button is clicked */
 redo:
 /** Emitted when zoom in button is clicked */
 zoomIn:
 /** Emitted when zoom out button is clicked */
 zoomOut:
 /** Emitted when fit to window button is clicked */
 zoomFit:
}>
</script>
<template>
 <TooltipProvider:delay-duration="300">
 <div
 class="flex items-center gap-1 rounded-lg bg-card/80 backdrop-blur-sm border border-border/50 shadow-lg"
 >
 <!-- Undo button -->
 <Tooltip>
 <TooltipTrigger as-child>
 <Button
 variant="ghost"
 size="icon-sm":disabled="!canUndo"
 @click="emit('undo')"
 >
 <span class="icon-[lucide--undo-2] text-lg" />
 </Button>
 </TooltipTrigger>
 <TooltipContent side="bottom">
 <p>撤销 (Ctrl+Z)</p>
 </TooltipContent>
 </Tooltip>
 <!-- Redo button -->
 <Tooltip>
 <TooltipTrigger as-child>
 <Button
 variant="ghost"
 size="icon-sm":disabled="!canRedo"
 @click="emit('redo')"
 >
 <span class="icon-[lucide--redo-2] text-lg" />
 </Button>
 </TooltipTrigger>
 <TooltipContent side="bottom">
 <p>重做 (Ctrl+Shift+Z)</p>
 </TooltipContent>
 </Tooltip>
 <!-- Divider between undo/redo and zoom controls -->
 <Separator orientation="vertical" class=" mx-1" />
 <!-- Zoom in button -->
 <Tooltip>
 <TooltipTrigger as-child>
 <Button
 variant="ghost"
 size="icon-sm"
 @click="emit('zoomIn')"
 >
 <span class="icon-[lucide--zoom-in] text-lg" />
 </Button>
 </TooltipTrigger>
 <TooltipContent side="bottom">
 <p>放大</p>
 </TooltipContent>
 </Tooltip>
 <!-- Zoom out button -->
 <Tooltip>
 <TooltipTrigger as-child>
 <Button
 variant="ghost"
 size="icon-sm"
 @click="emit('zoomOut')"
 >
 <span class="icon-[lucide--zoom-out] text-lg" />
 </Button>
 </TooltipTrigger>
 <TooltipContent side="bottom">
 <p>缩小</p>
 </TooltipContent>
 </Tooltip>
 <!-- Zoom fit button -->
 <Tooltip>
 <TooltipTrigger as-child>
 <Button
 variant="ghost"
 size="icon-sm"
 @click="emit('zoomFit')"
 >
 <span class="icon-[lucide--maximize] text-lg" />
 </Button>
 </TooltipTrigger>
 <TooltipContent side="bottom">
 <p>适应窗口</p>
 </TooltipContent>
 </Tooltip>
 </div>
 </TooltipProvider>
</template>
