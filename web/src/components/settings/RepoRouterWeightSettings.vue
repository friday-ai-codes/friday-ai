<script setup lang="ts">
/**
 * 仓库路由权重设置区（Phase 106，ROUTE-06 运维操作面）。
 *
 * - 读写走专用端点 /settings/repo-router/weight-config/（服务端强校验），
 *   绝不走通用 per-key 设置 API——后者无业务校验。
 * - 权重取值限离散网格（防过拟合）：用下拉而非自由输入，网格外取值在
 *   前端即被 UI 约束拦截；INV-R2 文本主导与校准区间在前端预校验即时提示，
 *   后端校验为准（400 的 errors 逐条渲染）。
 * - 保存成功后重新 GET 回读，以后端规范化结果为准；保存后下一次路由
 *   立即生效，无需发版。
 */
import type { RepoRouterWeightConfig } from '~/api/settings'
import { computed, onMounted, ref } from 'vue'
import { ApiError } from '~/api/client'
import {
  getRepoRouterWeightConfig,
  putRepoRouterWeightConfig,
} from '~/api/settings'
import { Button } from '~/components/ui/button'
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

const { handleError } = useErrorHandler()
const { success, error: showError } = useToast()

// 权重离散网格——与后端 repo_router_config.WEIGHT_GRID 字面一致（10 个值）。
const WEIGHT_GRID_OPTIONS = [0, 0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.30, 0.40, 0.55]

interface WeightField {
  key: string
  label: string
}

// 五信号加性权重（关键程度 C_crit 为同分带 tie-break 旁路，不在此表）。
const WEIGHT_FIELDS: WeightField[] = [
  { key: 'text', label: '文本证据' },
  { key: 'domain', label: '业务域' },
  { key: 'activity', label: '活跃度' },
  { key: 'stack', label: '技术栈' },
  { key: 'team', label: '团队归属' },
]

interface ConstantField {
  key: string
  label: string
  hint?: string
}

// 关键常数（其余常数如 p/activity_floor 等随 GET 回读原样保留、不在 UI 编辑）。
const CONSTANT_FIELDS: ConstantField[] = [
  { key: 'lam', label: 'λ（breadth 占比）', hint: '文本证据中命中广度的占比 [0,1]' },
  { key: 'b', label: 'b（尺寸归一强度）', hint: '0=不归一，1=完全按密度' },
  { key: 'n_cap', label: 'n_cap（广度饱和点）', hint: '命中数对数饱和点，≥1' },
  { key: 'half_life_days', label: '活跃度半衰期（天）', hint: '指数衰减半衰期，>0' },
  { key: 'offset_days', label: '活跃度宽限期（天）', hint: '衰减起算前的宽限天数，≥0' },
  { key: 'crit_band', label: '关键程度同分带宽', hint: '|ΔS| 小于该值视为同分带 (0,0.1]' },
  { key: 's_top_c_lo', label: 'S_top 校准下界 c_lo', hint: '与上界构成 affine clip 区间' },
  { key: 's_top_c_hi', label: 'S_top 校准上界 c_hi', hint: '必须大于下界' },
  { key: 't2_c_lo', label: 'T2 校准下界 c_lo', hint: '元数据 T2 通道校准区间下界' },
  { key: 't2_c_hi', label: 'T2 校准上界 c_hi', hint: '必须大于下界' },
]

const loading = ref(true)
const saving = ref(false)

// 最近一次 GET 回读的完整配置：UI 未编辑的字段（p/activity_floor/锚点表等）
// 保存时原样带回，避免被重置为默认。
const config = ref<RepoRouterWeightConfig | null>(null)
const isDefault = ref(false)

// 表单态（字符串承载，保存时统一解析为数值）
const versionForm = ref('')
const weightForm = ref<Record<string, string>>({})
const constantForm = ref<Record<string, string>>({})
const facetsForm = ref('')

// 后端 400 返回的逐条校验错误
const serverErrors = ref<string[]>([])

const dirty = ref(false)
function markDirty() {
  dirty.value = true
}

