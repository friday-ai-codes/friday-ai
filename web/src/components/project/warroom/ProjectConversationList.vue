<script setup lang="ts">
import type { Conversation } from '~/types/chat'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '~/components/ui/dropdown-menu'
import { ScrollArea } from '~/components/ui/scroll-area'
import { useConfirmDialog } from '~/composables/useConfirmDialog'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'
import { useAuthStore } from '~/stores/auth'
import { useChatStore } from '~/stores/chat'

// 左中右布局 · 左栏：项目会话列表（我的项目会话 / 项目共享会话）。
// 与中间对话区共用全局 useChatStore（项目作用域），三处状态实时一致。
const { t } = useI18n()
const { confirm } = useConfirmDialog()
const { handleError } = useErrorHandler()
const { success } = useToast()
const chatStore = useChatStore()
const auth = useAuthStore()

const groups = computed(() => {
  const shared: Conversation[] = []
  const mine: Conversation[] = []
  for (const c of chatStore.conversations) {
    if (c.is_archived)
      continue
    if (c.visibility === 'shared')
      shared.push(c)
    else
      mine.push(c)
  }
  return [
    { key: 'mine', label: t('projects.warroom.assistant.groupMine'), items: mine },
    { key: 'shared', label: t('projects.warroom.assistant.groupShared'), items: shared },
  ]
})

function canManageVisibility(c: Conversation): boolean {
  return (c.created_by?.id ?? null) === (auth.user?.id ?? null) && !!c.bound_project_id
}

async function onNew(visibility: 'personal' | 'shared') {
  try {
    await chatStore.createProjectConversation(visibility)
  }
  catch (e) {
    handleError(e, t('projects.warroom.assistant.newFailed'))
  }
}

async function onToggleVisibility(c: Conversation) {
  const toShared = c.visibility !== 'shared'
  const ok = await confirm({
    title: toShared
      ? t('projects.warroom.assistant.makeSharedTitle')
      : t('projects.warroom.assistant.makePersonalTitle'),
    description: toShared
      ? t('projects.warroom.assistant.makeSharedDesc')
      : t('projects.warroom.assistant.makePersonalDesc'),
    confirmText: t('projects.warroom.assistant.confirm'),
  })
  if (!ok)
    return
  try {
    await chatStore.setConversationVisibility(c.id, toShared ? 'shared' : 'personal')
    success(t('projects.warroom.assistant.visibilityChanged'))
  }
  catch (e) {
    handleError(e, t('projects.warroom.assistant.visibilityFailed'))
  }
}

async function onArchive(c: Conversation) {
  try {
    await chatStore.archiveConversation(c.id, !c.is_archived)
  }
  catch (e) {
    handleError(e, t('projects.warroom.assistant.archiveFailed'))
  }
}

async function onDelete(c: Conversation) {
  const ok = await confirm({
    title: t('projects.warroom.assistant.deleteTitle'),
    description: t('projects.warroom.assistant.deleteDesc'),
    confirmText: t('projects.warroom.assistant.confirm'),
    variant: 'destructive',
  })
  if (!ok)
    return
  try {
    await chatStore.removeConversation(c.id)
    success(t('projects.warroom.assistant.deleted'))
  }
  catch (e) {
    handleError(e, t('projects.warroom.assistant.deleteFailed'))
  }
}
</script>

