<script setup lang="ts">
/**
 * Provider 凭证列表表格（Quick UI 重设计）
 *
 * 设计基线：Data-Dense Dashboard —— 轻量徽标、品牌图标芯片、清晰层级、行 hover、
 * 统一 8px 节奏。修复旧版「作用域」绿色重徽标换行（系统默/认）、疏密失衡问题。
 */
import type { ProviderCredentialDto, ProviderType } from '~/types/providerCredential'
import { Button } from '~/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '~/components/ui/dropdown-menu'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'
import { Switch } from '~/components/ui/switch'
import { getProviderBrandColor } from '~/lib/providerBrandColors'
import ProviderHealthBadge from './ProviderHealthBadge.vue'

interface Props {
  credentials: ProviderCredentialDto[]
}

defineProps<Props>()

const emit = defineEmits<{
  (e: 'edit', c: ProviderCredentialDto): void
  (e: 'delete', c: ProviderCredentialDto): void
  (e: 'toggleActive', c: ProviderCredentialDto): void
  (e: 'testConnection', c: ProviderCredentialDto): void
  (e: 'refreshModels', c: ProviderCredentialDto): void
  (e: 'setDefault', c: ProviderCredentialDto): void
  (e: 'setDefaultModel', c: ProviderCredentialDto, modelId: string): void
}>()

const PROVIDER_LABELS: Record<string, string> = {
  anthropic: 'Anthropic',
  openai_chat: 'OpenAI Chat',
  openai_responses: 'OpenAI Responses',
  gemini: 'Gemini',
  ollama: 'Ollama',
}

function iconFor(providerType: string): string {
  const map: Record<string, string> = {
    anthropic: 'icon-[simple-icons--anthropic]',
    openai_chat: 'icon-[simple-icons--openai]',
    openai_responses: 'icon-[simple-icons--openai]',
    gemini: 'icon-[simple-icons--googlegemini]',
    ollama: 'icon-[lucide--cpu]',
  }
  return map[providerType] ?? 'icon-[lucide--key-round]'
}

function providerLabel(t: ProviderType): string {
  return PROVIDER_LABELS[t] ?? t
}

function onDefaultModelChange(c: ProviderCredentialDto, modelId: unknown) {
  const v = typeof modelId === 'string' ? modelId : ''
  if (v && v !== c.default_model)
    emit('setDefaultModel', c, v)
}
</script>

