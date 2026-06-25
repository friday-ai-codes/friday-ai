<script setup lang="ts">
/**
 * 运行时日志配置表单（UI-04 §5.4）。
 *
 * 复用既有 settings.ts 的 getSetting / updateSetting（**不新封装端点**）读写
 * SettingKeys.LOG_*（点分 key，见 server/system/models.py）。后端 SystemSetting
 * post_save signal 即时热更新（无需重启，per LOG-06），故保存成功后提示「已实时生效」。
 *
 * 注：settings.ts 的 `SettingKey` 为受限字符串枚举，不含 log.* 键；按 plan 约定以其
 * string 形态传入（`as unknown as SettingKey`），运行时即点分 key 字符串，与后端一致。
 *
 * 默认值对齐 models.py SettingKeys 注释：level 空→env→INFO、stack_threshold ERROR、
 * sampling_initial 50、sampling_rate 0.1、retention_days 30、retention_max_rows 1_000_000。
 * UI-SPEC §0：lucide 无 emoji、tabular-nums、亮暗 token、异步禁用 + spinner、toast 反馈。
 */
import type { SettingKey } from '~/api/settings'
import { onMounted, reactive, ref } from 'vue'
import { getSetting, updateSetting } from '~/api/settings'
import { Button } from '~/components/ui/button'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '~/components/ui/collapsible'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

const { success, info } = useToast()
const { handleError } = useErrorHandler()

// 点分 key（后端 SettingKeys.LOG_*）；以 string 形态传入 settings.ts API。
const LOG_KEYS = {
  level: 'log.level',
  componentLevels: 'log.component_levels',
  stackThreshold: 'log.stack_threshold',
  samplingInitial: 'log.sampling_initial',
  samplingRate: 'log.sampling_rate',
  retentionDays: 'log.retention_days',
  retentionSize: 'log.retention_max_rows',
} as const

/** 受限枚举不含 log.*，按 plan 约定转 SettingKey 形态传入（运行时即点分串）。 */
function asKey(k: string): SettingKey {
  return k as unknown as SettingKey
}

// 内置默认（对齐 models.py 注释）。
const DEFAULTS = {
  level: '', // 空 → 后端回退 env → INFO
  componentLevels: {} as Record<string, string>,
  stackThreshold: 'ERROR',
  samplingInitial: 50,
  samplingRate: 0.1,
  retentionDays: 30,
  retentionSize: 1_000_000,
}

const LEVEL_OPTIONS = [
  { value: 'DEBUG', label: 'DEBUG' },
  { value: 'INFO', label: 'INFO' },
  { value: 'WARNING', label: 'WARNING' },
  { value: 'ERROR', label: 'ERROR' },
]
// 全局级别允许「跟随默认（空）」哨兵（reka-ui SelectItem 不接受空串值）。
const LEVEL_INHERIT = '__inherit__'
const GLOBAL_LEVEL_OPTIONS = [{ value: LEVEL_INHERIT, label: '跟随默认（env→INFO）' }, ...LEVEL_OPTIONS]

interface ComponentLevelRow { key: string, value: string }

const form = reactive({
  level: LEVEL_INHERIT,
  componentLevels: [] as ComponentLevelRow[],
  stackThreshold: 'ERROR',
  samplingInitial: 50,
  samplingRate: 0.1,
  retentionDays: 30,
  retentionSize: 1_000_000,
})

const loading = ref(true)
const saving = ref(false)

