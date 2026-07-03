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
    desc: '粘贴需求文档自动解析，或手动录入模块和功能点。',
    cta: '去补充',
    icon: 'icon-[lucide--list-tree]',
    action: () => emit('add-feature-list'),
  },
  {
    title: '关联业务仓库',
    desc: '梳理这个项目涉及哪些代码仓库并确认关联。',
    cta: '开始梳理',
    icon: 'icon-[lucide--git-branch]',
    action: () => prefill('这个项目可能涉及哪些代码仓库？帮我分析业务与仓库的关联，并给出确认建议'),
  },
  {
    title: '生成技术方案',
    desc: '按需求和仓库产出技术方案，多轮澄清后定稿。',
    cta: '生成方案',
    icon: 'icon-[lucide--file-text]',
    action: () => prefill('基于当前项目的需求，帮我生成一份技术方案'),
  },
  {
    title: '建分支并编码',
    desc: '方案定稿后建分支、绑定项目，交给编码代理执行。',
    cta: '了解流程',
    icon: 'icon-[lucide--git-merge]',
    action: () => prefill('方案确认后，如何按方案建分支并开始编码？帮我说明接下来的步骤'),
  },
  {
    title: '跟踪交付现状',
    desc: '在右侧大盘查看进度、待合并 MR 和下一步建议。',
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
    class="shrink-0 border-b border-border/60 bg-gradient-to-b from-primary/[0.04] to-transparent"
    data-testid="project-onboarding"
  >
    <div class="mx-auto w-full max-w-2xl px-4 pt-3 pb-3.5">
      <!-- 头部：标题 + 分段进度条 + 跳过 -->
      <div class="flex items-center gap-2.5">
        <h3 class="flex items-center gap-1.5 text-xs font-semibold text-foreground shrink-0">
          <span class="icon-[lucide--rocket] text-primary text-sm" />
          上手引导
        </h3>
        <span class="text-[11px] text-muted-foreground/80 tabular-nums shrink-0">
          {{ stepIndex + 1 }}/{{ total }}
        </span>
        <!-- 分段进度条（可点跳步，比进度点更清晰、触达面积更大） -->
        <div class="flex flex-1 items-center gap-1" role="tablist" aria-label="引导步骤">
          <button
            v-for="(s, i) in steps"
            :key="i"
            type="button"
            role="tab"
            class="h-1 flex-1 cursor-pointer rounded-full transition-colors duration-200"
            :class="i < stepIndex ? 'bg-primary/50 hover:bg-primary/70'
              : i === stepIndex ? 'bg-primary'
                : 'bg-border hover:bg-border/80'"
            :aria-selected="i === stepIndex"
            :aria-label="`第 ${i + 1} 步：${s.title}`"
            :title="s.title"
            @click="stepIndex = i"
          />
        </div>
        <button
          type="button"
          class="shrink-0 cursor-pointer text-[11px] text-muted-foreground/70 hover:text-foreground transition-colors"
          data-testid="onboarding-dismiss"
          @click="dismissed = true"
        >
          跳过
        </button>
      </div>

      <!-- 当前步骤卡片：图标台 + 内容 + 主 CTA，一体成型 -->
      <div class="mt-2.5 flex items-center gap-3.5 rounded-xl border border-border/60 bg-card px-3.5 py-3 shadow-[0_1px_2px_rgb(0_0_0/0.04)]">
        <span class="relative inline-flex size-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary/15 to-primary/5 text-primary">
          <span :class="current.icon" class="text-base" />
          <span class="absolute -right-1 -top-1 inline-flex size-4 items-center justify-center rounded-full bg-primary text-[9px] font-semibold text-primary-foreground tabular-nums">
            {{ stepIndex + 1 }}
          </span>
        </span>
        <div class="min-w-0 flex-1">
          <p class="text-sm font-semibold text-foreground leading-snug">
            {{ current.title }}
          </p>
          <p class="mt-0.5 text-xs text-muted-foreground leading-relaxed truncate">
            {{ current.desc }}
          </p>
        </div>
        <div class="flex items-center gap-1 shrink-0">
          <button
            type="button"
            class="inline-flex size-7 cursor-pointer items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/70 disabled:opacity-30 disabled:cursor-default transition-colors"
            :disabled="isFirst"
            aria-label="上一步"
            @click="prev"
          >
            <span class="icon-[lucide--chevron-left] text-sm" />
          </button>
          <button
            type="button"
            class="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-lg bg-primary px-3.5 text-xs font-medium text-primary-foreground shadow-sm hover:bg-primary/90 active:scale-[0.98] disabled:opacity-50 transition-all duration-150"
            :disabled="stepIndex === 0 && !canManage"
            :data-testid="`onboarding-step-${stepIndex + 1}`"
            @click="runAndAdvance"
          >
            {{ current.cta }}
            <span class="icon-[lucide--arrow-right] text-[11px]" />
          </button>
          <button
            type="button"
            class="inline-flex size-7 cursor-pointer items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/70 disabled:opacity-30 disabled:cursor-default transition-colors"
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
