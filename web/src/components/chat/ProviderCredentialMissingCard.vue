<script setup lang="ts">
/**
 * — ProviderCredentialMissingCard（ /）
 *
 * 凭证缺失前置探测卡片：preflight 返回 code=provider_credential_missing 时，
 * ChatMessageArea 将本组件挂入系统消息插槽，展示结构化引导（非 toast / 非独立 modal）。
 *
 * D-05 CTA 按角色分流（始终显示两按钮）：
 *   - system_admin → 主按钮 "去系统设置"（default variant，跳 /admin/providers）
 *                     + 次按钮 "去空间设置"（outline variant，跳 /spaces/{id}/settings#providers）
 *   - project_admin / member / viewer → 主按钮 "去空间设置"（default variant）
 *                     + 次按钮 "去系统设置"（outline variant，disabled + tooltip "需系统管理员权限"）
 *
 * Analog: ProviderHealthBadge.vue（Tooltip disabled 按钮模板）+ CodingErrorCard.vue（系统消息卡片模式）。
 * Style: Sub2API Clean Card（禁用玻璃拟态 blur / bg-white/40 光晕层 / UI-SPEC L33 纠偏）。
 */
import type { ProviderType } from '~/types/providerCredential'
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { Button } from '~/components/ui/button'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '~/components/ui/tooltip'

export type UserRole = 'system_admin' | 'project_admin' | 'member' | 'viewer'

const props = defineProps<{
  missingProvider: ProviderType
  userRole: UserRole
  spaceId: string
}>()

/** Provider 中文品牌名映射（UI-SPEC §Copywriting L285）。 */
const PROVIDER_LABEL: Record<ProviderType, string> = {
  anthropic: 'Anthropic',
  openai_responses: 'OpenAI（Responses）',
  openai_chat: 'OpenAI（Chat）',
  gemini: 'Gemini',
  ollama: 'Ollama',
}

const providerLabel = computed(() => PROVIDER_LABEL[props.missingProvider] ?? props.missingProvider)
const isSystemAdmin = computed(() => props.userRole === 'system_admin')
const spaceSettingsUrl = computed(() => `/spaces/${props.spaceId}/settings#providers`)
</script>

<template>
  <div class="card p-6 my-12" role="alert" aria-live="polite">
    <div class="flex items-start gap-2">
      <span class="icon-[lucide--alert-circle] text-destructive text-xl shrink-0 mt-0.5" aria-hidden="true" />
      <div class="flex-1 space-y-2">
        <h3 class="text-base font-semibold">
          未配置 {{ providerLabel }} 凭证
        </h3>
        <p class="text-sm text-muted-foreground leading-6">
          当前对话解析到的 Provider 为 {{ providerLabel }}，但系统与空间均未配置可用凭证。请添加凭证后重新发送消息。
        </p>

        <div class="flex items-center gap-2 pt-2">
          <!-- Primary CTA：system_admin → 去系统设置；其他 → 去空间设置 -->
          <RouterLink v-if="isSystemAdmin" to="/admin/providers">
            <Button variant="default">
              去系统设置
            </Button>
          </RouterLink>
          <RouterLink v-else :to="spaceSettingsUrl">
            <Button variant="default">
              去空间设置
            </Button>
          </RouterLink>

          <!-- Secondary CTA：system_admin → 去空间设置（可点击）；其他 → 去系统设置 disabled + tooltip -->
          <RouterLink v-if="isSystemAdmin" :to="spaceSettingsUrl">
            <Button variant="outline">
              去空间设置
            </Button>
          </RouterLink>
          <TooltipProvider v-else :delay-duration="150">
            <Tooltip>
              <TooltipTrigger as-child>
                <span>
                  <Button
                    variant="outline"
                    disabled
                    aria-label="去系统设置（需系统管理员权限）"
                    title="需系统管理员权限"
                  >
                    去系统设置
                  </Button>
                </span>
              </TooltipTrigger>
              <TooltipContent class="max-w-xs text-xs font-normal">
                需系统管理员权限
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>
      </div>
    </div>
  </div>
</template>
