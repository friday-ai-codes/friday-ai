<script setup lang="ts">
/**
 * BranchNode - 分支节点（condition / parallel）卡片
 *
 * 对齐 dify if-else：每个分支在卡片内单独一行，行右侧各自一个 source handle。
 * 分支 handle 命名与后端一致：`branch_${i}`（+ condition 默认分支 `else`），
 * 因此连出的边 sourcePort 能被后端 routing 正确选中。
 * - parallel：分支可增删改，写回 `config.branches`（持久化 + 入历史）。
 * - condition：卡片只读展示条件摘要（条件编辑在右侧配置面板）。
 */
import { Handle, Position } from '@vue-flow/core'
import { GitBranch, GitFork, Plus, X } from 'lucide-vue-next'
import { computed } from 'vue'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
import BaseWorkflowNode from './BaseWorkflowNode.vue'

interface ParallelBranch { name: string, enabled?: boolean }
interface ConditionExpr { field?: string, operator?: string, value?: unknown }
interface ConditionItem { name?: string, expression?: ConditionExpr }
interface BranchRow { handleId: string, label: string }

const props = defineProps<{
  id: string
  data: {
    name: string
    nodeType: string
    disabled?: boolean
    config?: Record<string, any>
    [key: string]: unknown
  }
  selected?: boolean
}>()

const store = useWorkflowsStore()
const isCondition = computed(() => props.data.nodeType === 'condition')

const OPERATOR_LABELS: Record<string, string> = {
  eq: '=',
  ne: '≠',
  gt: '>',
  gte: '≥',
  lt: '<',
  lte: '≤',
  contains: '包含',
  not_contains: '不包含',
  starts_with: '开头是',
  ends_with: '结尾是',
  is_empty: '为空',
  is_not_empty: '非空',
  is_true: '为真',
  is_false: '为假',
}

function exprSummary(expr?: ConditionExpr): string {
  if (!expr || !expr.field)
    return ''
  const op = OPERATOR_LABELS[expr.operator ?? ''] ?? expr.operator ?? ''
  const val = expr.value === undefined || expr.value === null ? '' : String(expr.value)
  return `${expr.field} ${op} ${val}`.trim()
}

const parallelBranches = computed<ParallelBranch[]>(() =>
  Array.isArray(props.data.config?.branches) ? props.data.config!.branches : [],
)

/** 渲染行：condition = 条件 + 默认(else)，parallel = 各分支 */
const rows = computed<BranchRow[]>(() => {
  if (isCondition.value) {
    const conditions: ConditionItem[] = Array.isArray(props.data.config?.conditions)
      ? props.data.config!.conditions
      : []
    const list: BranchRow[] = conditions.map((c, i) => ({
      handleId: `branch_${i}`,
      label: c?.name || exprSummary(c?.expression) || `条件 ${i + 1}`,
    }))
    list.push({ handleId: props.data.config?.default_branch || 'else', label: '否则' })
    return list
  }
  return parallelBranches.value.map((b, i) => ({
    handleId: `branch_${i}`,
    label: b?.name || `分支 ${i + 1}`,
  }))
})

// —— parallel 分支编辑：写回 store.config.branches（持久化 + 入历史 + 对齐后端 branch_i）——
function commitBranches(next: ParallelBranch[]) {
  store.updateNode(props.id, { config: { ...(props.data.config ?? {}), branches: next } })
}

function addBranch() {
  const cur = parallelBranches.value
  if (cur.length >= 8)
    return
  commitBranches([...cur, { name: `分支 ${cur.length + 1}`, enabled: true }])
}

// 仅允许删除最后一个分支：避免 branch_${i} 索引重排导致已有连线 handle 失配
function removeLastBranch() {
  const cur = parallelBranches.value
  if (cur.length <= 2)
    return
  const lastHandle = `branch_${cur.length - 1}`
  store.edges
    .filter(e => e.source === props.id && (e.sourcePort ?? 'default') === lastHandle)
    .forEach(e => store.removeEdge(e.id))
  commitBranches(cur.slice(0, -1))
}

function renameBranch(index: number, name: string) {
  commitBranches(parallelBranches.value.map((b, i) => (i === index ? { ...b, name } : b)))
}
</script>

<template>
  <BaseWorkflowNode :id="id" :data="data" :selected="selected" hide-handles="output">
    <template #icon>
      <GitBranch v-if="isCondition" class="w-4 h-4" />
      <GitFork v-else class="w-4 h-4" />
    </template>

    <template #content>
      <div class="mt-1 space-y-1">
        <div
          v-for="(row, i) in rows"
          :key="row.handleId"
          class="relative flex items-center gap-1 rounded-md bg-muted/60 px-2 py-1"
        >
          <!-- parallel: 名称可编辑；condition: 只读条件摘要 -->
          <input
            v-if="!isCondition"
            :value="row.label"
            class="min-w-0 flex-1 bg-transparent text-xs text-foreground outline-none"
            @change="renameBranch(i, ($event.target as HTMLInputElement).value)"
            @click.stop
            @mousedown.stop
          >
          <span v-else class="min-w-0 flex-1 truncate text-xs text-foreground" :title="row.label">
            {{ row.label }}
          </span>

          <!-- 每个分支自己的 source handle（命名对齐后端 branch_i / else） -->
          <Handle
            :id="row.handleId"
            type="source"
            :position="Position.Right"
            :style="{ right: '-20px', top: '50%', transform: 'translateY(-50%)' }"
          />
        </div>

        <!-- parallel 增删分支（仅末尾可删，避免 branch_i 索引重排） -->
        <div v-if="!isCondition" class="flex items-center gap-3 pt-0.5">
          <button
            v-if="parallelBranches.length < 8"
            type="button"
            class="flex items-center gap-0.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
            @click.stop="addBranch"
          >
            <Plus class="w-3 h-3" /><span>分支</span>
          </button>
          <button
            v-if="parallelBranches.length > 2"
            type="button"
            class="flex items-center gap-0.5 text-xs text-muted-foreground hover:text-destructive transition-colors"
            @click.stop="removeLastBranch"
          >
            <X class="w-3 h-3" /><span>末尾</span>
          </button>
        </div>
      </div>
    </template>
  </BaseWorkflowNode>
</template>
