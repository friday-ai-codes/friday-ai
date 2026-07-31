<script setup lang="ts">
/**
 * 阶段 1 确认门面板（Phase 115-07，FLOW-03，UI-SPEC §11.3 / §16 / §13.5）。
 *
 * ## ① 范围增量登记（⛔ 不得默默丢掉）
 *
 * 112 只交付了 `blueprint-gate/` 八个端点，**全仓零前端** ⇒ 不做本面板，FLOW-03 在 UI 上
 * **不可达**：用户看得到蓝图正文却无法确认仓库集与职责，永远走不到 113 的阶段 2，整条链在
 * 界面上断在第一关。本面板因此是本相位显式登记的**可独立顺延尾巴**（CONTEXT `<deferred>` /
 * UI-SPEC §11.3 双处登记），若确需顺延，顺延目标是 Phase 116 且必须在 STATE 显式登记。
 *
 * ## ② ⭐ 渲染条件只有一条：`GET blueprint-gate/` 返回 200
 *
 * 任何非 200（含三种 404：门尚未开启 / artifact 查不到 / 该 artifact 上没有蓝图编排的会话）
 * ⇒ **不渲染本面板**，⛔ 不报错、⛔ 不弹 toast、⛔ 不进 §8.2 错误分档、⛔ **不靠 `detail`
 * 文本分支判定**（那等于把后端文案当协议，后端改一个字前端就错）。⚠️ 上面这三种语义刻意
 * **不写后端原文**：写了就等于把文案抄进前端源码，也会命中本 plan 自己的源码扫描。该判据的唯一落点是页面
 * 挂载点的 `v-if="gateAvailable"`——本组件被渲染出来时，快照必然已经是 200。
 *
 * ## ③ ⭐ ⛔ 不得据本链的状态码推断权限
 *
 * 实读 `blueprint_gate_views._ablueprint_project_id`（`:511`）**只在
 * `BlueprintRejectedToBoundaryView`（`:385`）里被用过一次** —— 八个端点里其余七个只有
 * `IsAuthenticated`，**没有项目范围闸**。它的 404 混合了三种语义 ⇒ 状态码不携带任何权限
 * 信息。页面的权限判定由四个主查询（正文 / 人审快照 / threads / events，全部有闸）承担。
 * 这是一处**既有后端缺口**，本相位边界是「只加读面」不修它，已记进 STATE 的 Pending Todos。
 *
 * ## ④ 七个动作的统一范式
 *
 * 一次 POST → 成功 ⇒ 成功 toast + ⭐ **双 invalidate**（`['blueprint','gate',id]` 与
 * `['blueprint','snapshot',id]` —— 确认门动作会同时改蓝图状态与线程）。⛔ 零乐观更新、
 * ⛔ 零 `setQueryData`、⛔ 不自行推断下一状态。
 *
 * ⭐ **动作由本面板自持并执行，⛔ 不上抛给页面分发**：七个动作与页面其余六个动作语义独立
 * （它们改的是确认门，不是人审），塞进页面的动作分发器会让页面再长一截；而本面板本就要在
 * 被顺延时整体拿掉，自持动作让「拿掉」是一次纯删除。`action` emit 只是**完成通知**（供页面
 * 或测试观察），⛔ 不是请求。
 *
 * ## ⑤ ⭐ `confirm/` 的 409 两档靠机器可读键，⛔ 不靠中文文案
 *
 * `blocked_reason === 'pending_clarification'` ⇒ 面板内提示 +「前往未决线程」⇒ emit
 * `goto-unresolved`（页面打开侧栏未决组）；其余 409 ⇒ 回显 `detail` + 刷新重试（invalidate）。
 * ⚠️ 后端当前的 409 响应体**只有 `detail`**（`blueprint_gate_views.py:240,249`），尚未下发
 * `blocked_reason`。这里坚持读机器可读键：未下发时一律落到「其余 409」这一档（功能降级但
 * 语义正确），⛔ 绝不退化成按中文文案分支。补齐 `blocked_reason` 已记进 STATE 的 Pending Todos。
 */