<template>
  <div class="flex flex-col h-full min-h-0 bg-muted/30" data-testid="warroom-conv-list">
    <!-- 头部：标题 + 新建 -->
    <header class="h-12 shrink-0 flex items-center gap-2 px-4">
      <h2 class="text-sm font-semibold text-foreground tracking-wide flex-1">
        {{ t('projects.warroom.workspace.conversations') }}
      </h2>
      <DropdownMenu>
        <DropdownMenuTrigger
          class="size-7 inline-flex items-center justify-center rounded-md text-muted-foreground hover:text-primary hover:bg-primary/10 transition-colors"
          :aria-label="t('projects.warroom.workspace.newConversation')"
          data-testid="conv-new"
        >
          <span class="icon-[lucide--square-pen] text-[15px]" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem data-testid="conv-new-personal" @click="onNew('personal')">
            <span class="icon-[lucide--lock] mr-2" />{{ t('projects.warroom.assistant.newPersonal') }}
          </DropdownMenuItem>
          <DropdownMenuItem data-testid="conv-new-shared" @click="onNew('shared')">
            <span class="icon-[lucide--users] mr-2" />{{ t('projects.warroom.assistant.newShared') }}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </header>

    <ScrollArea class="flex-1 min-h-0">
      <div class="px-2 pb-3">
        <!-- 加载 -->
        <div v-if="chatStore.loading && chatStore.conversations.length === 0" class="px-3 py-10 text-center">
          <span class="icon-[lucide--loader-circle] animate-spin text-base text-muted-foreground/70" />
        </div>

        <!-- 空态 -->
        <div
          v-else-if="chatStore.conversations.length === 0"
          class="px-3 py-12 text-center"
        >
          <div class="mx-auto mb-3 flex size-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <span class="icon-[lucide--message-square-plus] text-lg" />
          </div>
          <p class="text-[13px] font-medium text-foreground">
            {{ t('projects.warroom.workspace.empty') }}
          </p>
          <p class="mt-1 text-xs text-muted-foreground leading-relaxed">
            {{ t('projects.warroom.workspace.emptyHint') }}
          </p>
        </div>

        <!-- 分组列表 -->
        <template v-for="group in groups" :key="group.key">
          <template v-if="group.items.length">
            <p class="px-2.5 pt-3 pb-1 text-[11px] font-semibold tracking-wide text-muted-foreground/80 select-none">
              {{ group.label }}
            </p>
            <div
              v-for="conv in group.items"
              :key="conv.id"
              role="button"
              tabindex="0"
              class="group flex items-center gap-2 rounded-lg px-2.5 py-2 cursor-pointer transition-colors text-foreground/70 hover:bg-border/50 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              :class="conv.id === chatStore.currentConversationId ? 'bg-primary/10 text-primary hover:bg-primary/12 hover:text-primary' : ''"
              data-testid="conv-item"
              @click="chatStore.selectConversation(conv.id)"
              @keydown.enter="chatStore.selectConversation(conv.id)"
            >
              <span
                class="shrink-0 text-xs opacity-70"
                :class="conv.visibility === 'shared' ? 'icon-[lucide--users]' : 'icon-[lucide--lock]'"
              />
              <span
                v-if="conv.status === 'running'"
                class="size-1.5 rounded-full bg-amber-500 shrink-0 animate-pulse"
                :title="t('projects.warroom.assistant.title')"
              />
              <p class="flex-1 min-w-0 truncate text-[13px]" :class="conv.id === chatStore.currentConversationId ? 'font-semibold' : ''">
                {{ conv.title || t('projects.warroom.assistant.noConversation') }}
              </p>

              <DropdownMenu>
                <DropdownMenuTrigger
                  class="size-6 inline-flex items-center justify-center rounded-md text-muted-foreground/60 opacity-0 group-hover:opacity-100 data-[state=open]:opacity-100 hover:bg-border/70 hover:text-foreground transition-opacity shrink-0"
                  :aria-label="t('projects.warroom.assistant.actions')"
                  data-testid="conv-item-menu"
                  @click.stop
                >
                  <span class="icon-[lucide--ellipsis] text-sm" />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem v-if="canManageVisibility(conv)" @click="onToggleVisibility(conv)">
                    <span class="icon-[lucide--shuffle] mr-2" />
                    {{ conv.visibility === 'shared' ? t('projects.warroom.assistant.makePersonal') : t('projects.warroom.assistant.makeShared') }}
                  </DropdownMenuItem>
                  <DropdownMenuItem @click="onArchive(conv)">
                    <span class="icon-[lucide--archive] mr-2" />
                    {{ conv.is_archived ? t('projects.warroom.assistant.unarchive') : t('projects.warroom.assistant.archive') }}
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem class="text-destructive" @click="onDelete(conv)">
                    <span class="icon-[lucide--trash-2] mr-2" />{{ t('projects.warroom.assistant.delete') }}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </template>
        </template>
      </div>
    </ScrollArea>
  </div>
</template>
