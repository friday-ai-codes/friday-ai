<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getAllSettings, SettingKey, updateSetting } from '~/api/settings'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

const { handleError } = useErrorHandler()
const { success } = useToast()

interface FieldConfig {
  key: SettingKey
  label: string
  description: string
  placeholder: string
  type: 'text' | 'password'
}

const fields: FieldConfig[] = [
  {
    key: SettingKey.REDIS_URL,
    label: 'Redis URL',
    description: 'Redis 连接地址，用于 Channel Layer、缓存和任务队列',
    placeholder: 'redis://127.0.0.1:6379/0',
    type: 'text',
  },
  {
    key: SettingKey.SUBAGENT_API_URL,
    label: 'SubAgent API URL',
    description: 'SubAgent 容器内部通信地址',
    placeholder: 'http://localhost:10241',
    type: 'text',
  },
  {
    key: SettingKey.FRIDAY_BASE_URL,
    label: 'Friday Base URL',
    description: '服务端外部访问地址，用于回调和 webhook',
    placeholder: 'http://localhost:10241',
    type: 'text',
  },
  {
    key: SettingKey.FRIDAY_FRONTEND_URL,
    label: 'Friday Frontend URL',
    description: '前端访问地址，用于 OIDC 重定向',
    placeholder: 'http://localhost:10240',
    type: 'text',
  },
  {
    key: SettingKey.CONTAINER_CALLBACK_TOKEN,
    label: 'Container Callback Token',
    description: 'Runner 容器回调认证令牌',
    placeholder: '自动生成',
    type: 'password',
  },
]

const values = ref<Record<string, string>>({})
const dirty = ref<Record<string, boolean>>({})
const loading = ref(true)
const saving = ref<Record<string, boolean>>({})
const showPassword = ref<Record<string, boolean>>({})

async function load() {
  loading.value = true
  try {
    const settings = await getAllSettings()
    for (const field of fields) {
      const found = settings.find(s => s.key === field.key)
      values.value[field.key] = found?.value ?? ''
      dirty.value[field.key] = false
      saving.value[field.key] = false
    }
  }
  catch (e) {
    handleError(e, '加载基础设施配置')
  }
  finally {
    loading.value = false
  }
}

async function save(key: SettingKey) {
  saving.value[key] = true
  try {
    await updateSetting(key, values.value[key].trim())
    success(`${fields.find(f => f.key === key)?.label ?? key} 已保存`)
    dirty.value[key] = false
  }
  catch (e) {
    handleError(e, '保存配置')
  }
  finally {
    saving.value[key] = false
  }
}

function onInput(key: SettingKey) {
  dirty.value[key] = true
}

onMounted(load)
</script>

<template>
  <div class="card overflow-hidden">
    <div class="flex items-center gap-3 p-6 border-b border-border/50">
      <div class="p-2.5 rounded-xl bg-primary/10 flex items-center justify-center">
        <span class="icon-[lucide--server] text-2xl text-primary" />
      </div>
      <div class="flex-1">
        <h2 class="text-lg font-semibold">
          基础设施配置
        </h2>
        <p class="text-sm text-muted-foreground">
          后端服务连接地址和认证令牌（仅管理员可修改）
        </p>
      </div>
    </div>

    <div class="p-6 space-y-6">
      <div v-if="loading" class="flex items-center gap-2 text-muted-foreground">
        <span class="icon-[lucide--loader-circle] animate-spin" />
        加载中...
      </div>

      <div v-else class="space-y-5">
        <div
          v-for="field in fields"
          :key="field.key"
          class="space-y-2"
        >
          <div class="flex items-center justify-between">
            <Label :for="field.key" class="text-sm font-medium">
              {{ field.label }}
            </Label>
            <span
              v-if="dirty[field.key]"
              class="text-xs text-amber-500"
            >
              未保存
            </span>
          </div>
          <p class="text-xs text-muted-foreground">
            {{ field.description }}
          </p>
          <div class="relative">
            <span
              class="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
              :class="field.type === 'password' ? 'icon-[lucide--lock]' : 'icon-[lucide--link]'"
            />
            <Input
              :id="field.key"
              v-model="values[field.key]"
              :type="field.type === 'password' && !showPassword[field.key] ? 'password' : 'text'"
              :placeholder="field.placeholder"
              class="pl-10 pr-10 h-10 font-mono text-sm bg-muted/30 border-border/50 focus:border-primary/50"
              @input="onInput(field.key)"
            />
            <button
              v-if="field.type === 'password'"
              type="button"
              class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
              @click="showPassword[field.key] = !showPassword[field.key]"
            >
              <span :class="showPassword[field.key] ? 'icon-[lucide--eye-off]' : 'icon-[lucide--eye]'" />
            </button>
          </div>
          <div class="flex justify-end">
            <Button
              size="sm"
              :disabled="!dirty[field.key] || saving[field.key]"
              @click="save(field.key)"
            >
              <span v-if="saving[field.key]" class="icon-[lucide--loader-circle] animate-spin mr-1" />
              <span v-else class="icon-[lucide--save] mr-1" />
              保存
            </Button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
