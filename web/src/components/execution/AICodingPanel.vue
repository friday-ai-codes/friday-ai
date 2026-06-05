<script setup lang="ts">
import { computed, ref } from 'vue'
import { Badge } from '~/components/ui/badge'

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '~/components/ui/collapsible'

/**
 * AICodingPanel - AI 编码执行结果展示面板
 *
 * 功能：
 * - 展示分支信息（branch_name -> base_branch）
 * - 成功仓库列表（MR 链接 + 完成的任务列表 + 变更统计）
 * - 失败仓库列表（错误详情）
 * - 汇总统计（总仓库、成功、失败、变更文件数）
 * - 等待分支确认状态提示
 */

interface Props {
  nodeExecution: {
    id: string
    status: string
    node_type: string
    output_data?: Record<string, any>
  }
}

const props = defineProps<Props>()

// 从 output_data 提取数据
const mergeRequests = computed((): Record<string, any>[] =>
  props.nodeExecution.output_data?.merge_requests || [],
)

const branches = computed((): Record<string, any> =>
  props.nodeExecution.output_data?.branches || {},
)

const changesSummary = computed((): Record<string, any> =>
  props.nodeExecution.output_data?.changes_summary || {},
)

const failedDetails = computed((): Record<string, any>[] =>
  props.nodeExecution.output_data?.failed_details || [],
)

// 状态判断
const isCompleted = computed(() => props.nodeExecution.status === 'completed')
const isRunning = computed(() => props.nodeExecution.status === 'running')
const isWaitingEvent = computed(() => props.nodeExecution.status === 'waiting_event')
const hasFailures = computed(() => failedDetails.value.length > 0)
const allSucceeded = computed(() => changesSummary.value.failed_repos === 0)

// 成功仓库列表（从 changes_summary.succeeded_repos 或 merge_requests 提取）
const succeededRepos = computed((): Record<string, any>[] => {
  if (changesSummary.value.succeeded_repos) {
    return changesSummary.value.succeeded_repos
  }
  return mergeRequests.value
})

// 折叠面板状态
const succeededOpen = ref(true)
const failedOpen = ref(true)
</script>

