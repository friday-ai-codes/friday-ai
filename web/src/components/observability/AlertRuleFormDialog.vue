<script setup lang="ts">
/**
 * 告警阈值规则新建 / 编辑表单（UI-03 §4.2）。
 *
 * 受控枚举字段与后端 alert_serializers 白名单严格对齐（metric/op/severity ChoiceField、
 * channels ⊆ {email,feishu,webhook}、dimension 键 ⊆ 受控集合），禁自由字符串污染评估。
 * 提交前 zod 前校验；后端 400（中文 detail）经 ApiError 捕获 → toast + 不崩。
 * rule 传入=编辑（PATCH），空=新建（POST）。成功 emit saved + 关闭。
 */
import type { AlertChannel, AlertMetric, AlertOp, AlertRule, AlertRuleWrite, AlertSeverity } from '~/api/system'
import { computed, reactive, ref, watch } from 'vue'
import { z } from 'zod'
import { createAlertRule, updateAlertRule } from '~/api/system'
import { Button } from '~/components/ui/button'
import { Checkbox } from '~/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '~/components/ui/dialog'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'
import { Switch } from '~/components/ui/switch'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

const props = defineProps<{
  open: boolean
  rule?: AlertRule | null
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  'saved': []
}>()

const { success } = useToast()
const { handleError } = useErrorHandler()

// ── 受控枚举选项（与后端白名单对齐） ──────────────────────────────────
const METRIC_OPTIONS: { value: AlertMetric, label: string }[] = [
  { value: 'qps', label: 'QPS（请求速率）' },
  { value: 'error_rate', label: '错误率' },
  { value: 'ttft', label: '首字延迟 TTFT' },
  { value: 'cpu', label: 'CPU 使用率' },
  { value: 'memory', label: '内存使用率' },
  { value: 'db_connections', label: '数据库连接数' },
  { value: 'redis_clients', label: 'Redis 连接数' },
  { value: 'qdrant', label: 'Qdrant 可用性' },
  { value: 'queue_depth', label: '队列深度' },
]
const OP_OPTIONS: { value: AlertOp, label: string }[] = [
  { value: 'gt', label: '> 大于' },
  { value: 'gte', label: '≥ 大于等于' },
  { value: 'lt', label: '< 小于' },
  { value: 'lte', label: '≤ 小于等于' },
]
const SEVERITY_OPTIONS: { value: AlertSeverity, label: string }[] = [
  { value: 'P0', label: 'P0 严重' },
  { value: 'P1', label: 'P1 警告' },
  { value: 'P2', label: 'P2 提示' },
]
const CHANNEL_OPTIONS: { value: AlertChannel, label: string }[] = [
  { value: 'email', label: '邮件' },
  { value: 'feishu', label: '飞书' },
  { value: 'webhook', label: 'Webhook' },
]
// 维度键 Select：reka-ui SelectItem 不允许空字符串值，故用 'overall' 哨兵代表「全局」。
const DIM_OVERALL = 'overall'
const DIMENSION_KEY_OPTIONS = [
  { value: DIM_OVERALL, label: '全局（overall）' },
  { value: 'provider', label: 'provider 供应商' },
  { value: 'credential', label: 'credential 凭证' },
  { value: 'model', label: 'model 模型' },
  { value: 'source', label: 'source 来源' },
  { value: 'queue', label: 'queue 队列' },
  { value: 'route', label: 'route 路由' },
]

interface FormState {
  name: string
  metric: AlertMetric
  op: AlertOp
  value: number | undefined
  window: number
  severity: AlertSeverity
  channels: AlertChannel[]
  cooldown: number
  dimensionKey: string
  dimensionValue: string
  title_template: string
  enabled: boolean
}

function emptyForm(): FormState {
  return {
    name: '',
    metric: 'cpu',
    op: 'gt',
    value: undefined,
    window: 300,
    severity: 'P1',
    channels: ['email'],
    cooldown: 600,
    dimensionKey: DIM_OVERALL,
    dimensionValue: '',
    title_template: '',
    enabled: true,
  }
}

const form = reactive<FormState>(emptyForm())
const errors = reactive<Record<string, string>>({})
const submitting = ref(false)

