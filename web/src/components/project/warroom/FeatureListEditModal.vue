<script setup lang="ts">
import type { FeatureListModuleInput } from '~/api/projectWorkspace'
import { reactive, ref } from 'vue'
import { VueFinalModal } from 'vue-final-modal'
import { projectWorkspaceApi } from '~/api/projectWorkspace'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Textarea } from '~/components/ui/textarea'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

// #5 feature list 录入弹窗：两种方式——手动录入（模块 → 功能点 → 验收项）
// 或 贴飞书多维表格链接。提交经 POST /projects/{id}/feature-list/，由 ArtifactService 收口。
const props = defineProps<{ projectId: string }>()
const emit = defineEmits<{ confirm: [], cancel: [], closed: [] }>()

const { handleError } = useErrorHandler()
const { success } = useToast()

type Mode = 'manual' | 'paste' | 'gitlab' | 'feishu'
const mode = ref<Mode>('manual')
const submitting = ref(false)

const MODE_TABS: { id: Mode, label: string }[] = [
  { id: 'manual', label: '手动录入' },
  { id: 'paste', label: '粘贴解析' },
  { id: 'gitlab', label: 'GitLab 文档' },
  { id: 'feishu', label: '飞书链接' },
]

// 粘贴文档（AI 逐字解析）/ GitLab 文件链接。
const pasteText = ref('')
const gitlabUrl = ref('')

// 手动录入：模块 → 功能点（验收项以换行分隔，提交时拆成数组）。
interface FeatureDraft { name: string, acceptanceText: string }
interface ModuleDraft { module: string, features: FeatureDraft[] }
const modules = reactive<ModuleDraft[]>([
  { module: '', features: [{ name: '', acceptanceText: '' }] },
])

const feishuUrl = ref('')

function addModule() {
  modules.push({ module: '', features: [{ name: '', acceptanceText: '' }] })
}
function removeModule(i: number) {
  modules.splice(i, 1)
  if (modules.length === 0)
    addModule()
}
function addFeature(mi: number) {
  modules[mi].features.push({ name: '', acceptanceText: '' })
}
function removeFeature(mi: number, fi: number) {
  modules[mi].features.splice(fi, 1)
  if (modules[mi].features.length === 0)
    modules[mi].features.push({ name: '', acceptanceText: '' })
}

function buildManualPayload(): FeatureListModuleInput[] {
  return modules
    .map(m => ({
      module: m.module.trim() || '未分组',
      features: m.features
        .map(f => ({
          name: f.name.trim(),
          acceptance: f.acceptanceText
            .split('\n')
            .map(s => s.trim())
            .filter(Boolean),
        }))
        .filter(f => f.name),
    }))
    .filter(m => m.features.length > 0)
}

const errorText = ref('')

async function handleSubmit() {
  errorText.value = ''
  submitting.value = true
  try {
    if (mode.value === 'manual') {
      const payload = buildManualPayload()
      if (payload.length === 0) {
        errorText.value = '请至少填写一个功能点'
        return
      }
      await projectWorkspaceApi.setFeatureList(props.projectId, { mode: 'manual', modules: payload })
    }
    else if (mode.value === 'paste') {
      const text = pasteText.value.trim()
      if (!text) {
        errorText.value = '请粘贴文档内容'
        return
      }
      await projectWorkspaceApi.setFeatureList(props.projectId, { mode: 'paste', text })
    }
    else if (mode.value === 'gitlab') {
      const url = gitlabUrl.value.trim()
      if (!url) {
        errorText.value = '请填写 GitLab 文件链接'
        return
      }
      await projectWorkspaceApi.setFeatureList(props.projectId, { mode: 'gitlab', url })
    }
    else {
      const url = feishuUrl.value.trim()
      if (!url) {
        errorText.value = '请填写飞书多维表格链接'
        return
      }
      await projectWorkspaceApi.setFeatureList(props.projectId, { mode: 'feishu', url })
    }
    success('已保存 feature list')
    emit('confirm')
  }
  catch (e: unknown) {
    handleError(e, '保存 feature list')
  }
  finally {
    submitting.value = false
  }
}
</script>