<template>
  <div class="card card overflow-hidden">
    <!-- Header -->
    <div class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-3">
          <div class="bg-primary/10 rounded-lg p-2">
            <span class="icon-[lucide--terminal] w-5 h-5 text-primary" />
          </div>
          <h3 class="text-sm font-semibold">
            AI 编码执行
          </h3>
        </div>

        <!-- Status Badge -->
        <Badge
          v-if="isRunning"
          class="bg-amber-500/10 text-amber-600 border-amber-500/20 animate-pulse"
        >
          <span class="icon-[lucide--loader-2] w-3 h-3 mr-1 animate-spin" />
          编码中
        </Badge>
        <Badge
          v-else-if="isWaitingEvent"
          class="bg-primary/10 text-primary border-primary/20"
        >
          <span class="icon-[lucide--git-branch] w-3 h-3 mr-1" />
          待确认分支
        </Badge>
        <Badge
          v-else-if="isCompleted && allSucceeded"
          class="bg-emerald-500/10 text-emerald-600 border-emerald-500/20"
        >
          <span class="icon-[lucide--check] w-3 h-3 mr-1" />
          编码完成
        </Badge>
        <Badge
          v-else-if="isCompleted && hasFailures"
          class="bg-orange-500/10 text-orange-600 border-orange-500/20"
        >
          <span class="icon-[lucide--alert-triangle] w-3 h-3 mr-1" />
          部分完成
        </Badge>
        <Badge
          v-else-if="nodeExecution.status === 'failed'"
          class="bg-red-500/10 text-red-600 border-red-500/20"
        >
          <span class="icon-[lucide--x] w-3 h-3 mr-1" />
          编码失败
        </Badge>
      </div>
    </div>

    <div class="p-5 space-y-4">
      <!-- Branch Info (always visible when available) -->
      <div v-if="branches.branch_name" class="flex items-center gap-2 text-sm">
        <span class="icon-[lucide--git-branch] w-4 h-4 text-primary" />
        <code class="font-mono text-xs px-1.5 py-0.5 rounded bg-primary/10 text-primary">{{ branches.branch_name }}</code>
        <span class="icon-[lucide--arrow-right] w-3 h-3 text-muted-foreground" />
        <code class="font-mono text-xs px-1.5 py-0.5 rounded bg-muted text-muted-foreground">{{ branches.base_branch || 'main' }}</code>
      </div>

      <!-- Waiting Event: branch confirmation -->
      <div
        v-if="isWaitingEvent"
        class="p-3 rounded-xl bg-primary/5 border border-primary/10"
      >
        <div class="flex items-center gap-2 text-sm text-primary">
          <span class="icon-[lucide--hourglass] w-4 h-4 animate-pulse" />
          <span>正在等待飞书确认分支名...</span>
        </div>
        <div v-if="branches.candidates" class="mt-2 flex flex-wrap gap-1">
          <code
            v-for="candidate in branches.candidates"
            :key="candidate"
            class="font-mono text-xs px-1.5 py-0.5 rounded bg-primary/10 text-primary"
          >
            {{ candidate }}
          </code>
        </div>
      </div>

      <!-- Succeeded Repos (collapsible) -->
      <Collapsible v-if="succeededRepos.length > 0" v-model:open="succeededOpen">
        <CollapsibleTrigger class="flex items-center justify-between w-full py-1.5 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors group">
          <span class="flex items-center gap-2">
            <span class="icon-[lucide--check-circle] w-4 h-4 text-emerald-500" />
            成功仓库
            <Badge variant="secondary" class="text-[10px] px-1.5 py-0">
              {{ succeededRepos.length }}
            </Badge>
          </span>
          <span
            class="icon-[lucide--chevron-down] w-4 h-4 transition-transform duration-200"
            :class="{ 'rotate-180': succeededOpen }"
          />
        </CollapsibleTrigger>
        <CollapsibleContent class="space-y-2 pt-2">
          <div
            v-for="(repo, index) in succeededRepos"
            :key="index"
            class="rounded-xl border border-border/40 p-3 hover:border-primary/30 hover:shadow-sm transition-all"
          >
            <div class="flex items-center justify-between">
              <span class="font-medium text-sm">{{ repo.repository || repo.repo_name || `Repo ${index + 1}` }}</span>
              <a
                v-if="repo.mr_url || repo.merge_request_url"
                :href="repo.mr_url || repo.merge_request_url"
                target="_blank"
                rel="noopener noreferrer"
                class="text-xs text-primary hover:underline flex items-center gap-1"
              >
                <span class="icon-[lucide--external-link] w-3 h-3" />
                查看 MR
              </a>
            </div>

            <!-- Completed Tasks -->
            <div v-if="repo.tasks_completed && repo.tasks_completed.length > 0" class="mt-2 space-y-1">
              <div
                v-for="(task, tIdx) in repo.tasks_completed"
                :key="tIdx"
                class="flex items-center gap-1.5 text-xs text-muted-foreground"
              >
                <span class="icon-[lucide--check] w-3 h-3 text-emerald-500 shrink-0" />
                <span>{{ task }}</span>
              </div>
            </div>

            <!-- Changes Stats -->
            <div class="mt-2 flex items-center gap-2">
              <Badge
                v-if="repo.insertions !== undefined"
                variant="outline"
                class="text-[10px] px-1.5 py-0 border-emerald-500/30 text-emerald-600"
              >
                +{{ repo.insertions }}
              </Badge>
              <Badge
                v-if="repo.deletions !== undefined"
                variant="outline"
                class="text-[10px] px-1.5 py-0 border-red-500/30 text-red-600"
              >
                -{{ repo.deletions }}
              </Badge>
              <Badge
                v-if="repo.files_changed !== undefined"
                variant="outline"
                class="text-[10px] px-1.5 py-0"
              >
                {{ repo.files_changed }} 文件
              </Badge>
            </div>
          </div>
        </CollapsibleContent>
      </Collapsible>

      <!-- Failed Repos (collapsible) -->
      <Collapsible v-if="failedDetails.length > 0" v-model:open="failedOpen">
        <CollapsibleTrigger class="flex items-center justify-between w-full py-1.5 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors group">
          <span class="flex items-center gap-2">
            <span class="icon-[lucide--x-circle] w-4 h-4 text-red-500" />
            失败仓库
            <Badge variant="destructive" class="text-[10px] px-1.5 py-0">
              {{ failedDetails.length }}
            </Badge>
          </span>
          <span
            class="icon-[lucide--chevron-down] w-4 h-4 transition-transform duration-200"
            :class="{ 'rotate-180': failedOpen }"
          />
        </CollapsibleTrigger>
        <CollapsibleContent class="space-y-2 pt-2">
          <div
            v-for="(fail, index) in failedDetails"
            :key="index"
            class="rounded-xl bg-red-500/5 border border-red-500/10 p-3"
          >
            <div class="font-medium text-sm">
              {{ fail.repository || fail.repo_name || `Repo ${index + 1}` }}
            </div>
            <p class="text-xs text-red-600/80 mt-1">
              {{ fail.error || fail.reason || '未知错误' }}
            </p>
          </div>
        </CollapsibleContent>
      </Collapsible>

      <!-- Summary Stats -->
      <div
        v-if="changesSummary.total_repos !== undefined"
        class="grid grid-cols-4 gap-3 pt-2"
      >
        <div class="text-center">
          <div class="text-lg font-bold">
            {{ changesSummary.total_repos || 0 }}
          </div>
          <div class="text-xs text-muted-foreground">
            总仓库
          </div>
        </div>
        <div class="text-center">
          <div class="text-lg font-bold text-emerald-600">
            {{ changesSummary.succeeded_count || succeededRepos.length || 0 }}
          </div>
          <div class="text-xs text-muted-foreground">
            成功
          </div>
        </div>
        <div class="text-center">
          <div class="text-lg font-bold text-red-600">
            {{ changesSummary.failed_repos || failedDetails.length || 0 }}
          </div>
          <div class="text-xs text-muted-foreground">
            失败
          </div>
        </div>
        <div class="text-center">
          <div class="text-lg font-bold">
            {{ changesSummary.total_files_changed || 0 }}
          </div>
          <div class="text-xs text-muted-foreground">
            变更文件
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
