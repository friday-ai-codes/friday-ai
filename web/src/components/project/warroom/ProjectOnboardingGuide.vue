<script setup lang="ts">
import type { FeatureNode } from '~/api/projectWorkspace'
import { useQuery } from '@tanstack/vue-query'
import { computed, toRef } from 'vue'
import { projectWorkspaceApi } from '~/api/projectWorkspace'
import { useChatStore } from '~/stores/chat'

// #9 空项目引导：当项目还没有任何 feature 时，给出「1-2-3-4-5」上手步骤。
// 第 1 步（补充 feature list）由父级接管打开录入入口；其余步骤把引导提示词
// 预填到中间 AI 对话输入框（chatStore.prefillDraft），用户可改后发送。
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

// 有 feature 即视为项目已启动，不再显示上手引导。
const visible = computed(() => featureCount.value === 0)

interface Step {
  n: number
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
    n: 1,
    title: '补充 feature list',
    desc: '手动录入「模块 → 功能点 → 验收项」，或贴飞书多维表格链接同步进来。',
    cta: '去补充',
    icon: 'icon-[lucide--list-tree]',
    action: () => emit('add-feature-list'),
  },
  {
    n: 2,
    title: '关联业务仓库',
    desc: '让 AI 结合知识库分析这个项目涉及哪些代码仓库并确认关联。',
    cta: '让 AI 梳理',
    icon: 'icon-[lucide--git-branch]',
    action: () => prefill('这个项目可能涉及哪些代码仓库？帮我分析业务与仓库的关联，并给出确认建议'),
  },
  {
    n: 3,
    title: '生成技术方案',
    desc: '基于需求与仓库，产出 per-repo + 整体技术方案，多轮澄清后定稿。',
    cta: '生成方案',
    icon: 'icon-[lucide--file-text]',
    action: () => prefill('基于当前项目的需求，帮我生成一份技术方案'),
  },
  {
    n: 4,
    title: '建分支并编码',
    desc: '方案确认后按方案建分支、绑定项目，交给 AI 编码代理执行。',
    cta: '了解流程',
    icon: 'icon-[lucide--git-merge]',
    action: () => prefill('方案确认后，如何按方案建分支并开始编码？帮我说明接下来的步骤'),
  },
  {
    n: 5,
    title: '跟踪交付现状',
    desc: '在右侧大盘看 feature 进度灯、待合并 MR、文档同步与下一步建议。',
    cta: '看现状',
    icon: 'icon-[lucide--gauge]',
    action: () => prefill('总结一下这个项目当前的交付现状和下一步建议'),
  },
])
</script>

<template>
  <section v-if="visible" class="px-4 py-4" data-testid="project-onboarding">
    <div class="rounded-xl border border-primary/20 bg-primary/[0.04] p-4">
      <div class="flex items-center gap-2 mb-3">
        <span class="inline-flex size-7 items-center justify-center rounded-md bg-primary/12 text-primary">
          <span class="icon-[lucide--rocket] text-sm" />
        </span>
        <div class="min-w-0">
          <h3 class="text-sm font-semibold text-foreground">
            空项目上手引导
          </h3>
          <p class="text-xs text-muted-foreground">
            按下面 5 步把需求一路跑成 PR；每步都能让右侧 AI 帮你做。
          </p>
        </div>
      </div>

      <ol class="space-y-2">
        <li
          v-for="step in steps"
          :key="step.n"
          class="flex items-start gap-3 rounded-lg border border-border/50 bg-card/60 px-3 py-2.5"
        >
          <span class="mt-0.5 inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-primary/15 text-[11px] font-semibold text-primary tabular-nums">
            {{ step.n }}
          </span>
          <div class="min-w-0 flex-1">
            <p class="text-sm font-medium text-foreground inline-flex items-center gap-1.5">
              <span :class="step.icon" class="text-muted-foreground" />
              {{ step.title }}
            </p>
            <p class="text-xs text-muted-foreground mt-0.5">
              {{ step.desc }}
            </p>
          </div>
          <button
            type="button"
            class="shrink-0 self-center inline-flex items-center gap-1 rounded-md border border-primary/30 px-2 py-1 text-xs text-primary hover:bg-primary/10 transition-colors disabled:opacity-50"
            :disabled="step.n === 1 && !canManage"
            :data-testid="`onboarding-step-${step.n}`"
            @click="step.action"
          >
            {{ step.cta }}
            <span class="icon-[lucide--arrow-right] text-[11px]" />
          </button>
        </li>
      </ol>
    </div>
  </section>
</template>
