<script setup lang="ts">
import type { Project, ProjectStatus } from '~/api/projects'
import { useI18n } from 'vue-i18n'
import { Avatar, AvatarFallback } from '~/components/ui/avatar'
import { Badge, type BadgeVariants } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '~/components/ui/tooltip'

// 左中右布局 · 顶部页头：返回 + 项目身份 + 飞书看板 + 项目配置入口（#8）。
// 归档/终止等状态流转收纳进「项目配置」弹窗，不再裸放页头。
const props = defineProps<{ project: Project, canManage: boolean }>()
const emit = defineEmits<{ back: [], settings: [] }>()

const { t } = useI18n()

function statusVariant(status: ProjectStatus): BadgeVariants['variant'] {
  switch (status) {
    case 'developing':
      return 'success'
    case 'terminated':
      return 'destructive'
    default:
      return 'muted'
  }
}
</script>

<template>
  <header
    class="h-14 shrink-0 flex items-center gap-2.5 px-2.5 sm:px-4 border-b border-border/60"
    data-testid="warroom-header"
  >
    <TooltipProvider :delay-duration="300">
      <Tooltip>
        <TooltipTrigger as-child>
          <button
            type="button"
            class="size-8 inline-flex items-center justify-center rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/70 transition-colors shrink-0"
            :aria-label="t('projects.warroom.workspace.back')"
            data-testid="warroom-back"
            @click="emit('back')"
          >
            <span class="icon-[lucide--arrow-left] text-base" />
          </button>
        </TooltipTrigger>
        <TooltipContent>{{ t('projects.warroom.workspace.back') }}</TooltipContent>
      </Tooltip>
    </TooltipProvider>

    <Avatar shape="square" class="size-8 rounded-lg bg-primary/10 ring-1 ring-primary/15 shrink-0">
      <AvatarFallback class="bg-transparent rounded-lg text-primary font-semibold text-sm">
        {{ (project.name || '?').slice(0, 1).toUpperCase() }}
      </AvatarFallback>
    </Avatar>

    <div class="min-w-0 flex-1">
      <div class="flex items-center gap-2">
        <h1 class="text-sm font-semibold text-foreground truncate">
          {{ project.name }}
        </h1>
        <Badge :variant="statusVariant(project.status)" class="shrink-0 px-1.5 py-0 text-[11px]">
          {{ t(`projects.status.${project.status}`) }}
        </Badge>
      </div>
      <p class="text-xs text-muted-foreground inline-flex items-center gap-1 truncate">
        <span class="icon-[lucide--folder-git-2] text-[11px]" />
        {{ project.space_name }}
      </p>
    </div>

    <div class="flex items-center gap-2 shrink-0">
      <a
        v-if="project.feishu_board_url"
        :href="project.feishu_board_url"
        target="_blank"
        rel="noopener noreferrer"
      >
        <Button variant="outline" size="sm">
          <span class="icon-[lucide--external-link] mr-1.5" />
          <span class="hidden sm:inline">{{ t('projects.detail.feishuBoard') }}</span>
        </Button>
      </a>
      <Button
        v-if="canManage"
        variant="outline"
        size="sm"
        data-testid="project-settings-btn"
        @click="emit('settings')"
      >
        <span class="icon-[lucide--settings] sm:mr-1.5" />
        <span class="hidden sm:inline">{{ t('projects.detail.settings') }}</span>
      </Button>
    </div>
  </header>
</template>