import type { BlueprintGateRepo, BlueprintGateSnapshot } from '~/types/blueprint'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import blueprintsApi from '~/api/blueprints'
import { ApiError } from '~/api/client'
import { repositoriesApi } from '~/api/repositories'
import BlueprintGateRepoRow from '~/components/blueprint/BlueprintGateRepoRow.vue'
import { Button } from '~/components/ui/button'
import { Separator } from '~/components/ui/separator'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/tooltip'
import RepositoryPicker from '~/components/workflow/RepositoryPicker.vue'
import { useConfirmDialog } from '~/composables/useConfirmDialog'
import { useToast } from '~/composables/useToast'

const props = withDefaults(defineProps<{
  artifactId: string
  snapshot: BlueprintGateSnapshot
  submitting?: boolean
}>(), {
  submitting: false,
})

const emit = defineEmits<{
  /** 完成通知（动作已由本面板执行完毕），⛔ 不是请求。 */
  'action': [name: string, payload?: unknown]
  /** `confirm/` 409 `pending_clarification` 的解药入口：页面打开侧栏未决组。 */
  'goto-unresolved': []
}>()

const { t } = useI18n()
const toast = useToast()
const queryClient = useQueryClient()
const { confirm } = useConfirmDialog()

/** 一个动作 = 一次 POST + 一句成功文案；七个动作共用同一条执行通道。 */
interface GateTask {
  name: string
  run: () => Promise<unknown>
  success: (result: unknown) => string
}

// ── 快照派生 ──────────────────────────────────────────────────────────────────

const repos = computed<BlueprintGateRepo[]>(() => props.snapshot.repos ?? [])

const pendingIds = computed(() => new Set(props.snapshot.pending_research_repository_ids ?? []))

function isPending(repo: BlueprintGateRepo): boolean {
  return pendingIds.value.has(repo.repository_id)
}

/** ⭐ 存在待调研仓 ⇒ 确认主按钮禁用（回显后端 `_LOCK_BLOCKED_MESSAGES` 的语义）。 */
const hasPending = computed(() => pendingIds.value.size > 0)

/**
 * rejected 沉淀的候选是否存在。
 *
 * ⚠️ 快照**没有**单独的 rejected 清单（`BlueprintGateSnapshotSerializer` 逐字只有八键），
 * 可派生的唯一代理是 `repos[].removed` —— 确认门里被移除的仓正是产出 `boundaries` 草案的
 * 那一批（`BlueprintGateRemoveRepoView` 文档「其移除理由产 boundaries 草案」）。⛔ 不猜键名。
 */
const hasRejectedCandidates = computed(() => repos.value.some(repo => repo.removed === true))

// ── 动作通道（一次 POST + 双 invalidate；⛔ 零乐观更新）────────────────────────

/** ⭐ 双失效：确认门动作会同时改蓝图状态与线程，只失效 gate 会让正文停在旧状态。 */
function invalidateGate(): void {
  queryClient.invalidateQueries({ queryKey: ['blueprint', 'gate', props.artifactId] })
  queryClient.invalidateQueries({ queryKey: ['blueprint', 'snapshot', props.artifactId] })
}

/** `confirm/` 409 且带该机器可读键时，展开面板内的解药入口。 */
const clarificationBlocked = ref(false)

function blockedReasonOf(error: unknown): string {
  if (!(error instanceof ApiError) || !error.body || typeof error.body !== 'object')
    return ''
  return String((error.body as { blocked_reason?: unknown }).blocked_reason ?? '')
}

function reportFailure(task: GateTask, error: unknown): void {
  if (error instanceof ApiError) {
    if (task.name === 'confirm' && error.status === 409) {
      if (blockedReasonOf(error) === 'pending_clarification') {
        clarificationBlocked.value = true
        return
      }
      toast.error(error.detail, t('knowledge.blueprints.error.refresh'))
      invalidateGate()
      return
    }
    if (error.status >= 400 && error.status < 500) {
      toast.error(error.detail)
      return
    }
  }
  toast.error(t('knowledge.blueprints.error.unavailable'))
}

const gateAction = useMutation({
  mutationFn: (task: GateTask) => task.run(),
  onSuccess: (result, task) => {
    clarificationBlocked.value = false
    toast.success(task.success(result))
    invalidateGate()
    emit('action', task.name, result)
  },
  onError: (error, task) => {
    reportFailure(task, error)
  },
})

