<script setup lang="ts">
/**
 * 蓝图状态徽标（Phase 115，12 态 + 未知态兜底）。
 *
 * 形态照 `~/components/common/StatusBadge.vue`（三档 size 映射 + 裸图标名拼接 + animate-spin），
 * label 取法照 `~/components/spec/SddSpecStatusBadge.vue`（走 i18n 而非配置里的中文字面量）。
 *
 * ⛔ **颜色全部由 `<Badge variant>` 承载，禁止在 Badge 上用 `:class` 追加颜色类**（UI-SPEC §15）。
 * ⛔ 全程 mustache 插值，不走任何原始 HTML 注入指令（源码守卫扫描锁死整个扫描面）。
 */
import type { BlueprintStatusConfig } from '~/config/blueprintStatus'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Badge } from '~/components/ui/badge'
import { getBlueprintStatusConfig } from '~/config/blueprintStatus'

const props = withDefaults(defineProps<{
  /** 蓝图 `current_status`；`''`（v0 旧数据）是合法输入，命中「旧版方案」档。 */
  status: string
  size?: 'sm' | 'md' | 'lg'
  showIcon?: boolean
  showLabel?: boolean
}>(), {
  size: 'md',
  showIcon: true,
  showLabel: true,
})

const { t } = useI18n()

const config = computed<BlueprintStatusConfig>(() => getBlueprintStatusConfig(props.status))
const label = computed(() => t(config.value.labelKey))

const sizeClass = computed(() => ({
  sm: 'text-[10px] px-1.5 py-0.5',
  md: 'text-xs px-2 py-0.5',
  lg: 'text-sm px-2.5 py-1',
}[props.size]))

const iconSizeClass = computed(() => ({
  sm: 'text-[10px]',
  md: 'text-xs',
  lg: 'text-sm',
}[props.size]))
</script>

<template>
  <Badge
    :variant="config.variant"
    :class="sizeClass"
    :title="label"
    data-testid="blueprint-status-badge"
  >
    <span
      v-if="showIcon"
      :class="[`icon-[${config.icon}]`, iconSizeClass, config.animate ? 'animate-spin' : '']"
      aria-hidden="true"
    />
    <span v-if="showLabel">{{ label }}</span>
  </Badge>
</template>
