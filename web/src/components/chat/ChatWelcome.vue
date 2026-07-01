<script setup lang="ts">
import { gsap } from 'gsap'
import pulseRingsAnimation from '~/assets/lottie/pulseRings'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'

const chatStore = useChatStore()
const spacesStore = useSpacesStore()

// ============================================================================
// 入场动效：logo 弹入（背后 Lottie 涟漪光环）→ 标题/文案/引导卡片错拍浮现
// ============================================================================
const rootEl = ref<HTMLElement | null>(null)
const logoRingsEl = ref<HTMLElement | null>(null)

useLottie(logoRingsEl, pulseRingsAnimation)

useGsapReveal(rootEl, () => {
  gsap.timeline()
    .from('.welcome-logo-wrap', { y: 16, scale: 0.78, autoAlpha: 0, duration: 0.55, ease: 'back.out(1.8)', clearProps: 'all' })
    .from('.welcome-item', { y: 12, autoAlpha: 0, duration: 0.4, stagger: 0.07, ease: 'power2.out', clearProps: 'all' }, '-=0.25')
})

// 项目作战室内复用本组件作为对话空态：此时围绕「项目」而非「空间」，
// 不应再引导用户去创建/选择空间（boundProjectId 非空即项目作用域）。
const isProjectScope = computed(() => !!chatStore.boundProjectId)

const hasSpace = computed(() => !!chatStore.selectedSpaceId)
/** 实例里一个空间都没有：引导创建，或直接开始通用对话 */
const noSpacesExist = computed(() => spacesStore.spaces.length === 0)

const currentSpaceName = computed(() => {
  const space = spacesStore.spaces.find(s => s.id === chatStore.selectedSpaceId)
  return space?.name ?? ''
})

// 快捷提示词：点击填充到输入框（而非直接发送），用户可修改后再发
const quickPrompts = [
  { icon: 'icon-[lucide--folder-tree]', label: '了解空间结构', prompt: '请列出当前空间的文件结构，并概述各模块的作用' },
  { icon: 'icon-[lucide--code-2]', label: '解释核心代码', prompt: '请帮我解释空间中的核心代码逻辑' },
  { icon: 'icon-[lucide--search]', label: '搜索代码实现', prompt: '请帮我在空间中搜索相关的代码实现：' },
  { icon: 'icon-[lucide--file-text]', label: '生成空间概览', prompt: '请给我一个当前空间的整体概览' },
]

// 项目作用域的提示词：围绕需求拆解 / 仓库关联 / 技术方案 / 项目现状。
const projectPrompts = [
  { icon: 'icon-[lucide--list-tree]', label: '拆解需求', prompt: '帮我把这个项目的需求拆解成 feature list（模块 → 功能点 → 验收项）' },
  { icon: 'icon-[lucide--git-branch]', label: '梳理仓库', prompt: '这个项目可能涉及哪些代码仓库？帮我分析业务与仓库的关联' },
  { icon: 'icon-[lucide--file-text]', label: '生成技术方案', prompt: '基于当前需求，帮我生成一份技术方案' },
  { icon: 'icon-[lucide--gauge]', label: '项目现状', prompt: '总结一下这个项目当前的交付现状和下一步建议' },
]

const activePrompts = computed(() => (isProjectScope.value ? projectPrompts : quickPrompts))

function handleQuickPrompt(prompt: string) {
  chatStore.prefillDraft(prompt)
}
</script>