<template>
  <div class="overflow-hidden rounded-xl border border-border/60">
    <table class="w-full border-collapse text-sm">
      <thead>
        <tr class="border-b border-border/60 bg-muted/30">
          <th class="px-4 py-2.5 text-left text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Provider
          </th>
          <th class="px-4 py-2.5 text-left text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            凭证
          </th>
          <th class="hidden lg:table-cell px-4 py-2.5 text-left text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            作用域
          </th>
          <th class="hidden md:table-cell px-4 py-2.5 text-left text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            默认模型
          </th>
          <th class="px-4 py-2.5 text-left text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            健康
          </th>
          <th class="px-4 py-2.5 text-center text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            启用
          </th>
          <th class="px-4 py-2.5 text-right text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            操作
          </th>
        </tr>
      </thead>
      <tbody class="divide-y divide-border/50">
        <tr
          v-for="c in credentials"
          :key="c.id"
          class="group transition-colors hover:bg-muted/40"
          :class="{ 'opacity-55': !c.is_active }"
        >
          <!-- Provider：品牌图标芯片 + 显示名 -->
          <td class="px-4 py-3.5">
            <div class="flex items-center gap-2.5">
              <span
                class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
                :class="getProviderBrandColor(c.provider_type).bg"
                aria-hidden="true"
              >
                <span
                  class="h-4 w-4"
                  :class="[iconFor(c.provider_type), getProviderBrandColor(c.provider_type).text]"
                />
              </span>
              <span class="font-medium text-foreground">{{ providerLabel(c.provider_type) }}</span>
            </div>
          </td>

          <!-- 凭证名称 + 默认星标 + last4 -->
          <td class="px-4 py-3.5">
            <div class="flex items-center gap-1.5">
              <span class="truncate font-medium text-foreground">{{ c.name }}</span>
              <span
                v-if="c.is_default"
                class="inline-flex shrink-0 items-center gap-0.5 rounded-md bg-amber-400/15 px-1.5 py-0.5 text-[10px] font-medium text-amber-600"
                title="该维度默认凭证"
              >
                <span class="icon-[lucide--star] h-2.5 w-2.5" aria-hidden="true" />
                默认
              </span>
            </div>
            <span v-if="c.api_key_last4" class="font-mono text-xs text-muted-foreground">
              {{ c.api_key_last4 }}
            </span>
          </td>

          <!-- 作用域：轻量中性 chip（whitespace-nowrap 修复换行） -->
          <td class="hidden lg:table-cell px-4 py-3.5">
            <span
              class="inline-flex items-center gap-1 whitespace-nowrap rounded-md border border-border/60 bg-muted/40 px-2 py-0.5 text-xs text-muted-foreground"
            >
              <span
                class="h-3 w-3"
                :class="c.scope === 'system' ? 'icon-[lucide--globe]' : 'icon-[lucide--folder-lock]'"
                aria-hidden="true"
              />
              {{ c.scope === 'system' ? '系统' : '本空间' }}
            </span>
          </td>

          <!-- 默认模型：有清单 → 下拉切换；否则纯文本 -->
          <td class="hidden md:table-cell px-4 py-3.5">
            <Select
              v-if="(c.available_models?.length ?? 0) > 0"
              :model-value="c.default_model || ''"
              @update:model-value="onDefaultModelChange(c, $event)"
            >
              <SelectTrigger class="h-8 min-w-44 max-w-56 text-xs">
                <SelectValue placeholder="选择默认模型" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem
                  v-for="m in c.available_models"
                  :key="m.id"
                  :value="m.id"
                  class="text-xs"
                >
                  {{ m.display_name || m.id }}
                </SelectItem>
              </SelectContent>
            </Select>
            <span v-else class="inline-flex items-center gap-1.5 font-mono text-xs text-muted-foreground">
              <span class="icon-[lucide--box] h-3 w-3 opacity-70" aria-hidden="true" />
              {{ c.default_model || '未配置' }}
            </span>
          </td>

          <!-- 健康 -->
          <td class="px-4 py-3.5">
            <ProviderHealthBadge
              :status="c.last_health_check_status"
              :last-error="c.last_health_check_error"
              :last-checked-at="c.last_health_check_at"
              @test="emit('testConnection', c)"
            />
          </td>

          <!-- 启用 -->
          <td class="px-4 py-3.5 text-center">
            <Switch
              :model-value="c.is_active"
              :aria-label="`启用 ${c.name}`"
              @update:model-value="emit('toggleActive', c)"
            />
          </td>

          <!-- 操作 -->
          <td class="px-4 py-3.5 text-right">
            <DropdownMenu>
              <DropdownMenuTrigger as-child>
                <Button
                  variant="ghost"
                  size="icon"
                  class="h-8 w-8 text-muted-foreground opacity-60 transition-opacity group-hover:opacity-100"
                  :aria-label="`${c.name} 操作菜单`"
                >
                  <span class="icon-[lucide--more-horizontal] h-4 w-4" aria-hidden="true" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" class="w-44">
                <DropdownMenuItem @click="emit('edit', c)">
                  <span class="icon-[lucide--pencil] mr-2 h-3.5 w-3.5" aria-hidden="true" />
                  编辑
                </DropdownMenuItem>
                <DropdownMenuItem
                  v-if="!c.is_default"
                  @click="emit('setDefault', c)"
                >
                  <span class="icon-[lucide--star] mr-2 h-3.5 w-3.5" aria-hidden="true" />
                  设为默认
                </DropdownMenuItem>
                <DropdownMenuItem @click="emit('refreshModels', c)">
                  <span class="icon-[lucide--refresh-cw] mr-2 h-3.5 w-3.5" aria-hidden="true" />
                  刷新模型清单
                </DropdownMenuItem>
                <DropdownMenuItem
                  class="text-destructive focus:text-destructive"
                  @click="emit('delete', c)"
                >
                  <span class="icon-[lucide--trash-2] mr-2 h-3.5 w-3.5" aria-hidden="true" />
                  删除凭证
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </td>
        </tr>
        <tr v-if="credentials.length === 0">
          <td
            colspan="7"
            class="px-4 py-12 text-center text-sm text-muted-foreground"
          >
            暂无凭证，点击「新建凭证」开始
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