async function loadConfig() {
  loading.value = true
  try {
    const data = await getRepoRouterWeightConfig()
    config.value = data
    isDefault.value = data.is_default === true
    versionForm.value = data.weight_set_version
    weightForm.value = Object.fromEntries(
      WEIGHT_FIELDS.map(f => [f.key, String(data.weights[f.key] ?? 0)]),
    )
    constantForm.value = Object.fromEntries(
      CONSTANT_FIELDS.map(f => [f.key, String(data.constants[f.key] ?? '')]),
    )
    facetsForm.value = (data.t2_disabled_facets ?? []).join(', ')
    dirty.value = false
    serverErrors.value = []
  }
  catch (e: unknown) {
    handleError(e, '加载仓库路由权重配置')
  }
  finally {
    loading.value = false
  }
}

function parsedWeights(): Record<string, number> {
  return Object.fromEntries(
    WEIGHT_FIELDS.map(f => [f.key, Number(weightForm.value[f.key])]),
  )
}

function parsedConstant(key: string): number {
  return Number(constantForm.value[key])
}

/**
 * 前端预校验（保存按钮前置拦截 + 内联提示）。仅为 UX 提前反馈，
 * 后端 validate_weight_config 是强制面（绕过前端无影响）。
 */
const validationErrors = computed<string[]>(() => {
  const errs: string[] = []
  const w = parsedWeights()

  // INV-R2 相对形式：元数据三权重之和 ≤ 0.5 × 五权重总和
  const total = WEIGHT_FIELDS.reduce((acc, f) => acc + (w[f.key] || 0), 0)
  const metaSum = (w.domain || 0) + (w.stack || 0) + (w.team || 0)
  if (metaSum > 0.5 * total + 1e-9) {
    errs.push(
      '文本证据必须占主导（INV-R2）：业务域 + 技术栈 + 团队归属 的权重之和不得超过全部权重和的一半',
    )
  }

  for (const f of CONSTANT_FIELDS) {
    const raw = (constantForm.value[f.key] ?? '').trim()
    if (raw === '' || !Number.isFinite(Number(raw)))
      errs.push(`「${f.label}」必须是有效数值`)
  }

  // 校准区间非空：c_lo < c_hi（s_top 与 t2 两组）
  if (
    Number.isFinite(parsedConstant('s_top_c_lo'))
    && Number.isFinite(parsedConstant('s_top_c_hi'))
    && parsedConstant('s_top_c_lo') >= parsedConstant('s_top_c_hi')
  ) {
    errs.push('S_top 校准区间非法：c_lo 必须小于 c_hi')
  }
  if (
    Number.isFinite(parsedConstant('t2_c_lo'))
    && Number.isFinite(parsedConstant('t2_c_hi'))
    && parsedConstant('t2_c_lo') >= parsedConstant('t2_c_hi')
  ) {
    errs.push('T2 校准区间非法：c_lo 必须小于 c_hi')
  }

  if (!versionForm.value.trim())
    errs.push('weight_set_version 必须为非空字符串')

  return errs
})

/** 改了权重却没改版本号时提示同步更新（不同版本的路由结果不可比）。 */
const versionUpdateHint = computed<boolean>(() => {
  if (!config.value)
    return false
  const w = parsedWeights()
  const weightsChanged = WEIGHT_FIELDS.some(
    f => Math.abs((config.value!.weights[f.key] ?? 0) - (w[f.key] || 0)) > 1e-9,
  )
  return weightsChanged && versionForm.value.trim() === config.value.weight_set_version
})

function onWeightChange(key: string, value: unknown) {
  weightForm.value = { ...weightForm.value, [key]: String(value) }
  markDirty()
}