const busy = computed(() => props.submitting || gateAction.isPending.value)

async function runTask(task: GateTask): Promise<boolean> {
  try {
    await gateAction.mutateAsync(task)
    return true
  }
  catch {
    // 失败已在 `onError` 分档处理；这里只用于让批量动作停在第一次失败处。
    return false
  }
}

// ── 七个动作 ──────────────────────────────────────────────────────────────────

async function onConfirm(): Promise<void> {
  const ok = await confirm({
    title: t('knowledge.blueprints.gate.lockTitle'),
    description: t('knowledge.blueprints.gate.lockBody'),
    confirmText: t('knowledge.blueprints.gate.lockConfirm'),
    variant: 'destructive',
  })
  if (!ok)
    return
  await runTask({
    name: 'confirm',
    run: () => blueprintsApi.confirmGate(props.artifactId),
    success: () => t('knowledge.blueprints.gate.confirmSuccess'),
  })
}

async function onRemove(repositoryId: string): Promise<void> {
  await runTask({
    name: 'remove_repo',
    run: () => blueprintsApi.removeRepo(props.artifactId, { repository_id: repositoryId }),
    success: () => t('knowledge.blueprints.gate.removeSuccess'),
  })
}

async function onReclassify(repositoryId: string, role: 'direct' | 'indirect'): Promise<void> {
  await runTask({
    name: 'reclassify_role',
    run: () => blueprintsApi.reclassifyRole(props.artifactId, { repository_id: repositoryId, role }),
    success: () => t('knowledge.blueprints.gate.reclassifySuccess'),
  })
}

async function onEditResponsibility(repositoryId: string, text: string, rerun: boolean): Promise<void> {
  await runTask({
    name: 'edit_responsibility',
    run: () => blueprintsApi.editResponsibility(props.artifactId, {
      repository_id: repositoryId,
      responsibility: text,
      rerun,
    }),
    success: () => t('knowledge.blueprints.gate.editSuccess'),
  })
}

async function onUpgradeResearch(repositoryId: string): Promise<void> {
  await runTask({
    name: 'upgrade_research',
    run: () => blueprintsApi.upgradeResearch(props.artifactId, { repository_id: repositoryId }),
    success: () => t('knowledge.blueprints.gate.upgradeSuccess'),
  })
}

async function onRejectedToBoundary(): Promise<void> {
  await runTask({
    name: 'rejected_to_boundary',
    run: () => blueprintsApi.rejectedToBoundary(props.artifactId),
    success: (result) => {
      const count = Number((result as { draft_count?: unknown } | null)?.draft_count ?? 0)
      return t('knowledge.blueprints.gate.boundarySuccess', { n: count })
    },
  })
}

// ── 添加仓库：⭐ 复用既有 `RepositoryPicker`（⛔ 不新造、⛔ 不包适配层）──────────

/**
 * `RepositoryPicker` 的形状已核实：`modelValue: string[]`（多选）+ `repositories: {id,name}[]`
 * + `placeholder` / `allowManualInput`，**唯一 emit 是 `update:modelValue`** ⇒ 一个本地
 * `ref<string[]>` 直接 `v-model` 即可，⛔ 不写薄适配层、⛔ 不改用别的选择器。
 */
const picked = ref<string[]>([])

/** 候选仓库列表失败不反噬本面板：`retry: false` + 空数组 ⇒ 选择器自动切到手输 id 模式。 */
const repositoriesQuery = useQuery({
  queryKey: ['repositories', 'list'],
  queryFn: () => repositoriesApi.list(),
  staleTime: 60_000,
  retry: false,
})

const repositoryOptions = computed(
  () => (repositoriesQuery.data.value ?? []).map(item => ({ id: item.id, name: item.name })),
)

/** 多选逐个 POST，**顺序执行**；任一失败即停在该处，未提交的 id 留在选择器里可重试。 */
async function onAddRepos(): Promise<void> {
  const ids = [...picked.value]
  if (!ids.length || busy.value)
    return
  const remaining: string[] = []
  let failed = false
  for (const repositoryId of ids) {
    if (failed) {
      remaining.push(repositoryId)
      continue
    }
    const ok = await runTask({
      name: 'add_repo',
      run: () => blueprintsApi.addRepo(props.artifactId, { repository_id: repositoryId }),
      success: () => t('knowledge.blueprints.gate.addSuccess'),
    })
    if (!ok) {
      failed = true
      remaining.push(repositoryId)
    }
  }
  picked.value = remaining
}

