<script setup lang="ts">
import type { NodePort } from '~/stores/useNodeTypesStore'
import { ArrowDownToLine, ArrowUpFromLine, Copy } from 'lucide-vue-next'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import {
 Tooltip,
 TooltipContent,
 TooltipProvider,
 TooltipTrigger,
} from '~/components/ui/tooltip'
import { useToast } from '~/composables/useToast'
interface Props {
 /** 输入端口列表 */
 inputs: NodePort
 /** 输出端口列表 */
 outputs: NodePort
 /** 节点 ID（用于生成变量路径） */
 nodeId: string
}
const props = defineProps<Props>
const { toast } = useToast
// 端口类型颜色映射
const typeColors: Record<string, string> = {
 string: 'bg-blue-500/10 text-blue-600',
 object: 'bg-purple-500/10 text-purple-600',
 array: 'bg-amber-500/10 text-amber-600',
 number: 'bg-emerald-500/10 text-emerald-600',
 boolean: 'bg-rose-500/10 text-rose-600',
 any: 'bg-gray-500/10 text-gray-600',
}
function getTypeColor(type: string): string {
 return typeColors[type.toLowerCase] || typeColors.any
}
function copyVariablePath(portName: string) {
 const path = `{{nodes.${props.nodeId}.${portName}}}`
 navigator.clipboard.writeText(path)
 toast({
 title: '已复制',
 description: path,
 })
}
</script>
<template>
 <div class="space-y-4">
 <!-- 输入端口 -->
 <div v-if="inputs.length > 0" class="space-y-2">
 <div class="flex items-center gap-2 text-sm font-medium text-muted-foreground">
 <ArrowDownToLine class="w-4 text-blue-500" />
 <span>输入</span>
 </div>
 <div class="rounded-lg bg-muted/30 border border-border/50 divide-y divide-border/50">
 <div
 v-for="port in inputs":key="port.name"
 class=" first:rounded-t-lg last:rounded-b-lg"
 >
 <div class="flex items-center justify-between">
 <div class="flex items-center gap-2">
 <span class="text-sm font-medium">{{ port.label }}</span>
 <Badge v-if="port.required" variant="outline" class="text-[10px] px-1.5 py-0">
 必填
 </Badge>
 </div>
 <Badge:class="getTypeColor(port.type)" class="text-[10px] font-normal">
 {{ port.type }}
 </Badge>
 </div>
 <p v-if="port.description" class="text-xs text-muted-foreground mt-1">
 {{ port.description }}
 </p>
 </div>
 </div>
 </div>
 <!-- 输出端口 -->
 <div v-if="outputs.length > 0" class="space-y-2">
 <div class="flex items-center gap-2 text-sm font-medium text-muted-foreground">
 <ArrowUpFromLine class="w-4 text-green-500" />
 <span>输出</span>
 </div>
 <div class="rounded-lg bg-muted/30 border border-border/50 divide-y divide-border/50">
 <div
 v-for="port in outputs":key="port.name"
 class=" first:rounded-t-lg last:rounded-b-lg group"
 >
 <div class="flex items-center justify-between">
 <div class="flex items-center gap-2">
 <span class="text-sm font-medium">{{ port.label }}</span>
 </div>
 <Badge:class="getTypeColor(port.type)" class="text-[10px] font-normal">
 {{ port.type }}
 </Badge>
 </div>
 <p v-if="port.description" class="text-xs text-muted-foreground mt-1">
 {{ port.description }}
 </p>
 <!-- 变量路径提示 -->
 <div class="flex items-center justify-between mt-2 pt-2 border-t border-border/30">
 <code class="text-[10px] text-muted-foreground font-mono">
 {{ `\{\{nodes.${nodeId}.${port.name}\}\}` }}
 </code>
 <TooltipProvider>
 <Tooltip>
 <TooltipTrigger as-child>
 <Button
 variant="ghost"
 size="icon"
 class=" w-6 opacity-0 group-hover:opacity-100 transition-opacity"
 @click="copyVariablePath(port.name)"
 >
 <Copy class="w-3 " />
 </Button>
 </TooltipTrigger>
 <TooltipContent>
 <p>复制变量路径</p>
 </TooltipContent>
 </Tooltip>
 </TooltipProvider>
 </div>
 </div>
 </div>
 </div>
 <!-- 空状态 -->
 <div v-if="inputs.length === 0 && outputs.length === 0" class="py-4 text-center">
 <p class="text-sm text-muted-foreground">
 该节点没有定义端口
 </p>
 </div>
 </div>
</template>