/** 把 settings 读取值（string|null）安全转换后回填表单。 */
function readNumber(value: string | null | undefined, fallback: number): number {
  if (value == null || value === '')
    return fallback
  const n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

function parseComponentLevels(value: string | null | undefined): ComponentLevelRow[] {
  if (!value)
    return []
  try {
    const obj = JSON.parse(value)
    if (obj && typeof obj === 'object')
      return Object.entries(obj).map(([key, v]) => ({ key, value: String(v) }))
  }
  catch {
    // 非法 JSON → 视为空（容错，不报错）。
  }
  return []
}

async function loadOne(key: string): Promise<string | null> {
  try {
    const res = await getSetting(asKey(key))
    return res.value
  }
  catch {
    // 键未设置 / 读取失败 → 回退默认（best-effort，绝不报错）。
    return null
  }
}

async function loadAll() {
  loading.value = true
  try {
    const [level, comp, stack, sInit, sRate, rDays, rSize] = await Promise.all([
      loadOne(LOG_KEYS.level),
      loadOne(LOG_KEYS.componentLevels),
      loadOne(LOG_KEYS.stackThreshold),
      loadOne(LOG_KEYS.samplingInitial),
      loadOne(LOG_KEYS.samplingRate),
      loadOne(LOG_KEYS.retentionDays),
      loadOne(LOG_KEYS.retentionSize),
    ])
    form.level = level && level.trim() ? level.trim().toUpperCase() : LEVEL_INHERIT
    form.componentLevels = parseComponentLevels(comp)
    form.stackThreshold = (stack && stack.trim() ? stack.trim().toUpperCase() : DEFAULTS.stackThreshold)
    form.samplingInitial = readNumber(sInit, DEFAULTS.samplingInitial)
    form.samplingRate = readNumber(sRate, DEFAULTS.samplingRate)
    form.retentionDays = readNumber(rDays, DEFAULTS.retentionDays)
    form.retentionSize = readNumber(rSize, DEFAULTS.retentionSize)
  }
  finally {
    loading.value = false
  }
}

onMounted(loadAll)

function addComponentRow() {
  form.componentLevels.push({ key: '', value: 'INFO' })
}
function removeComponentRow(idx: number) {
  form.componentLevels.splice(idx, 1)
}

/** 组件级别行 → JSON map（忽略空 key）。 */
function componentLevelsJson(): string {
  const map: Record<string, string> = {}
  for (const row of form.componentLevels) {
    const k = row.key.trim()
    if (k)
      map[k] = row.value.trim().toUpperCase()
  }
  return JSON.stringify(map)
}

async function onSave() {
  saving.value = true
  try {
    // 逐键写入（map→JSON，数字→String）；level 哨兵→空串（后端回退默认）。
    await Promise.all([
      updateSetting(asKey(LOG_KEYS.level), form.level === LEVEL_INHERIT ? '' : form.level),
      updateSetting(asKey(LOG_KEYS.componentLevels), componentLevelsJson()),
      updateSetting(asKey(LOG_KEYS.stackThreshold), form.stackThreshold),
      updateSetting(asKey(LOG_KEYS.samplingInitial), String(form.samplingInitial)),
      updateSetting(asKey(LOG_KEYS.samplingRate), String(form.samplingRate)),
      updateSetting(asKey(LOG_KEYS.retentionDays), String(form.retentionDays)),
      updateSetting(asKey(LOG_KEYS.retentionSize), String(form.retentionSize)),
    ])
    success('日志配置已保存', '后端 signal 已实时生效，无需重启')
  }
  catch (e) {
    handleError(e, '保存日志配置')
  }
  finally {
    saving.value = false
  }
}

/** 回滚默认：仅把表单重置为内置默认（需点「保存并生效」才落库）。 */
function onResetDefaults() {
  form.level = LEVEL_INHERIT
  form.componentLevels = []
  form.stackThreshold = DEFAULTS.stackThreshold
  form.samplingInitial = DEFAULTS.samplingInitial
  form.samplingRate = DEFAULTS.samplingRate
  form.retentionDays = DEFAULTS.retentionDays
  form.retentionSize = DEFAULTS.retentionSize
  info('已重置为默认值', '点击「保存并生效」后才会落库')
}

const open = ref(false)
</script>

<template>
  <Collapsible v-model:open="open" class="rounded-xl border border-border/60 bg-card">
    <CollapsibleTrigger
      class="flex w-full items-center justify-between gap-3 p-4 text-left transition-colors hover:bg-muted/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
      aria-label="展开运行时日志配置"
    >
      <div class="flex items-center gap-2">
        <span class="icon-[lucide--sliders-horizontal] text-lg text-primary" />
        <div>
          <h2 class="text-sm font-semibold">
            运行时日志配置
          </h2>
          <p class="text-xs text-muted-foreground">
            级别 / 分组件 / 堆栈阈值 / 采样 / 保留——保存即实时生效，无需重启
          </p>
        </div>
      </div>
      <span
        class="text-base text-muted-foreground transition-transform"
        :class="open ? 'icon-[lucide--chevron-up]' : 'icon-[lucide--chevron-down]'"
      />
    </CollapsibleTrigger>

    <CollapsibleContent>
      <div class="space-y-5 border-t border-border/50 p-4">
        <!-- 级别组 -->
        <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div class="space-y-1.5">
            <Label class="text-xs">全局级别</Label>
            <Select v-model="form.level" :disabled="loading">
              <SelectTrigger class="h-9">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-for="opt in GLOBAL_LEVEL_OPTIONS" :key="opt.value" :value="opt.value">
                  {{ opt.label }}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div class="space-y-1.5">
            <Label class="text-xs">堆栈阈值（记录堆栈的最低级别）</Label>
            <Select v-model="form.stackThreshold" :disabled="loading">
              <SelectTrigger class="h-9">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-for="opt in LEVEL_OPTIONS" :key="opt.value" :value="opt.value">
                  {{ opt.label }}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        <!-- 分组件级别（JSON map 行编辑） -->
        <div class="space-y-2">
          <div class="flex items-center justify-between">
            <Label class="text-xs">分组件级别（覆盖全局，如 rag=DEBUG）</Label>
            <Button variant="outline" size="sm" :disabled="loading" @click="addComponentRow">
              <span class="icon-[lucide--plus]" />
              添加
            </Button>
          </div>
          <div v-if="form.componentLevels.length" class="space-y-2">
            <div
              v-for="(row, idx) in form.componentLevels"
              :key="idx"
              class="flex items-center gap-2"
            >
              <Input
                v-model="row.key"
                placeholder="组件名（如 rag）"
                class="h-9 flex-1"
                aria-label="组件名"
              />
              <Select v-model="row.value">
                <SelectTrigger class="h-9 w-[120px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem v-for="opt in LEVEL_OPTIONS" :key="opt.value" :value="opt.value">
                    {{ opt.label }}
                  </SelectItem>
                </SelectContent>
              </Select>
              <Button variant="ghost" size="icon-sm" aria-label="移除该组件级别" @click="removeComponentRow(idx)">
                <span class="icon-[lucide--x] text-destructive" />
              </Button>
            </div>
          </div>
          <p v-else class="text-xs text-muted-foreground">
            未配置分组件级别，全部跟随全局级别
          </p>
        </div>

        <!-- 采样组 -->
        <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div class="space-y-1.5">
            <Label class="text-xs">采样初始（首 N 条全记）</Label>
            <Input v-model.number="form.samplingInitial" type="number" min="0" class="h-9 tabular-nums" :disabled="loading" />
          </div>
          <div class="space-y-1.5">
            <Label class="text-xs">采样后续比例（0..1）</Label>
            <Input v-model.number="form.samplingRate" type="number" step="0.01" min="0" max="1" class="h-9 tabular-nums" :disabled="loading" />
          </div>
        </div>

        <!-- 保留组 -->
        <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div class="space-y-1.5">
            <Label class="text-xs">保留天数</Label>
            <Input v-model.number="form.retentionDays" type="number" min="1" class="h-9 tabular-nums" :disabled="loading" />
          </div>
          <div class="space-y-1.5">
            <Label class="text-xs">保留行数上限</Label>
            <Input v-model.number="form.retentionSize" type="number" min="1" class="h-9 tabular-nums" :disabled="loading" />
          </div>
        </div>

        <!-- caller / sampling 说明 -->
        <p class="rounded-lg bg-muted/40 p-3 text-[11px] text-muted-foreground">
          <span class="icon-[lucide--info] mr-1 align-middle" />
          采样仅作用于 <span class="font-mono">sampling</span> 类（高频内部步骤）；<span class="font-mono">caller</span>
          类（用户可归因调用）始终全量记录，不受采样比例影响。
        </p>

        <!-- 操作 -->
        <div class="flex items-center justify-end gap-2 border-t border-border/50 pt-4">
          <Button variant="outline" :disabled="saving || loading" @click="onResetDefaults">
            <span class="icon-[lucide--rotate-ccw]" />
            回滚默认
          </Button>
          <Button :disabled="saving || loading" @click="onSave">
            <span v-if="saving" class="icon-[lucide--loader-2] mr-1.5 animate-spin" />
            保存并生效
          </Button>
        </div>
      </div>
    </CollapsibleContent>
  </Collapsible>
</template>
