<script setup lang="ts">
import type { Project } from '~/api/projects'
import { useElementSize } from '@vueuse/core'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import ChatInput from '~/components/chat/ChatInput.vue'
import ChatMessageArea from '~/components/chat/ChatMessageArea.vue'
import ProjectConversationList from '~/components/project/warroom/ProjectConversationList.vue'
import ProjectMaterialsPanel from '~/components/project/warroom/ProjectMaterialsPanel.vue'
import ProjectOnboardingGuide from '~/components/project/warroom/ProjectOnboardingGuide.vue'
import { useFeatureListEditor } from '~/components/project/warroom/useFeatureListEditor'
import { useChatStore } from '~/stores/chat'

// 项目作战室 · 左中右工作台：左=会话列表，中=AI 对话，右=项目资料。
// 中间对话区复用全局 chat（同 useChatStore / 同 ChatMessageArea 渲染器 / 同 ChatInput），
// 仅把 store 切到当前项目作用域（会话按 bound_project 过滤、新建自动绑定项目）。
const props = defineProps<{ project: Project, canManage: boolean }>()

const { t } = useI18n()
const chatStore = useChatStore()

// #9 空项目上手引导（分步式）移到中间对话区顶部；「补充 feature list」打开录入弹窗。
const { openFeatureListEditor } = useFeatureListEditor()
function onAddFeatureList() {
  openFeatureListEditor(props.project.id)
}

onMounted(() => {
  chatStore.enterProjectScope(props.project.id, props.project.space_id)
})
// 离开项目页时解除作用域，避免把项目过滤带到全局 /chat（chat.vue 也会兜一次）。
onBeforeUnmount(() => chatStore.exitProjectScope())

// 按「实际可用容器宽度」做响应式（兼容全局侧栏折叠，不依赖视口断点）：
// 宽度不足时把左/右栏收成自带的滑出抽屉（悬浮层），由边缘把手 / 工具条唤起，
// 给中间对话腾出空间。
const rootEl = ref<HTMLElement | null>(null)
const { width } = useElementSize(rootEl)
// width=0 为测量前的初始态，默认按内联展示，避免首帧抽屉闪烁。
const leftInline = computed(() => width.value === 0 || width.value >= 860)
const rightInline = computed(() => width.value === 0 || width.value >= 1180)

const leftOpen = ref(false)
const rightOpen = ref(false)
const anyDrawerOpen = computed(() => (leftOpen.value && !leftInline.value) || (rightOpen.value && !rightInline.value))

// 切回内联宽度时自动收起抽屉，避免内联 + 抽屉重复渲染。
watch(leftInline, v => v && (leftOpen.value = false))
watch(rightInline, v => v && (rightOpen.value = false))