function onGotoUnresolved(): void {
  emit('goto-unresolved')
}
</script>

<template>
  <section class="card space-y-4 p-4" data-testid="blueprint-gate-panel" :aria-label="t('knowledge.blueprints.gate.title')">
    <header class="space-y-1">
      <h2 class="text-sm font-semibold">
        {{ t('knowledge.blueprints.gate.title') }}
      </h2>
      <!-- 顶部说明条：仓内没有 `ui/alert`，沿用 115-06 的「语义描边 div + role=status」范式 -->
      <div class="rounded-lg border border-border bg-muted/40 p-2 text-xs text-muted-foreground" role="status">
        {{ t('knowledge.blueprints.gate.notice') }}
      </div>
    </header>

    <!-- 仓库行列表 -->
    <div v-if="repos.length" class="space-y-2">
      <BlueprintGateRepoRow
        v-for="repo in repos"
        :key="repo.repository_id"
        :repo="repo"
        :pending="isPending(repo)"
        :submitting="busy"
        @remove="onRemove"
        @reclassify="onReclassify"
        @edit-responsibility="onEditResponsibility"
        @upgrade-research="onUpgradeResearch"
      />
    </div>
    <p v-else class="text-xs text-muted-foreground" data-testid="blueprint-gate-empty">
      {{ t('knowledge.blueprints.repo.empty') }}
    </p>

    <Separator />

    <!-- 添加仓库：复用既有仓库选择器（多选） -->
    <div class="space-y-2" data-testid="blueprint-gate-add-repo">
      <p class="text-xs font-medium">
        {{ t('knowledge.blueprints.gate.addRepo') }}
      </p>
      <div class="flex flex-wrap items-center gap-2">
        <div class="min-w-0 flex-1">
          <RepositoryPicker
            v-model="picked"
            :repositories="repositoryOptions"
            :placeholder="t('knowledge.blueprints.gate.addRepoPlaceholder')"
          />
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          :disabled="!picked.length || busy"
          data-testid="blueprint-gate-add-repo-submit"
          @click="onAddRepos"
        >
          {{ t('knowledge.blueprints.gate.addRepoSubmit') }}
        </Button>
      </div>
    </div>

    <!-- ⭐ confirm 409 `pending_clarification` 的解药入口 -->
    <div
      v-if="clarificationBlocked"
      class="flex flex-wrap items-center gap-2 rounded-lg border border-border p-2 text-xs"
      role="status"
      data-testid="blueprint-gate-clarification-blocked"
    >
      <span>{{ t('knowledge.blueprints.gate.unresolvedClarification') }}</span>
      <Button
        type="button"
        variant="outline"
        size="sm"
        data-testid="blueprint-gate-goto-unresolved"
        @click="onGotoUnresolved"
      >
        {{ t('knowledge.blueprints.gate.gotoUnresolved') }}
      </Button>
    </div>

    <!-- 底部动作条：次级动作在左、确认主按钮在右 -->
    <div class="flex flex-wrap items-center gap-2">
      <Button
        v-if="hasRejectedCandidates"
        type="button"
        variant="ghost"
        size="sm"
        :disabled="busy"
        data-testid="blueprint-gate-rejected-to-boundary"
        @click="onRejectedToBoundary"
      >
        {{ t('knowledge.blueprints.gate.rejectedToBoundary') }}
      </Button>

      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger as-child>
            <span class="ml-auto inline-flex">
              <Button
                type="button"
                size="sm"
                :disabled="hasPending || busy"
                data-testid="blueprint-gate-confirm"
                @click="onConfirm"
              >
                {{ t('knowledge.blueprints.gate.confirm') }}
              </Button>
            </span>
          </TooltipTrigger>
          <TooltipContent v-if="hasPending" data-testid="blueprint-gate-confirm-tooltip">
            {{ t('knowledge.blueprints.gate.pendingResearch') }}
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    </div>
  </section>
</template>