const isEdit = computed(() => props.rule != null)

// 打开 / rule 变化时初始化表单（编辑回填 / 新建重置）。
watch(
  () => [props.open, props.rule] as const,
  ([open]) => {
    if (!open)
      return
    clearErrors()
    if (props.rule) {
      const r = props.rule
      const dimEntries = Object.entries(r.dimension ?? {})
      Object.assign(form, {
        name: r.name,
        metric: r.metric,
        op: r.op,
        value: r.value,
        window: r.window,
        severity: r.severity,
        channels: [...r.channels],
        cooldown: r.cooldown,
        dimensionKey: dimEntries[0]?.[0] ?? DIM_OVERALL,
        dimensionValue: dimEntries[0]?.[1] ?? '',
        title_template: r.title_template ?? '',
        enabled: r.enabled,
      } satisfies FormState)
    }
    else {
      Object.assign(form, emptyForm())
    }
  },
  { immediate: true },
)

function clearErrors() {
  for (const k of Object.keys(errors))
    delete errors[k]
}

const schema = z.object({
  name: z.string().trim().min(1, '请填写规则名称'),
  metric: z.enum(['qps', 'error_rate', 'ttft', 'cpu', 'memory', 'db_connections', 'redis_clients', 'qdrant', 'queue_depth']),
  op: z.enum(['gt', 'gte', 'lt', 'lte']),
  value: z.number({ message: '请填写有效阈值' }).finite('请填写有效阈值'),
  window: z.number().int().min(1, '窗口需 ≥ 1 秒'),
  severity: z.enum(['P0', 'P1', 'P2']),
  channels: z.array(z.enum(['email', 'feishu', 'webhook'])),
  cooldown: z.number().int().min(0, '冷却需 ≥ 0 秒'),
})

function toggleChannel(ch: AlertChannel, checked: boolean | 'indeterminate') {
  const on = checked === true
  const has = form.channels.includes(ch)
  if (on && !has)
    form.channels.push(ch)
  else if (!on && has)
    form.channels = form.channels.filter(c => c !== ch)
}

async function onSubmit() {
  clearErrors()
  const parsed = schema.safeParse({
    name: form.name,
    metric: form.metric,
    op: form.op,
    value: form.value,
    window: form.window,
    severity: form.severity,
    channels: form.channels,
    cooldown: form.cooldown,
  })
  if (!parsed.success) {
    for (const issue of parsed.error.issues) {
      const key = String(issue.path[0] ?? '')
      if (key && !errors[key])
        errors[key] = issue.message
    }
    return
  }

  const dimension: Record<string, string> = {}
  if (form.dimensionKey !== DIM_OVERALL && form.dimensionValue.trim())
    dimension[form.dimensionKey] = form.dimensionValue.trim()

  const body: AlertRuleWrite = {
    name: parsed.data.name,
    metric: parsed.data.metric,
    op: parsed.data.op,
    value: parsed.data.value,
    window: parsed.data.window,
    severity: parsed.data.severity,
    enabled: form.enabled,
    channels: parsed.data.channels,
    cooldown: parsed.data.cooldown,
    dimension,
    title_template: form.title_template.trim(),
  }

  submitting.value = true
  try {
    if (isEdit.value && props.rule)
      await updateAlertRule(props.rule.id, body)
    else
      await createAlertRule(body)
    success(isEdit.value ? '规则已更新' : '规则已创建')
    emit('saved')
    emit('update:open', false)
  }
  catch (e) {
    handleError(e, isEdit.value ? '更新规则' : '创建规则')
  }
  finally {
    submitting.value = false
  }
}
</script>