function closeDrawers() {
  leftOpen.value = false
  rightOpen.value = false
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape')
    closeDrawers()
}
onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div ref="rootEl" class="relative flex h-full min-h-0 overflow-hidden" data-testid="warroom-workspace">
    <!-- 左：会话列表（宽度足够时内联） -->
    <aside v-if="leftInline" class="flex w-64 shrink-0 border-r border-border/60">
      <ProjectConversationList class="w-full" />
    </aside>

    <!-- 中：AI 对话（复用全局 chat 渲染器 + 输入框） -->
    <main class="flex-1 min-w-0 flex flex-col bg-card">
      <!-- 折叠态工具条：仅在左栏被收起时出现 -->
      <div
        v-if="!leftInline"
        class="h-11 shrink-0 flex items-center px-2 border-b border-border/60"
      >
        <button
          type="button"
          class="inline-flex items-center gap-1.5 px-2.5 h-8 rounded-md text-sm text-muted-foreground hover:text-foreground hover:bg-muted/70 transition-colors"
          data-testid="warroom-open-left"
          @click="leftOpen = true"
        >
          <span class="icon-[lucide--messages-square] text-sm" />
          {{ t('projects.warroom.workspace.conversations') }}
        </button>
      </div>
      <!-- 空项目分步上手引导（无 feature 时显示，置于对话区上方） -->
      <ProjectOnboardingGuide
        :project-id="project.id"
        :can-manage="canManage"
        @add-feature-list="onAddFeatureList"
      />
      <div class="flex-1 min-h-0 relative">
        <ChatMessageArea />
        <ChatInput
          class="chat-input-float"
          @pin-confirmed="chatStore.patchConversationProviderAndModel"
        />
      </div>
    </main>

    <!-- 右：项目资料（宽度足够时内联） -->
    <aside v-if="rightInline" class="flex w-88 xl:w-96 shrink-0 border-l border-border/60">
      <ProjectMaterialsPanel :project="project" :can-manage="canManage" class="w-full" />
    </aside>

    <!-- 右侧悬浮把手：内联放不下时常驻右缘，点击从右侧滑出资料抽屉 -->
    <button
      v-if="!rightInline && !rightOpen"
      type="button"
      class="absolute right-0 top-1/2 -translate-y-1/2 z-20 flex flex-col items-center gap-1.5 rounded-l-xl border border-r-0 border-border/70 bg-card/95 backdrop-blur px-1.5 py-3 text-muted-foreground shadow-sm transition-colors hover:text-primary hover:border-primary/40"
      :aria-label="t('projects.warroom.workspace.materials')"
      data-testid="warroom-materials-handle"
      @click="rightOpen = true"
    >
      <span class="icon-[lucide--folder-git-2] text-base" />
      <span class="text-xs tracking-wide [writing-mode:vertical-rl]">
        {{ t('projects.warroom.workspace.materials') }}
      </span>
    </button>

    <!-- 抽屉遮罩（点击空白处收起） -->
    <Transition name="warroom-fade">
      <div
        v-if="anyDrawerOpen"
        class="absolute inset-0 z-30 bg-foreground/20 backdrop-blur-[1px]"
        data-testid="warroom-drawer-backdrop"
        @click="closeDrawers"
      />
    </Transition>

    <!-- 左侧会话抽屉 -->
    <Transition name="warroom-slide-left">
      <aside
        v-if="leftOpen && !leftInline"
        class="absolute inset-y-0 left-0 z-40 w-72 max-w-[85%] flex bg-background border-r border-border/60 shadow-2xl"
        role="dialog"
        aria-modal="true"
      >
        <ProjectConversationList class="w-full" />
      </aside>
    </Transition>

    <!-- 右侧资料抽屉（从右侧滑出的悬浮层） -->
    <Transition name="warroom-slide-right">
      <aside
        v-if="rightOpen && !rightInline"
        class="absolute inset-y-0 right-0 z-40 w-md max-w-[92%] flex flex-col bg-card border-l border-border/60 shadow-2xl"
        role="dialog"
        aria-modal="true"
        data-testid="warroom-materials-drawer"
      >
        <button
          type="button"
          class="absolute top-3 right-3 z-10 size-7 inline-flex items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/70 transition-colors"
          :aria-label="t('projects.warroom.workspace.close')"
          data-testid="warroom-materials-close"
          @click="rightOpen = false"
        >
          <span class="icon-[lucide--x] text-sm" />
        </button>
        <ProjectMaterialsPanel :project="project" :can-manage="canManage" class="flex-1 min-h-0" />
      </aside>
    </Transition>
  </div>
</template>

<style scoped>
/* 中间对话输入框浮于消息区底部（与 /chat 一致） */
.chat-input-float {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 10;
  pointer-events: none;
}

.warroom-fade-enter-active,
.warroom-fade-leave-active {
  transition: opacity 0.2s ease;
}
.warroom-fade-enter-from,
.warroom-fade-leave-to {
  opacity: 0;
}

.warroom-slide-right-enter-active,
.warroom-slide-right-leave-active,
.warroom-slide-left-enter-active,
.warroom-slide-left-leave-active {
  transition: transform 0.28s cubic-bezier(0.32, 0.72, 0, 1);
}
.warroom-slide-right-enter-from,
.warroom-slide-right-leave-to {
  transform: translateX(100%);
}
.warroom-slide-left-enter-from,
.warroom-slide-left-leave-to {
  transform: translateX(-100%);
}
</style>
