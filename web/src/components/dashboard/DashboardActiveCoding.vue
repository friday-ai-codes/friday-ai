<script setup lang="ts">
import type { InProgressCodingItem } from '~/api/dashboard'
import { ref, toRef } from 'vue'
import deepOrbitAnimation from '~/assets/lottie/deepOrbit'
import { Button } from '~/components/ui/button'

const props = defineProps<{
  count: number
  items: InProgressCodingItem[]
  loading: boolean
}>()

// 有进行中的编码时，标题图标换成「双星环绕」Lottie——隐喻 AI 代理正在工作
const orbitEl = ref<HTMLElement | null>(null)
useLottie(orbitEl, deepOrbitAnimation)

// 数据到达后列表行错拍浮入
const rootEl = ref<HTMLElement | null>(null)
useListReveal(rootEl, '.coding-row', toRef(() => !props.loading))

function formatDate(dateStr: string) {
  const date = new Date(dateStr)
  return date.toLocaleDateString('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function linkFor(item: InProgressCodingItem): string {
  if (item.source === 'chat' && item.conversation_id)
    return `/chat?conversation=${item.conversation_id}`
  if (item.workflow_execution_id)
    return `/executions/${item.workflow_execution_id}`
  return '/executions'
}

/** 等待人工处理的状态（方案/代码评审、等待确认）用 amber 区分于自动执行中 */
const WAITING_STATUSES = new Set(['plan_review', 'code_review', 'awaiting_confirmation'])

function isWaiting(status: string): boolean {
  return WAITING_STATUSES.has(status)
}
</script>

<template>
  <section ref="rootEl" class="card overflow-hidden" aria-label="进行中的编码">
    <!-- 标题栏 -->
    <div class="flex items-center justify-between px-6 py-4 border-b border-border/50">
      <div class="flex items-center gap-3">
        <div class="stat-icon stat-icon-primary">
          <!-- 有任务进行中：双星环绕 Lottie；空闲：静态终端图标 -->
          <span
            v-if="!loading && count > 0"
            ref="orbitEl"
            class="coding-orbit"
            aria-hidden="true"
          />
          <span v-else class="icon-[lucide--terminal] text-lg" aria-hidden="true" />
        </div>
        <div>
          <div class="flex items-center gap-2">
            <h2 class="text-base font-semibold text-foreground">
              进行中的编码
            </h2>
            <span
              v-if="!loading && count > 0"
              class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-primary/10 text-primary text-xs font-medium tabular-nums"
            >
              <span class="relative flex w-1.5 h-1.5" aria-hidden="true">
                <span class="animate-ping motion-reduce:animate-none absolute inline-flex h-full w-full rounded-full bg-primary opacity-75" />
                <span class="relative inline-flex rounded-full w-1.5 h-1.5 bg-primary" />
              </span>
              {{ count }}
            </span>
          </div>
          <p class="text-xs text-muted-foreground mt-0.5">
            AI 正在执行的编码任务
          </p>
        </div>
      </div>
      <RouterLink to="/executions">
        <span class="text-sm font-medium text-muted-foreground hover:text-primary transition-colors group inline-flex items-center">
          查看全部
          <span class="icon-[lucide--arrow-right] ml-1 group-hover:translate-x-1 transition-transform" aria-hidden="true" />
        </span>
      </RouterLink>
    </div>

    <div class="p-4">
      <!-- 加载骨架 -->
      <div v-if="loading" class="space-y-1">
        <div v-for="i in 2" :key="i" class="flex items-center gap-4 p-3 rounded-xl">
          <div class="w-9 h-9 rounded-lg bg-muted animate-pulse" />
          <div class="flex-1 space-y-2">
            <div class="h-4 w-2/5 bg-muted animate-pulse rounded" />
            <div class="h-3 w-1/5 bg-muted animate-pulse rounded" />
          </div>
          <div class="h-5 w-14 bg-muted animate-pulse rounded-full" />
        </div>
      </div>

      <!-- 空状态：给出明确的下一步引导 -->
      <div v-else-if="items.length === 0" class="py-8 text-center">
        <div class="stat-icon stat-icon-primary mx-auto mb-3 w-12 h-12 text-xl">
          <span class="icon-[lucide--coffee]" aria-hidden="true" />
        </div>
        <p class="text-sm font-medium text-foreground mb-1">
          当前没有进行中的编码
        </p>
        <p class="text-xs text-muted-foreground mb-4">
          在 AI 对话中确认技术方案，即可发起一次自动编码
        </p>
        <RouterLink to="/chat">
          <Button size="sm" variant="outline">
            <span class="icon-[lucide--message-square]" aria-hidden="true" />
            去发起 AI 编码
          </Button>
        </RouterLink>
      </div>

      <!-- 进行中列表 -->
      <div v-else class="space-y-1">
        <RouterLink
          v-for="item in items"
          :key="item.id"
          :to="linkFor(item)"
          class="coding-row group flex items-center gap-4 p-3 rounded-xl hover:bg-muted/50 transition-colors duration-200"
        >
          <!-- 来源图标 -->
          <div
            class="shrink-0 w-9 h-9 rounded-lg bg-muted/50 flex items-center justify-center text-muted-foreground group-hover:bg-primary/10 group-hover:text-primary transition-colors"
            :title="item.source === 'chat' ? '对话发起' : '工作流发起'"
          >
            <span
              :class="item.source === 'chat' ? 'icon-[lucide--message-square-code]' : 'icon-[lucide--workflow]'"
              aria-hidden="true"
            />
          </div>

          <!-- 标题 + 元信息 -->
          <div class="flex-1 min-w-0">
            <p class="text-sm font-medium text-foreground truncate group-hover:text-primary transition-colors">
              {{ item.title }}
            </p>
            <p class="text-xs text-muted-foreground mt-0.5 truncate">
              <span v-if="item.repository_name" class="inline-flex items-center gap-1">
                <span class="icon-[lucide--git-branch] text-[0.7rem]" aria-hidden="true" />
                {{ item.repository_name }}
                <span aria-hidden="true">·</span>
              </span>
              {{ formatDate(item.updated_at) }}
            </p>
          </div>

          <!-- 状态徽标：等待人工 amber / 自动执行中 primary -->
          <span
            class="shrink-0 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium"
            :class="isWaiting(item.status)
              ? 'bg-amber-500/10 text-amber-600'
              : 'bg-primary/10 text-primary'"
          >
            <span
              v-if="!isWaiting(item.status)"
              class="icon-[lucide--loader-circle] animate-spin motion-reduce:animate-none"
              aria-hidden="true"
            />
            <span v-else class="icon-[lucide--user-round-check]" aria-hidden="true" />
            {{ item.status_label }}
          </span>

          <span
            class="icon-[lucide--chevron-right] text-muted-foreground/30 group-hover:text-primary group-hover:translate-x-0.5 transition-all"
            aria-hidden="true"
          />
        </RouterLink>
      </div>
    </div>
  </section>
</template>

<style scoped>
/* Lottie 双星环绕容器（进行中状态替换静态终端图标） */
.coding-orbit {
  display: inline-flex;
  width: 1.375rem;
  height: 1.375rem;
  flex-shrink: 0;
}
.coding-orbit :deep(svg) {
  display: block;
  width: 100%;
  height: 100%;
}
</style>