<template>
  <Dialog :open="open" @update:open="(v: boolean) => emit('update:open', v)">
    <DialogContent class="max-h-[90vh] max-w-lg overflow-y-auto">
      <DialogHeader>
        <DialogTitle>{{ isEdit ? '编辑告警规则' : '新建告警规则' }}</DialogTitle>
        <DialogDescription>
          配置阈值条件与通知通道；字段均为受控枚举，提交后由后端二次校验
        </DialogDescription>
      </DialogHeader>

      <form class="space-y-4" @submit.prevent="onSubmit">
        <!-- 名称 -->
        <div class="space-y-1.5">
          <Label class="text-xs">规则名称</Label>
          <Input v-model="form.name" placeholder="如：CPU 高负载告警" />
          <p v-if="errors.name" class="text-xs text-destructive">
            {{ errors.name }}
          </p>
        </div>

        <!-- 指标 / 运算符 / 阈值 -->
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div class="space-y-1.5">
            <Label class="text-xs">监控指标</Label>
            <Select v-model="form.metric">
              <SelectTrigger class="h-9">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-for="opt in METRIC_OPTIONS" :key="opt.value" :value="opt.value">
                  {{ opt.label }}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div class="space-y-1.5">
            <Label class="text-xs">运算符</Label>
            <Select v-model="form.op">
              <SelectTrigger class="h-9">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-for="opt in OP_OPTIONS" :key="opt.value" :value="opt.value">
                  {{ opt.label }}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div class="space-y-1.5">
            <Label class="text-xs">阈值</Label>
            <Input v-model.number="form.value" type="number" step="any" placeholder="如 85" />
            <p v-if="errors.value" class="text-xs text-destructive">
              {{ errors.value }}
            </p>
          </div>
        </div>

        <!-- 窗口 / 冷却 / 级别 -->
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div class="space-y-1.5">
            <Label class="text-xs">窗口（秒）</Label>
            <Input v-model.number="form.window" type="number" min="1" />
            <p v-if="errors.window" class="text-xs text-destructive">
              {{ errors.window }}
            </p>
          </div>
          <div class="space-y-1.5">
            <Label class="text-xs">冷却（秒）</Label>
            <Input v-model.number="form.cooldown" type="number" min="0" />
            <p v-if="errors.cooldown" class="text-xs text-destructive">
              {{ errors.cooldown }}
            </p>
          </div>
          <div class="space-y-1.5">
            <Label class="text-xs">严重级别</Label>
            <Select v-model="form.severity">
              <SelectTrigger class="h-9">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-for="opt in SEVERITY_OPTIONS" :key="opt.value" :value="opt.value">
                  {{ opt.label }}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        <!-- 通知通道 -->
        <div class="space-y-1.5">
          <Label class="text-xs">通知通道</Label>
          <div class="flex flex-wrap gap-4">
            <label
              v-for="opt in CHANNEL_OPTIONS"
              :key="opt.value"
              class="flex cursor-pointer items-center gap-2 text-sm select-none"
            >
              <Checkbox
                :model-value="form.channels.includes(opt.value)"
                @update:model-value="(v) => toggleChannel(opt.value, v)"
              />
              {{ opt.label }}
            </label>
          </div>
        </div>

        <!-- 维度（受控键 + 值，留空=全局） -->
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div class="space-y-1.5">
            <Label class="text-xs">触发维度</Label>
            <Select v-model="form.dimensionKey">
              <SelectTrigger class="h-9">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-for="opt in DIMENSION_KEY_OPTIONS" :key="opt.value" :value="opt.value">
                  {{ opt.label }}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div class="space-y-1.5">
            <Label class="text-xs">维度值</Label>
            <Input
              v-model="form.dimensionValue"
              :disabled="form.dimensionKey === DIM_OVERALL"
              placeholder="如 anthropic"
            />
          </div>
        </div>

        <!-- 标题模板 -->
        <div class="space-y-1.5">
          <Label class="text-xs">标题模板（可空）</Label>
          <Input v-model="form.title_template" placeholder="支持占位符 {metric} / {current} / {value}" />
        </div>

        <!-- 启用开关 -->
        <label class="flex cursor-pointer items-center gap-2 text-sm select-none">
          <Switch v-model="form.enabled" aria-label="启用规则" />
          <span>{{ form.enabled ? '已启用' : '已禁用' }}</span>
        </label>

        <DialogFooter>
          <Button type="button" variant="ghost" :disabled="submitting" @click="emit('update:open', false)">
            取消
          </Button>
          <Button type="submit" :disabled="submitting">
            <span v-if="submitting" class="icon-[lucide--loader-2] mr-1.5 animate-spin" />
            {{ isEdit ? '保存' : '创建' }}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  </Dialog>
</template>