<template>
  <VueFinalModal
    class="flex justify-center items-center"
    content-class="flex flex-col bg-card rounded-2xl shadow-lg border border-border/50 max-w-2xl w-full mx-4 max-h-[85vh]"
    overlay-transition="vfm-fade"
    content-transition="vfm-zoom"
    @closed="emit('closed')"
  >
    <header class="flex items-center gap-2.5 px-5 py-4 border-b border-border/50">
      <span class="inline-flex size-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
        <span class="icon-[lucide--list-tree]" />
      </span>
      <div class="min-w-0">
        <h2 class="text-sm font-semibold text-foreground">
          补充 feature list
        </h2>
        <p class="text-xs text-muted-foreground">
          手动录入，或贴飞书多维表格链接同步进来
        </p>
      </div>
    </header>

    <!-- 模式切换 -->
    <div class="px-5 pt-4">
      <div class="inline-flex flex-wrap rounded-lg border border-border/60 p-0.5 text-sm gap-0.5">
        <button
          v-for="tab in MODE_TABS"
          :key="tab.id"
          type="button"
          class="px-3 py-1 rounded-md transition-colors"
          :class="mode === tab.id ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'"
          :data-testid="`fl-mode-${tab.id}`"
          @click="mode = tab.id"
        >
          {{ tab.label }}
        </button>
      </div>
    </div>

    <div class="flex-1 min-h-0 overflow-y-auto px-5 py-4 space-y-4">
      <!-- 手动录入 -->
      <div v-if="mode === 'manual'" class="space-y-4" data-testid="fl-manual">
        <div
          v-for="(mod, mi) in modules"
          :key="mi"
          class="rounded-lg border border-border/60 p-3 space-y-3"
        >
          <div class="flex items-center gap-2">
            <Input
              v-model="mod.module"
              placeholder="模块名（如：用户中心）"
              class="h-8 flex-1"
            />
            <button
              type="button"
              class="size-8 inline-flex items-center justify-center rounded-md text-muted-foreground hover:text-destructive hover:bg-destructive/5"
              :aria-label="`删除模块 ${mi + 1}`"
              @click="removeModule(mi)"
            >
              <span class="icon-[lucide--trash-2] text-sm" />
            </button>
          </div>

          <div
            v-for="(feat, fi) in mod.features"
            :key="fi"
            class="rounded-md border border-border/40 bg-muted/20 p-2.5 space-y-2"
          >
            <div class="flex items-center gap-2">
              <span class="icon-[lucide--git-branch] text-muted-foreground text-sm shrink-0" />
              <Input
                v-model="feat.name"
                placeholder="功能点名称"
                class="h-8 flex-1"
              />
              <button
                type="button"
                class="size-7 inline-flex items-center justify-center rounded-md text-muted-foreground hover:text-destructive"
                :aria-label="`删除功能点 ${fi + 1}`"
                @click="removeFeature(mi, fi)"
              >
                <span class="icon-[lucide--x] text-sm" />
              </button>
            </div>
            <Textarea
              v-model="feat.acceptanceText"
              placeholder="验收项（每行一条，可留空）"
              :rows="2"
              class="text-sm"
            />
          </div>

          <button
            type="button"
            class="text-xs text-primary inline-flex items-center gap-1 hover:underline"
            @click="addFeature(mi)"
          >
            <span class="icon-[lucide--plus] text-[11px]" /> 添加功能点
          </button>
        </div>

        <button
          type="button"
          class="w-full rounded-lg border border-dashed border-border/70 py-2 text-sm text-muted-foreground hover:border-primary/40 hover:text-primary transition-colors"
          data-testid="fl-add-module"
          @click="addModule"
        >
          <span class="icon-[lucide--folder-plus] mr-1.5" /> 添加模块
        </button>
      </div>

      <!-- 粘贴文档（AI 逐字解析） -->
      <div v-else-if="mode === 'paste'" class="space-y-2" data-testid="fl-paste">
        <label class="text-sm font-medium text-foreground">粘贴文档内容</label>
        <Textarea
          v-model="pasteText"
          placeholder="把需求 / PRD / feature 文档整篇粘贴进来，AI 会解析为「模块 → 功能点 → 验收项」结构"
          :rows="10"
          class="text-sm font-mono"
        />
        <p class="text-xs text-muted-foreground">
          AI 仅解析结构，功能点 / 验收项内容<strong>逐字保留原文</strong>（不改写、不翻译）。
        </p>
      </div>

      <!-- GitLab 文件链接（全局凭证鉴权取文 + AI 解析） -->
      <div v-else-if="mode === 'gitlab'" class="space-y-2" data-testid="fl-gitlab">
        <label class="text-sm font-medium text-foreground">GitLab 文件链接</label>
        <Input
          v-model="gitlabUrl"
          placeholder="https://gitlab.xxx.com/group/proj/-/blob/main/docs/features.md"
          class="h-9 font-mono text-sm"
        />
        <p class="text-xs text-muted-foreground">
          用全局 GitLab 凭证（按 host 命中）拉取该文件，再由 AI 逐字解析为 feature 结构。
        </p>
      </div>

      <!-- 飞书链接 -->
      <div v-else class="space-y-2" data-testid="fl-feishu">
        <label class="text-sm font-medium text-foreground">飞书多维表格链接</label>
        <Input
          v-model="feishuUrl"
          placeholder="https://xxx.feishu.cn/base/..."
          class="h-9"
        />
        <p class="text-xs text-muted-foreground">
          贴入承载「模块 / 功能点 / 验收项 / 状态」的多维表格链接，系统会同步并解析为 feature 树。
        </p>
      </div>

      <p v-if="errorText" class="text-sm text-destructive" data-testid="fl-error">
        {{ errorText }}
      </p>
    </div>

    <footer class="flex items-center justify-end gap-2 px-5 py-4 border-t border-border/50">
      <Button variant="ghost" :disabled="submitting" @click="emit('cancel')">
        取消
      </Button>
      <Button :disabled="submitting" data-testid="fl-submit" @click="handleSubmit">
        <span v-if="submitting" class="icon-[lucide--loader-2] mr-1.5 animate-spin" />
        保存
      </Button>
    </footer>
  </VueFinalModal>
</template>
