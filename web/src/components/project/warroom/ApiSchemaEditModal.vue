<script setup lang="ts">
import type { ApiField, StateApi, StateApiStatus } from '~/api/projectWorkspace'
import { reactive, ref } from 'vue'
import { VueFinalModal } from 'vue-final-modal'
import { projectWorkspaceApi } from '~/api/projectWorkspace'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'
import { Textarea } from '~/components/ui/textarea'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

// #5：API 清单完整 schema 编辑器——method/path/状态/说明 + 请求字段 + 返回字段
//（每字段含名称/类型/是否可选/说明）。新增（无 existing）或编辑（传 existing）。
const props = defineProps<{ projectId: string, existing?: StateApi | null }>()
const emit = defineEmits<{ confirm: [], cancel: [], closed: [] }>()

const { handleError } = useErrorHandler()
const { success } = useToast()

const METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']
const STATUSES: StateApiStatus[] = ['planned', 'in_progress', 'done']
const FIELD_TYPES = ['string', 'number', 'integer', 'boolean', 'object', 'array', 'datetime', 'enum']

interface FieldDraft { name: string, type: string, optional: boolean, description: string }
function toDraft(f: ApiField): FieldDraft {
  return { name: f.name, type: f.type || 'string', optional: !!f.optional, description: f.description || '' }
}

const form = reactive({
  method: props.existing?.method || 'GET',
  path: props.existing?.path || '',
  status: (props.existing?.status || 'planned') as StateApiStatus,
  description: props.existing?.description || '',
})
const requestFields = reactive<FieldDraft[]>((props.existing?.request_fields || []).map(toDraft))
const responseFields = reactive<FieldDraft[]>((props.existing?.response_fields || []).map(toDraft))

function addField(list: FieldDraft[]) {
  list.push({ name: '', type: 'string', optional: false, description: '' })
}
function removeField(list: FieldDraft[], i: number) {
  list.splice(i, 1)
}

function buildFields(list: FieldDraft[]): ApiField[] {
  return list
    .map(f => ({
      name: f.name.trim(),
      type: f.type.trim() || 'string',
      optional: f.optional,
      description: f.description.trim(),
    }))
    .filter(f => f.name)
}

const submitting = ref(false)
const errorText = ref('')

async function handleSubmit() {
  errorText.value = ''
  if (!form.path.trim()) {
    errorText.value = '请填写 API 路径'
    return
  }
  submitting.value = true
  try {
    const payload = {
      method: form.method,
      path: form.path.trim(),
      status: form.status,
      description: form.description.trim(),
      request_fields: buildFields(requestFields),
      response_fields: buildFields(responseFields),
    }
    if (props.existing)
      await projectWorkspaceApi.patchStateApi(props.projectId, props.existing.id, payload)
    else
      await projectWorkspaceApi.upsertStateApi(props.projectId, payload)
    success('已保存 API')
    emit('confirm')
  }
  catch (e: unknown) {
    handleError(e, '保存 API 失败')
  }
  finally {
    submitting.value = false
  }
}
</script>

<template>
  <VueFinalModal
    class="flex justify-center items-center"
    content-class="flex flex-col bg-card rounded-2xl shadow-lg border border-border/50 max-w-2xl w-full mx-4 max-h-[88vh]"
    overlay-transition="vfm-fade"
    content-transition="vfm-zoom"
    @closed="emit('closed')"
  >
    <header class="flex items-center gap-2.5 px-5 py-4 border-b border-border/50">
      <span class="inline-flex size-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
        <span class="icon-[lucide--webhook]" />
      </span>
      <h2 class="text-sm font-semibold text-foreground">
        {{ existing ? '编辑 API' : '新增 API' }}
      </h2>
    </header>

    <div class="flex-1 min-h-0 overflow-y-auto px-5 py-4 space-y-4">
      <!-- 基本信息 -->
      <div class="flex items-center gap-2">
        <Select v-model="form.method">
          <SelectTrigger class="h-9 w-28 text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem v-for="m in METHODS" :key="m" :value="m">
              {{ m }}
            </SelectItem>
          </SelectContent>
        </Select>
        <Input
          v-model="form.path"
          placeholder="/api/资源/路径"
          class="h-9 flex-1 font-mono text-sm"
          spellcheck="false"
          autocomplete="off"
        />
        <Select v-model="form.status">
          <SelectTrigger class="h-9 w-28 text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem v-for="s in STATUSES" :key="s" :value="s">
              {{ s === 'planned' ? '规划中' : s === 'in_progress' ? '开发中' : '已完成' }}
            </SelectItem>
          </SelectContent>
        </Select>
      </div>
      <Textarea v-model="form.description" placeholder="接口说明（可选）" :rows="2" class="text-sm" />

      <!-- 请求字段 + 返回字段 -->
      <div v-for="group in [{ key: 'req', label: '请求字段', list: requestFields }, { key: 'res', label: '返回字段', list: responseFields }]" :key="group.key" class="space-y-2">
        <div class="flex items-center gap-2">
          <h3 class="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
            {{ group.label }}
          </h3>
          <button
            type="button"
            class="ml-auto text-xs text-primary inline-flex items-center gap-1 hover:underline"
            :data-testid="`api-add-field-${group.key}`"
            @click="addField(group.list)"
          >
            <span class="icon-[lucide--plus] text-[11px]" /> 添加字段
          </button>
        </div>
        <p v-if="group.list.length === 0" class="text-xs text-muted-foreground/70">
          暂无字段
        </p>
        <div
          v-for="(f, i) in group.list"
          :key="i"
          class="flex items-center gap-2"
        >
          <Input v-model="f.name" placeholder="字段名" class="h-8 w-32 font-mono text-xs" />
          <Select v-model="f.type">
            <SelectTrigger class="h-8 w-28 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem v-for="ty in FIELD_TYPES" :key="ty" :value="ty">
                {{ ty }}
              </SelectItem>
            </SelectContent>
          </Select>
          <label class="inline-flex items-center gap-1 text-xs text-muted-foreground shrink-0 cursor-pointer">
            <input v-model="f.optional" type="checkbox" class="size-3.5"> 可选
          </label>
          <Input v-model="f.description" placeholder="说明" class="h-8 flex-1 text-xs" />
          <button
            type="button"
            class="size-7 inline-flex items-center justify-center rounded-md text-muted-foreground hover:text-destructive shrink-0"
            aria-label="删除字段"
            @click="removeField(group.list, i)"
          >
            <span class="icon-[lucide--x] text-sm" />
          </button>
        </div>
      </div>

      <p v-if="errorText" class="text-sm text-destructive">
        {{ errorText }}
      </p>
    </div>

    <footer class="flex items-center justify-end gap-2 px-5 py-4 border-t border-border/50">
      <Button variant="ghost" :disabled="submitting" @click="emit('cancel')">
        取消
      </Button>
      <Button :disabled="submitting" data-testid="api-schema-save" @click="handleSubmit">
        保存
      </Button>
    </footer>
  </VueFinalModal>
</template>