function buildPayload(): Omit<RepoRouterWeightConfig, 'is_default'> {
  const base = config.value!
  // PUT payload 不得携带 is_default（后端拒绝未知顶层键）
  const { is_default: _ignored, ...rest } = base
  return {
    ...rest,
    weight_set_version: versionForm.value.trim(),
    weights: parsedWeights(),
    constants: {
      ...base.constants,
      ...Object.fromEntries(
        CONSTANT_FIELDS.map(f => [f.key, parsedConstant(f.key)]),
      ),
    },
    t2_disabled_facets: facetsForm.value
      .split(/[,，]/)
      .map(s => s.trim())
      .filter(Boolean),
  }
}

async function save() {
  if (!config.value || validationErrors.value.length > 0)
    return
  saving.value = true
  serverErrors.value = []
  try {
    await putRepoRouterWeightConfig(buildPayload())
    success('仓库路由权重已保存，下一次路由立即生效，无需发版')
    // 回读后端规范化结果为准
    await loadConfig()
  }
  catch (e: unknown) {
    if (e instanceof ApiError && e.status === 400 && e.body && typeof e.body === 'object') {
      const errors = (e.body as { errors?: unknown }).errors
      if (Array.isArray(errors) && errors.length > 0) {
        serverErrors.value = errors.map(String)
        showError('权重配置校验失败，请按提示修正后重试')
        return
      }
    }
    handleError(e, '保存仓库路由权重配置')
  }
  finally {
    saving.value = false
  }
}

onMounted(() => {
  loadConfig()
})
</script>