<template>
  <div class="welcome-stage h-full flex items-center justify-center">
    <div class="w-full max-w-xl px-6 pb-36 text-center">
      <!-- Logo + 问候 -->
      <div class="welcome-logo-wrap relative mx-auto w-14 h-14 mb-5">
        <!-- Lottie 涟漪光环：在 logo 背后缓缓扩散 -->
        <div
          ref="logoRingsEl"
          class="absolute -inset-5 pointer-events-none"
          aria-hidden="true"
        />
        <img
          src="/logo-mark.svg"
          alt="Friday"
          class="welcome-logo relative w-14 h-14"
        >
      </div>
      <h1 class="welcome-item text-2xl font-semibold tracking-tight text-foreground">
        有什么可以帮你？
      </h1>
      <p class="welcome-item mt-2 text-sm text-muted-foreground">
        <template v-if="isProjectScope">
          围绕这个项目提问，也可以让我拆解需求、生成技术方案
        </template>
        <template v-else-if="hasSpace">
          可以问「{{ currentSpaceName }}」空间里的代码
        </template>
        <template v-else-if="noSpacesExist">
          还没有空间，创建后可以问代码，也可以直接开始对话
        </template>
        <template v-else>
          选个空间可以问代码，或直接开始对话
        </template>
      </p>

      <!-- 实例无任何空间：引导创建 or 直接对话（项目作用域内不引导空间） -->
      <div v-if="!isProjectScope && noSpacesExist" class="welcome-item mt-8 flex justify-center">
        <div class="welcome-space-card">
          <div class="flex items-center gap-2.5 text-left">
            <span class="welcome-space-icon">
              <span class="icon-[lucide--folder-plus] text-lg" />
            </span>
            <div>
              <p class="text-[13px] font-semibold text-foreground">
                还没有空间
              </p>
              <p class="text-xs text-muted-foreground">
                空间绑定代码仓库后，AI 才能回答代码相关问题
              </p>
            </div>
          </div>
          <div class="mt-3 flex gap-2">
            <RouterLink to="/spaces" class="welcome-cta-primary flex-1">
              <span class="icon-[lucide--plus] text-[13px]" />
              去创建空间
            </RouterLink>
          </div>
          <p class="mt-2.5 text-center text-xs text-muted-foreground/70">
            或直接在下方输入框开始通用对话
          </p>
        </div>
      </div>

      <!-- 有空间但未选：引导选择（也允许直接对话；项目作用域内不引导空间） -->
      <div v-else-if="!isProjectScope && !hasSpace" class="welcome-item mt-8 flex justify-center">
        <div class="welcome-space-card">
          <div class="flex items-center gap-2.5 text-left">
            <span class="welcome-space-icon">
              <span class="icon-[lucide--folder-git-2] text-lg" />
            </span>
            <div>
              <p class="text-[13px] font-semibold text-foreground">
                选择空间
              </p>
              <p class="text-xs text-muted-foreground">
                对话将围绕该空间的代码展开
              </p>
            </div>
          </div>
          <Select v-model="chatStore.selectedSpaceId">
            <SelectTrigger class="mt-3 w-full h-9 text-[13px]">
              <SelectValue placeholder="请选择一个空间..." />
            </SelectTrigger>
            <SelectContent>
              <SelectItem
                v-for="space in spacesStore.spaces"
                :key="space.id"
                :value="space.id"
              >
                {{ space.name }}
              </SelectItem>
            </SelectContent>
          </Select>
          <p class="mt-2.5 text-center text-xs text-muted-foreground/70">
            不选空间也可以直接开始通用对话
          </p>
        </div>
      </div>

      <!-- 已选空间 / 项目作用域：快捷提示 -->
      <div v-else class="mt-8 grid grid-cols-2 gap-2.5">
        <button
          v-for="item in activePrompts"
          :key="item.label"
          type="button"
          class="welcome-prompt-card welcome-item group"
          @click="handleQuickPrompt(item.prompt)"
        >
          <span class="welcome-prompt-icon">
            <span :class="item.icon" class="text-base" />
          </span>
          <span class="text-[13px] font-medium text-foreground/85 group-hover:text-foreground transition-colors">
            {{ item.label }}
          </span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.welcome-logo {
  filter: drop-shadow(0 6px 16px hsl(168 76% 42% / 0.25));
}

.welcome-space-card {
  width: 20rem;
  padding: 1rem;
  border-radius: 1rem;
  border: 1px solid hsl(214 32% 89%);
  background: hsl(0 0% 100% / 0.85);
  box-shadow:
    0 4px 14px hsl(215 28% 17% / 0.05),
    inset 0 1px 0 hsl(0 0% 100% / 0.9);
}

.welcome-cta-primary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.375rem;
  height: 2.25rem;
  padding: 0 0.875rem;
  border-radius: 0.625rem;
  background: hsl(168 76% 42%);
  color: white;
  font-size: 0.8125rem;
  font-weight: 600;
  transition:
    background-color 0.15s ease,
    box-shadow 0.15s ease;
  box-shadow: 0 1px 3px hsl(168 76% 42% / 0.3);
}

.welcome-cta-primary:hover {
  background: hsl(167 76% 36%);
}

.welcome-space-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 2.25rem;
  height: 2.25rem;
  border-radius: 0.75rem;
  background: hsl(168 76% 42% / 0.1);
  color: hsl(168 76% 36%);
  flex-shrink: 0;
}

.welcome-prompt-card {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  padding: 0.75rem 0.875rem;
  border-radius: 0.875rem;
  border: 1px solid hsl(214 32% 90%);
  background: hsl(0 0% 100% / 0.72);
  text-align: left;
  cursor: pointer;
  transition:
    border-color 0.18s ease,
    background-color 0.18s ease,
    box-shadow 0.18s ease,
    transform 0.18s ease;
}

.welcome-prompt-card:hover {
  border-color: hsl(168 76% 42% / 0.35);
  background: hsl(0 0% 100%);
  box-shadow: 0 4px 14px hsl(215 28% 17% / 0.06);
  transform: translateY(-1px);
}

.welcome-prompt-card:focus-visible {
  outline: 2px solid hsl(168 76% 42% / 0.5);
  outline-offset: 2px;
}

.welcome-prompt-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  border-radius: 0.625rem;
  background: hsl(168 76% 42% / 0.09);
  color: hsl(168 76% 38%);
  flex-shrink: 0;
  transition: background-color 0.18s ease;
}

.welcome-prompt-card:hover .welcome-prompt-icon {
  background: hsl(168 76% 42% / 0.14);
}
</style>
