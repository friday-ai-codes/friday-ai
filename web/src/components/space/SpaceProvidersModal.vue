<script setup lang="ts">
/**
 * SpaceProvidersModal — 空间级 Provider 凭证管理弹窗
 *
 * 把原独立路由页 `pages/spaces/[id]/providers.vue` 的功能迁入空间详情页弹窗：
 * 复用 scope-aware 的 ProviderSettings 容器（scope='project' + spaceId，embedded 模式），
 * 新建凭证 CTA 由弹窗头部承载，调用 ProviderSettings 暴露的 openCreate()。
 *
 * 后端纵深防御（Permission + queryset 双层）才是权限权威；
 * 前端仅 UX 层渲染，非空间成员 API 会返空列表/404。
 */
import ProviderSettings from '~/components/providers/ProviderSettings.vue'
import { Button } from '~/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '~/components/ui/dialog'

defineProps<{
  spaceId: string
}>()

const open = defineModel<boolean>('open', { default: false })

const providerSettingsRef = ref<InstanceType<typeof ProviderSettings> | null>(null)
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent class="sm:max-w-4xl max-h-[85vh] overflow-y-auto">
      <DialogHeader>
        <div class="flex items-start justify-between gap-4 pr-8">
          <div class="space-y-1.5">
            <DialogTitle class="flex items-center gap-2">
              <span class="icon-[lucide--key-round] text-primary" />
              Provider 凭证
            </DialogTitle>
            <DialogDescription>
              仅本空间可见的 Provider 凭证，覆盖系统默认
            </DialogDescription>
          </div>
          <Button size="sm" class="shrink-0" @click="providerSettingsRef?.openCreate()">
            <span class="icon-[lucide--plus] w-4 h-4 mr-1" aria-hidden="true" />
            新建凭证
          </Button>
        </div>
      </DialogHeader>

      <ProviderSettings
        v-if="open"
        ref="providerSettingsRef"
        scope="project"
        :space-id="spaceId"
        embedded
      />
    </DialogContent>
  </Dialog>
</template>
