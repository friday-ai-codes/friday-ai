<script setup lang="ts">
import type { CostBreakdown } from '~/types/execution'
/**
 * ProviderCostTable — 按 Provider 分组的 Token 消耗统计表格
 *
 * 从 CostBreakdown 数据中提取模型信息，根据模型名推断 Provider 类型，
 * 按 Provider 分组聚合 Token 消耗和成本。
 */
import { computed } from 'vue'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '~/components/ui/table'

const props = defineProps<{
  costData: CostBreakdown | null
}>()

interface ProviderGroup {
  providerType: string
  displayName: string
  inputTokens: number
  outputTokens: number
  totalCost: string
}

/** 根据模型名推断 Provider */
function inferProvider(model: string): { type: string, name: string } {
  const m = model.toLowerCase()
  if (m.startsWith('claude'))
    return { type: 'anthropic', name: 'Anthropic' }
  if (m.startsWith('gpt-') || m.startsWith('o1') || m.startsWith('o3'))
    return { type: 'openai', name: 'OpenAI' }
  if (m.startsWith('gemini'))
    return { type: 'google', name: 'Google' }
  return { type: 'other', name: '其他' }
}

/** 千位分隔符格式化 */
function formatTokens(n: number): string {
  return n.toLocaleString('en-US')
}

/** 按 Provider 分组聚合 */
const providerGroups = computed<ProviderGroup[]>(() => {
  if (!props.costData?.nodes?.length)
    return []

  const groupMap = new Map<string, { name: string, input: number, output: number, cost: number }>()

  for (const node of props.costData.nodes) {
    for (const [modelId, modelData] of Object.entries(node.models)) {
      const { type, name } = inferProvider(modelId)
      const existing = groupMap.get(type)
      if (existing) {
        existing.input += modelData.input_tokens
        existing.output += modelData.output_tokens
        existing.cost += Number.parseFloat(modelData.total_cost_usd)
      }
      else {
        groupMap.set(type, {
          name,
          input: modelData.input_tokens,
          output: modelData.output_tokens,
          cost: Number.parseFloat(modelData.total_cost_usd),
        })
      }
    }
  }

  return Array.from(groupMap.entries()).map(([type, data]) => ({
    providerType: type,
    displayName: data.name,
    inputTokens: data.input,
    outputTokens: data.output,
    totalCost: data.cost.toFixed(2),
  }))
})

/** 汇总数据 */
const summary = computed(() => {
  if (!providerGroups.value.length)
    return null
  return {
    inputTokens: providerGroups.value.reduce((sum, g) => sum + g.inputTokens, 0),
    outputTokens: providerGroups.value.reduce((sum, g) => sum + g.outputTokens, 0),
    totalCost: providerGroups.value.reduce((sum, g) => sum + Number.parseFloat(g.totalCost), 0).toFixed(2),
  }
})
</script>

<template>
  <div class="rounded-xl bg-card/60 backdrop-blur-sm border border-border/50 overflow-hidden">
    <div class="px-4 py-3 border-b border-border/30">
      <h3 class="text-sm font-medium">
        Provider 使用量
      </h3>
    </div>

    <!-- 空状态 -->
    <div v-if="!providerGroups.length" class="px-4 py-6 text-center text-sm text-muted-foreground">
      暂无 Token 消耗数据
    </div>

    <!-- 表格 -->
    <Table v-else>
      <TableHeader>
        <TableRow>
          <TableHead>Provider</TableHead>
          <TableHead class="text-right">
            输入 Token
          </TableHead>
          <TableHead class="text-right">
            输出 Token
          </TableHead>
          <TableHead class="text-right">
            成本
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        <TableRow v-for="item in providerGroups" :key="item.providerType">
          <TableCell class="font-medium">
            {{ item.displayName }}
          </TableCell>
          <TableCell class="text-right font-mono text-sm">
            {{ formatTokens(item.inputTokens) }}
          </TableCell>
          <TableCell class="text-right font-mono text-sm">
            {{ formatTokens(item.outputTokens) }}
          </TableCell>
          <TableCell class="text-right font-mono text-sm">
            ${{ item.totalCost }}
          </TableCell>
        </TableRow>
        <!-- 汇总行 -->
        <TableRow v-if="summary" class="border-t-2 border-border/50 font-semibold">
          <TableCell>合计</TableCell>
          <TableCell class="text-right font-mono text-sm">
            {{ formatTokens(summary.inputTokens) }}
          </TableCell>
          <TableCell class="text-right font-mono text-sm">
            {{ formatTokens(summary.outputTokens) }}
          </TableCell>
          <TableCell class="text-right font-mono text-sm">
            ${{ summary.totalCost }}
          </TableCell>
        </TableRow>
      </TableBody>
    </Table>
  </div>
</template>
