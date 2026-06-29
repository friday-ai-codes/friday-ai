<script setup lang="ts">
import type { FeatureNode } from '~/api/projectWorkspace'
import { useQuery } from '@tanstack/vue-query'
import { useLocalStorage } from '@vueuse/core'
import { computed, ref, toRef } from 'vue'
import { projectWorkspaceApi } from '~/api/projectWorkspace'
import { useChatStore } from '~/stores/chat'

// #9 空项目上手引导（分步式 stepper）：随中间对话区顶部呈现，一次只看一步，可前进/后退。
// 无 feature 时显示；有 feature 自动隐藏；用户可「跳过」（按项目记忆，localStorage）。
const props = defineProps<{ projectId: string, canManage?: boolean }>()
const emit = defineEmits<{ 'add-feature-list': [] }>()

const chatStore = useChatStore()
const projectIdRef = toRef(props, 'projectId')

const { data } = useQuery({
  queryKey: ['project-features', projectIdRef],
  queryFn: () => projectWorkspaceApi.getFeatureList(props.projectId),
})

const featureCount = computed(() => {
  const d = data.value as FeatureNode[] | { modules?: FeatureNode[] } | undefined
  const modules = Array.isArray(d) ? d : (d?.modules ?? [])
  let n = 0
  const walk = (ns: FeatureNode[]) => {
    for (const node of ns ?? []) {
      if (node.kind === 'feature')
        n += 1
      if (node.children?.length)
        walk(node.children)
    }
  }
  walk(modules)
  return n
})

// 跳过状态按项目记忆（不跨项目）。
const dismissed = useLocalStorage(`project-onboarding-dismissed-${props.projectId}`, false)
const visible = computed(() => featureCount.value === 0 && !dismissed.value)

interface Step {
  title: string
  desc: string
  cta: string
  icon: string
  action: () => void
}

function prefill(prompt: string) {
  chatStore.prefillDraft(prompt)
}

const steps = computed<Step[]>(() => [
  {
    title: '补充 feature list',
    desc: '手动录入「模块 → 功能点 → 验收项」，或贴 GitLab 文档 / 粘贴整篇文档让 AI 解析。',
    cta: '去补充',
    icon: 'icon-[lucide--list-tree]',
    action: () => emit('add-feature-list'),
  },
  {
    title: '关联业务仓库',
    desc: '让 AI 结合知识库分析这个项目涉及哪些代码仓库并确认关联。',
    cta: '让 AI 梳理',
    icon: 'icon-[lucide--git-branch]',
    action: () => prefill('这个项目可能涉及哪些代码仓库？帮我分析业务与仓库的关联，并给出确认建议'),
  },
  {
    title: '生成技术方案',
    desc: '基于需求与仓库，产出 per-repo + 整体技术方案，多轮澄清后定稿。',
    cta: '生成方案',
    icon: 'icon-[lucide--file-text]',
    action: () => prefill('基于当前项目的需求，帮我生成一份技术方案'),
  },
  {
    title: '建分支并编码',
    desc: '方案确认后按方案建分支、绑定项目，交给 AI 编码代理执行。',
    cta: '了解流程',
    icon: 'icon-[lucide--git-merge]',
    action: () => prefill('方案确认后，如何按方案建分支并开始编码？帮我说明接下来的步骤'),
  },
  {
    title: '跟踪交付现状',
    desc: '在右侧大盘看 feature 进度灯、待合并 MR、文档同步与下一步建议。',
    cta: '看现状',
    icon: 'icon-[lucide--gauge]',
    action: () => prefill('总结一下这个项目当前的交付现状和下一步建议'),
  },
])

const stepIndex = ref(0)
const total = computed(() => steps.value.length)
const current = computed(() => steps.value[stepIndex.value])
const isFirst = computed(() => stepIndex.value === 0)
const isLast = computed(() => stepIndex.value === total.value - 1)

function next() {
  if (!isLast.value)
    stepIndex.value += 1
}
function prev() {
  if (!isFirst.value)
    stepIndex.value -= 1
}
function runAndAdvance() {
  current.value.action()
  next()
}
</script>

<template>
  <section
    v-if="visible"
    class="shrink-0 border-b border-border/60 bg-gradient-to-b from-primary/[0.05] to-transparent"
    data-testid="project-onboarding"
  >
    <div class="mx-auto w-full max-w-2xl px-4 py-3">
      <!-- 头部：标题 + 进度 + 跳过 -->
      <div class="flex items-center gap-2">
        <span class="inline-flex size-6 items-center justify-center rounded-md bg-primary/12 text-primary">
          <span class="icon-[lucide--rocket] text-xs" />
        </span>
        <h3 class="text-xs font-semibold text-foreground">
          空项目上手引导
        </h3>
        <span class="text-[11px] text-muted-foreground tabular-nums">
          第 {{ stepIndex + 1 }} / {{ total }} 步
        </span>
        <!-- 进度点 -->
        <div class="ml-1 flex items-center gap-1">
          <button
            v-for="(_, i) in steps"
            :key="i"
            type="button"
            class="size-1.5 rounded-full transition-colors"
            :class="i === stepIndex ? 'bg-primary' : i < stepIndex ? 'bg-primary/40' : 'bg-border'"
            :aria-label="`跳到第 ${i + 1} 步`"
            @click="stepIndex = i"
          />
        </div>
        <button
          type="button"
          class="ml-auto text-[11px] text-muted-foreground hover:text-foreground transition-colors"
          data-testid="onboarding-dismiss"
          @click="dismissed = true"
        >
          跳过引导
        </button>
      </div>

      <!-- 当前步骤 -->
      <div class="mt-2 flex items-center gap-3">
        <span class="inline-flex size-8 shrink-0 items-center justify-center rounded-lg bg-card border border-border/60 text-primary">
          <span :class="current.icon" class="text-sm" />
        </span>
        <div class="min-w-0 flex-1">
          <p class="text-sm font-medium text-foreground">
            {{ current.title }}
          </p>
          <p class="text-xs text-muted-foreground truncate">
            {{ current.desc }}
          </p>
        </div>
        <div class="flex items-center gap-1.5 shrink-0">
          <button
            type="button"
            class="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/70 disabled:opacity-30 transition-colors"
            :disabled="isFirst"
            aria-label="上一步"
            @click="prev"
          >
            <span class="icon-[lucide--chevron-left] text-sm" />
          </button>
          <button
            type="button"
            class="inline-flex items-center gap-1 rounded-md bg-primary px-2.5 h-7 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
            :disabled="stepIndex === 0 && !canManage"
            :data-testid="`onboarding-step-${stepIndex + 1}`"
            @click="runAndAdvance"
          >
            {{ current.cta }}
            <span class="icon-[lucide--arrow-right] text-[11px]" />
          </button>
          <button
            type="button"
            class="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/70 disabled:opacity-30 transition-colors"
            :disabled="isLast"
            aria-label="下一步"
            @click="next"
          >
            <span class="icon-[lucide--chevron-right] text-sm" />
          </button>
        </div>
      </div>
    </div>
  </section>
</template>
