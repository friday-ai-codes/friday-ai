<script setup lang="ts">
import type { NodePort } from '~/stores/useNodeTypesStore'
import { ArrowDownToLine, ArrowUpFromLine, Copy } from 'lucide-vue-next'
import { computed } from 'vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '~/components/ui/tooltip'
import { useToast } from '~/composables/useToast'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
import { buildNodeRef } from '~/utils/variableRef'

interface Props {
  /** 输入端口列表 */
  inputs: NodePort[]
  /** 输出端口列表 */
  outputs: NodePort[]
  /** 节点 ID（UUID，组件内查表换取权威 shortId 生成变量路径） */
  nodeId: string
}

const props = defineProps<Props>()
const { success, error } = useToast()

const workflowsStore = useWorkflowsStore()

/**
 * 由 props.nodeId（UUID）查 store 节点的权威 shortId。
 * 查不到属异常态（保存后 store 节点必有 shortId）——禁止生成引用，
 * 绝不回退 props.nodeId 产 UUID 形式引用（锁定决策 VAR-03）。
 */
const shortId = computed(() => workflowsStore.getNodeById(props.nodeId)?.shortId ?? '')

// 端口类型颜色映射
const typeColors: Record<string, string> = {
  string: 'bg-primary/10 text-primary',
  object: 'bg-primary/10 text-primary',
  array: 'bg-primary/10 text-primary',
  number: 'bg-primary/10 text-primary',
  boolean: 'bg-primary/10 text-primary',
  any: 'bg-muted text-muted-foreground',
}

function getTypeColor(type: string): string {
  return typeColors[type.toLowerCase()] || typeColors.any
}

function copyVariablePath(portName: string) {
  if (!shortId.value) {
    error('节点缺少 short_id，请先保存工作流')
    return
  }
  const path = buildNodeRef(shortId.value, portName)
  navigator.clipboard.writeText(path)
  success('已复制', path)
}
</script>

<template>
  <div class="space-y-4">
    <!-- 输入端口 -->
    <div v-if="inputs.length > 0" class="space-y-2">
      <div class="flex items-center gap-2 text-sm font-medium text-muted-foreground">
        <ArrowDownToLine class="w-4 h-4 text-primary" />
        <span>输入</span>
      </div>
      <div class="rounded-lg bg-muted/30 border border-border/50 divide-y divide-border/50">
        <div
          v-for="port in inputs"
          :key="port.name"
          class="p-3 first:rounded-t-lg last:rounded-b-lg"
        >
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <span class="text-sm font-medium">{{ port.label }}</span>
              <Badge v-if="port.required" variant="outline" class="text-[10px] px-1.5 py-0">
                必填
              </Badge>
            </div>
            <span :class="getTypeColor(port.type)" class="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-normal">
              {{ port.type }}
            </span>
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
        <ArrowUpFromLine class="w-4 h-4 text-green-500" />
        <span>输出</span>
      </div>
      <div class="rounded-lg bg-muted/30 border border-border/50 divide-y divide-border/50">
        <div
          v-for="port in outputs"
          :key="port.name"
          class="p-3 first:rounded-t-lg last:rounded-b-lg group"
        >
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <span class="text-sm font-medium">{{ port.label }}</span>
            </div>
            <span :class="getTypeColor(port.type)" class="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-normal">
              {{ port.type }}
            </span>
          </div>
          <p v-if="port.description" class="text-xs text-muted-foreground mt-1">
            {{ port.description }}
          </p>
          <!-- 变量路径提示 -->
          <div class="flex items-center justify-between mt-2 pt-2 border-t border-border/30">
            <code class="text-[10px] text-muted-foreground font-mono">
              {{ shortId ? buildNodeRef(shortId, port.name) : '保存工作流后可用' }}
            </code>
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger as-child>
                  <Button
                    variant="ghost"
                    size="icon"
                    class="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity"
                    @click="copyVariablePath(port.name)"
                  >
                    <Copy class="w-3 h-3" />
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
