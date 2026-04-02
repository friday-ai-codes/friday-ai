<script setup lang="ts">
import { Button } from '~/components/ui/button'
import { Switch } from '~/components/ui/switch'
interface Props {
 wsDisconnected: boolean
 isDebugExecution: boolean
 isActiveStatus: boolean
 isBreakpointMode: boolean
 debugPausedNodeName: string | null
}
defineProps<Props>
const emit = defineEmits<{
 reconnectWs:
 cancelDebug:
 'update:isBreakpointMode': [value: boolean]
}>
</script>
<template>
 <!-- WebSocket 断线警告条 -->
 <Transition
 enter-active-class="transition-all duration-300 ease-out"
 enter-from-class="-translate-y-2 opacity-0"
 enter-to-class="translate-y-0 opacity-100"
 leave-active-class="transition-all duration-200 ease-in"
 leave-from-class="translate-y-0 opacity-100"
 leave-to-class="-translate-y-2 opacity-0"
 >
 <div
 v-if="wsDisconnected"
 class="shrink-0 flex items-center justify-center gap-2 bg-amber-500/90 backdrop-blur-sm text-white text-sm px-4 py-1.5 z-10"
 >
 <span class="icon-[lucide--wifi-off] w-4 " />
 <span>连接已断开，状态可能不是最新</span>
 <button
 class="ml-2 text-xs underline underline-offset-2 hover:no-underline"
 @click="emit('reconnectWs')"
 >
 重新连接
 </button>
 </div>
 </Transition>
 <!-- Phase: 调试模式横幅 -->
 <Transition
 enter-active-class="transition-all duration-300 ease-out"
 enter-from-class="-translate-y-2 opacity-0"
 enter-to-class="translate-y-0 opacity-100"
 leave-active-class="transition-all duration-200 ease-in"
 leave-from-class="translate-y-0 opacity-100"
 leave-to-class="-translate-y-2 opacity-0"
 >
 <div
 v-if="isDebugExecution && isActiveStatus"
 class="shrink-0 flex items-center justify-between bg-amber-500/90 backdrop-blur-sm text-white px-4 py-2 z-10"
 >
 <div class="flex items-center gap-2 text-sm">
 <span class="icon-[lucide--bug] w-4 " />
 <span class="font-medium">调试模式</span>
 <!-- Phase: 逐步/断点模式切换 -->
 <div class="flex items-center gap-1.5 ml-3 pl-3 border-l border-white/30">
 <span class="text-xs text-white/70">逐步</span>
 <Switch:checked="isBreakpointMode"
 class="data-[state=checked]:bg-white/30 data-[state=unchecked]:bg-white/20 w-7"
 @update:checked="emit('update:isBreakpointMode', $event)"
 />
 <span class="text-xs text-white/70">断点</span>
 </div>
 <span v-if="debugPausedNodeName" class="text-white/80">
 · 暂停在「{{ debugPausedNodeName }}」
 </span>
 </div>
 <Button
 variant="ghost"
 size="sm"
 class="text-white hover:bg-white/20 text-xs"
 @click="emit('cancelDebug')"
 >
 <span class="icon-[lucide--square] w-3.5 .5 mr-1" />
 终止调试
 </Button>
 </div>
 </Transition>
</template>