<template>
  <section class="group relative">
    <div class="card overflow-hidden">
      <!-- 卡片头部 -->
      <div class="flex items-center gap-3 p-6 border-b border-border/50">
        <div class="p-2.5 rounded-xl bg-primary/10 flex items-center justify-center">
          <span class="icon-[lucide--sliders-horizontal] text-2xl text-amber-500" />
        </div>
        <div class="flex-1 min-w-0">
          <h2 class="text-lg font-semibold">
            仓库路由权重
          </h2>
          <p class="text-sm text-muted-foreground">
            多信号打分函数的权重与常数。保存后下一次路由立即生效，无需发版。
          </p>
        </div>
        <span
          v-if="!loading && isDefault"
          class="shrink-0 rounded-full border border-border/60 bg-muted/50 px-2.5 py-1 text-xs text-muted-foreground"
        >
          当前为内置默认值
        </span>
      </div>

      <div v-if="loading" class="flex items-center justify-center gap-3 p-12">
        <span class="icon-[lucide--loader-circle] text-2xl text-primary animate-spin" />
        <span class="text-muted-foreground">加载设置...</span>
      </div>

      <div v-else-if="!config" class="p-6 text-sm text-muted-foreground">
        配置加载失败，请刷新页面重试。
      </div>

      <div v-else class="p-6 space-y-8">
        <!-- 版本号 -->
        <div class="space-y-2">
          <Label for="repo-router-weight-version">权重集版本号 (weight_set_version)</Label>
          <Input
            id="repo-router-weight-version"
            v-model="versionForm"
            placeholder="phase106-v1"
            class="h-10 max-w-sm bg-muted/30 border-border/50 focus:border-primary/50"
            @input="markDirty"
          />
          <p
            class="text-xs"
            :class="versionUpdateHint ? 'text-amber-600' : 'text-muted-foreground'"
          >
            <template v-if="versionUpdateHint">
              已修改权重，请同步更新版本号——不同版本的路由结果不可比
            </template>
            <template v-else>
              修改权重或常数时建议同步更新版本号，便于路由结果按版本对齐比较
            </template>
          </p>
        </div>

        <!-- 五信号权重（离散网格下拉） -->
        <div class="space-y-4">
          <div class="flex items-center gap-2 text-sm font-medium text-muted-foreground">
            <span class="icon-[lucide--scale]" />
            <span>信号权重（取值限离散网格，防过拟合）</span>
          </div>
          <div class="rounded-xl bg-muted/30 border border-border/30 p-4">
            <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <div v-for="f in WEIGHT_FIELDS" :key="f.key" class="space-y-2">
                <Label :for="`repo-router-weight-${f.key}`">{{ f.label }} ({{ f.key }})</Label>
                <Select
                  :model-value="weightForm[f.key]"
                  @update:model-value="(v: unknown) => onWeightChange(f.key, v)"
                >
                  <SelectTrigger :id="`repo-router-weight-${f.key}`" class="h-10 w-full bg-muted/30 border-border/50">
                    <SelectValue placeholder="选择权重" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem
                      v-for="opt in WEIGHT_GRID_OPTIONS"
                      :key="String(opt)"
                      :value="String(opt)"
                    >
                      {{ opt.toFixed(2) }}
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <p class="mt-3 text-xs text-muted-foreground">
              相对权重经缺失重归一化生效，绝对和无须为 1；元数据（业务域/技术栈/团队归属）
              权重之和不得超过全部权重和的一半（文本主导不变量 INV-R2）。
            </p>
          </div>
        </div>

        <!-- 关键常数 -->
        <div class="space-y-4">
          <div class="flex items-center gap-2 text-sm font-medium text-muted-foreground">
            <span class="icon-[lucide--sigma]" />
            <span>关键常数</span>
          </div>
          <div class="rounded-xl bg-muted/30 border border-border/30 p-4">
            <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <div v-for="f in CONSTANT_FIELDS" :key="f.key" class="space-y-2">
                <Label :for="`repo-router-const-${f.key}`">{{ f.label }}</Label>
                <Input
                  :id="`repo-router-const-${f.key}`"
                  v-model="constantForm[f.key]"
                  type="number"
                  step="any"
                  class="h-10 bg-muted/30 border-border/50 focus:border-primary/50"
                  @input="markDirty"
                />
                <p v-if="f.hint" class="text-xs text-muted-foreground">
                  {{ f.hint }}
                </p>
              </div>
            </div>
          </div>
        </div>

        <!-- T2 停用 facet 列表 -->
        <div class="space-y-2">
          <Label for="repo-router-t2-disabled">T2 停用 facet（逗号分隔）</Label>
          <Input
            id="repo-router-t2-disabled"
            v-model="facetsForm"
            placeholder="如：业务域, 团队"
            class="h-10 bg-muted/30 border-border/50 focus:border-primary/50"
            @input="markDirty"
          />
          <p class="text-xs text-muted-foreground">
            O-2 校准判定区分度不足（c_hi − c_lo &lt; 0.10）的 facet 在此停用 T2 embedding 通道，只保留 T1 词典匹配
          </p>
        </div>

        <!-- 前端预校验提示 -->
        <div
          v-if="dirty && validationErrors.length > 0"
          class="rounded-xl border border-amber-500/40 bg-amber-500/10 p-4 space-y-1"
        >
          <div class="flex items-center gap-2 text-sm font-medium text-amber-600">
            <span class="icon-[lucide--triangle-alert]" />
            <span>保存前请修正以下问题</span>
          </div>
          <ul class="list-disc pl-6 text-xs text-amber-700 space-y-0.5">
            <li v-for="(err, i) in validationErrors" :key="i">
              {{ err }}
            </li>
          </ul>
        </div>

        <!-- 后端校验错误（逐条渲染，以后端为准） -->
        <div
          v-if="serverErrors.length > 0"
          class="rounded-xl border border-destructive/40 bg-destructive/10 p-4 space-y-1"
        >
          <div class="flex items-center gap-2 text-sm font-medium text-destructive">
            <span class="icon-[lucide--circle-x]" />
            <span>后端校验未通过</span>
          </div>
          <ul class="list-disc pl-6 text-xs text-destructive space-y-0.5">
            <li v-for="(err, i) in serverErrors" :key="i">
              {{ err }}
            </li>
          </ul>
        </div>
      </div>

      <div class="flex justify-end px-6 py-4 border-t border-border/50">
        <Button
          :disabled="loading || saving || !dirty || validationErrors.length > 0"
          @click="save"
        >
          <span v-if="saving" class="icon-[lucide--loader-circle] animate-spin mr-2" />
          <span v-else class="icon-[lucide--save] mr-2" />
          保存设置
        </Button>
      </div>
    </div>
  </section>
</template>
