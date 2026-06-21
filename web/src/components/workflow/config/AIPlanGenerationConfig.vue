<script setup lang="ts">
import type { WorkflowEdge, WorkflowNode } from '~/types/workflow/store'

import { storeToRefs } from 'pinia'
import { computed, onMounted, ref } from 'vue'

import ModelSelect from '~/components/providers/ModelSelect.vue'
import ProviderCredentialDropdown from '~/components/providers/ProviderCredentialDropdown.vue'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '~/components/ui/collapsible'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import RepositoryPicker from '~/components/workflow/RepositoryPicker.vue'
import { MarkdownEditorModal, SmartMarkdownEditor, SmartTextarea } from '~/components/workflow/smart-input'
import { useConfigModel } from '~/composables/useConfigModel'
import { useRepositoriesStore } from '~/stores/repositories'

/**
 * AIPlanGenerationConfig - Configuration panel for AI Plan Generation node.
 *
 * Features:
 * - Repository selection: include/exclude dual tag lists
 * - User Prompt: Markdown editor with variable support (expanded by default)
 * - System Prompt: Markdown editor (collapsed by default)
 * - Advanced options: provider credential, model, max iterations
 * - chat_id: 仅用于 AI 飞书澄清提问（ask_user_question）；方案推送/审批已解耦到下游节点
 */

// ============================================================================
// Types
// ============================================================================

interface AIPlanGenerationConfig {
  system_prompt: string
  user_prompt: string
  include_repos: string[]
  exclude_repos: string[]
  max_iterations: number
  enabled_tools: string[]
  chat_id: string
  use_custom_api: boolean
  api_base_url: string
  api_key: string
  model: string
  provider_credential_id?: string | null
}

// ============================================================================
// Props & Emits
// ============================================================================

interface Props {
  config: AIPlanGenerationConfig
  workflowNodes?: WorkflowNode[]
  workflowEdges?: WorkflowEdge[]
  currentNodeId?: string
}

const props = withDefaults(defineProps<Props>(), {
  workflowNodes: () => [],
  workflowEdges: () => [],
  currentNodeId: '',
})

const emit = defineEmits<{
  (e: 'update:config', value: AIPlanGenerationConfig): void
}>()

// ============================================================================
// Config Model
// ============================================================================

const { field } = useConfigModel({
  config: () => props.config as unknown as Record<string, unknown>,
  emit: v => emit('update:config', v as unknown as AIPlanGenerationConfig),
})

const systemPrompt = field('system_prompt', '') as import('vue').WritableComputedRef<string>
const userPrompt = field('user_prompt', '') as import('vue').WritableComputedRef<string>
const includeRepos = field('include_repos', []) as import('vue').WritableComputedRef<string[]>
const excludeRepos = field('exclude_repos', []) as import('vue').WritableComputedRef<string[]>
const maxIterations = field('max_iterations', 50) as import('vue').WritableComputedRef<number>
const chatId = field('chat_id', '') as import('vue').WritableComputedRef<string>

// 模型：方案生成统一走系统 Provider 凭证（默认 Anthropic），不再暴露自定义 API。
const model = field('model', '') as import('vue').WritableComputedRef<string>

// Provider 凭证
// AIPlanGenerationConfig 当前模板未渲染 thinking / reasoning_effort 字段,
// 故不声明对应的 capability computed(避免 noUnusedLocals);仅保留 id 字段双向绑定。
// 若在方案生成卡片内补 thinking UI,再按 Task 08-01 模式接入 providerStore + supports_thinking。
const providerCredentialIdField = field('provider_credential_id', null) as import('vue').WritableComputedRef<string | null>
const providerCredentialId = computed<string | null>({
  get: () => providerCredentialIdField.value ?? null,
  set: (v: string | null) => { providerCredentialIdField.value = v },
})

// ============================================================================
// 仓库选择（模糊搜索）— 后端 include_repos/exclude_repos 存仓库 UUID，
// 故用 RepositoryPicker 从真实仓库列表选择，同时保留手动输入（变量/UUID）。
// ============================================================================

const repositoriesStore = useRepositoriesStore()
const { repositories: allRepositories } = storeToRefs(repositoriesStore)

const repoOptions = computed(() =>
  allRepositories.value.map(r => ({ id: r.id, name: r.name })),
)

onMounted(() => {
  if (allRepositories.value.length === 0)
    repositoriesStore.fetchRepositories().catch(() => {})
})

// ============================================================================
// Modal & Collapsible State
// ============================================================================

const systemPromptOpen = ref(false)
const systemPromptModalOpen = ref(false)
const userPromptModalOpen = ref(false)
const advancedOpen = ref(false)
</script>

<template>
  <div class="space-y-4">
    <!-- ================================================================== -->
    <!-- Introduction Card -->
    <!-- ================================================================== -->
    <div class="rounded-xl bg-primary/10 border border-primary/20 p-3">
      <div class="flex items-start gap-2">
        <span class="icon-[lucide--sparkles] text-primary text-lg shrink-0 mt-0.5" />
        <div class="space-y-1.5">
          <h4 class="text-sm font-medium">
            AI 方案生成
          </h4>
          <p class="text-xs text-muted-foreground leading-relaxed">
            基于 <span class="text-primary font-medium">ReAct Agent</span> 自动分析多仓库代码，
            通过向量检索 (RAG) 理解代码上下文，生成结构化技术方案并自动验证。
            方案的文档生成、审批与推送交由下游节点（人工审批 / 飞书文档 / 飞书通知）负责。
          </p>
          <!-- Capability Tags -->
          <div class="flex flex-wrap gap-1 pt-0.5">
            <span class="px-1.5 py-0.5 rounded bg-primary/10 text-primary text-[10px] font-medium">ReAct</span>
            <span class="px-1.5 py-0.5 rounded bg-primary/10 text-primary text-[10px] font-medium">RAG 向量检索</span>
            <span class="px-1.5 py-0.5 rounded bg-primary/10 text-primary text-[10px] font-medium">verify_plan</span>
          </div>
        </div>
      </div>
    </div>

    <!-- ================================================================== -->
    <!-- Phase Timeline -->
    <!-- ================================================================== -->
    <div class="relative pl-6">
      <!-- 左侧竖线 -->
      <div class="absolute left-[9px] top-2 bottom-2 w-px bg-linear-to-b from-primary/40 via-primary/30 to-primary/20" />

      <!-- ============================================================== -->
      <!-- : 需求输入 -->
      <!-- ============================================================== -->
      <div class="relative pb-5">
        <!-- 步骤圆点 -->
        <div class="absolute -left-6 top-0.5 flex items-center justify-center w-[19px] h-[19px] rounded-full bg-primary/15 border border-primary/30">
          <span class="text-[10px] font-bold text-primary">1</span>
        </div>

        <div class="space-y-2.5">
          <div>
            <h5 class="text-sm font-medium flex items-center gap-1.5">
              <span class="icon-[lucide--file-text] text-primary text-sm" />
              需求输入
            </h5>
            <p class="text-[11px] text-muted-foreground mt-0.5">
              描述你的需求，AI 将以此为起点分析代码并生成方案
            </p>
          </div>

          <div class="space-y-1.5">
            <Label class="text-xs flex items-center gap-1">
              用户提示词
              <span class="text-destructive">*</span>
            </Label>
            <SmartMarkdownEditor
              v-model="userPrompt"
              :workflow-nodes="workflowNodes"
              :workflow-edges="workflowEdges"
              :current-node-id="currentNodeId"
              placeholder="描述需求内容，输入 {{ 引用上游节点变量..."
              :min-rows="5"
              :show-toolbar="true"
              :compact="true"
              @expand="userPromptModalOpen = true"
            />
            <p class="text-[10px] text-muted-foreground">
              支持 Markdown 和 <code class="text-[10px] px-1 py-0.5 bg-muted rounded">{'{{ '}nodes.ID.field{' }}'}</code> 变量引用
            </p>
          </div>
        </div>
      </div>

      <!-- ============================================================== -->
      <!-- : 代码检索 -->
      <!-- ============================================================== -->
      <div class="relative pb-5">
        <div class="absolute -left-6 top-0.5 flex items-center justify-center w-[19px] h-[19px] rounded-full bg-primary/15 border border-primary/30">
          <span class="text-[10px] font-bold text-primary">2</span>
        </div>

        <div class="space-y-2.5">
          <div>
            <h5 class="text-sm font-medium flex items-center gap-1.5">
              <span class="icon-[lucide--search-code] text-primary text-sm" />
              代码检索
              <span class="px-1.5 py-0.5 rounded bg-primary/10 text-primary text-[9px] font-medium">RAG</span>
            </h5>
            <p class="text-[11px] text-muted-foreground mt-0.5">
              通过向量检索跨仓库搜索相关代码，分析依赖关系和代码结构
            </p>
          </div>

          <!-- Include Repos -->
          <div class="space-y-1.5">
            <Label class="text-xs text-muted-foreground">必须包含的仓库</Label>
            <RepositoryPicker
              v-model="includeRepos"
              :repositories="repoOptions"
              placeholder="搜索并选择仓库..."
            />
          </div>

          <!-- Exclude Repos -->
          <div class="space-y-1.5">
            <Label class="text-xs text-muted-foreground">必须排除的仓库</Label>
            <RepositoryPicker
              v-model="excludeRepos"
              :repositories="repoOptions"
              placeholder="搜索并选择要排除的仓库..."
            />
            <p class="text-[10px] text-muted-foreground">
              未指定的仓库由 AI 自动决定是否检索
            </p>
          </div>
        </div>
      </div>

      <!-- ============================================================== -->
      <!-- : 方案生成 -->
      <!-- ============================================================== -->
      <div class="relative pb-5">
        <div class="absolute -left-6 top-0.5 flex items-center justify-center w-[19px] h-[19px] rounded-full bg-primary/15 border border-primary/30">
          <span class="text-[10px] font-bold text-primary">3</span>
        </div>

        <div class="space-y-2.5">
          <div>
            <h5 class="text-sm font-medium flex items-center gap-1.5">
              <span class="icon-[lucide--sparkles] text-primary text-sm" />
              方案生成
              <span class="px-1.5 py-0.5 rounded bg-primary/10 text-primary text-[9px] font-medium">ReAct</span>
            </h5>
            <p class="text-[11px] text-muted-foreground mt-0.5">
              ReAct Agent 循环推理，基于代码检索结果生成结构化技术方案
            </p>
          </div>

          <!-- System Prompt (collapsed) -->
          <Collapsible v-model:open="systemPromptOpen">
            <CollapsibleTrigger class="flex items-center justify-between w-full py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors">
              <span class="flex items-center gap-1.5">
                <span class="icon-[lucide--settings] text-sm" />
                自定义系统指令
              </span>
              <span
                class="icon-[lucide--chevron-down] text-xs transition-transform duration-200"
                :class="{ 'rotate-180': systemPromptOpen }"
              />
            </CollapsibleTrigger>
            <CollapsibleContent class="space-y-1.5 pt-1.5">
              <SmartMarkdownEditor
                v-model="systemPrompt"
                :workflow-nodes="workflowNodes"
                :workflow-edges="workflowEdges"
                :current-node-id="currentNodeId"
                placeholder="追加到系统默认提示词末尾的自定义指令..."
                :min-rows="3"
                :show-toolbar="true"
                :compact="true"
                @expand="systemPromptModalOpen = true"
              />
              <p class="text-[10px] text-muted-foreground">
                追加到系统默认 System Prompt 末尾，留空使用默认配置
              </p>
            </CollapsibleContent>
          </Collapsible>

          <!-- Model & Iterations -->
          <Collapsible v-model:open="advancedOpen">
            <CollapsibleTrigger class="flex items-center justify-between w-full py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors">
              <span class="flex items-center gap-1.5">
                <span class="icon-[lucide--cpu] text-sm" />
                模型 & 参数
              </span>
              <span
                class="icon-[lucide--chevron-down] text-xs transition-transform duration-200"
                :class="{ 'rotate-180': advancedOpen }"
              />
            </CollapsibleTrigger>
            <CollapsibleContent class="space-y-3 pt-1.5">
              <!-- Provider 凭证(/05/06) -->
              <div class="space-y-1.5">
                <Label class="text-xs font-normal">
                  Provider 凭证
                </Label>
                <ProviderCredentialDropdown
                  :model-value="providerCredentialId"
                  scope="system"
                  @update:model-value="v => providerCredentialId = v"
                />
                <p class="text-[10px] text-muted-foreground">
                  选择一条启用中的 Provider 凭证,未选择则走系统默认
                </p>
              </div>

              <!-- 模型(方案生成需要 ReadFile/Grep 等工具,UI-06 requires-tools=true) -->
              <div class="space-y-1.5">
                <Label class="text-xs font-normal">
                  模型
                </Label>
                <ModelSelect
                  :credential-id="providerCredentialId"
                  :requires-tools="true"
                  :model-value="model"
                  @update:model-value="v => model = v ?? ''"
                />
                <p class="text-[10px] text-muted-foreground">
                  默认使用系统 Anthropic 凭证，仅列出支持 tool use 的模型
                </p>
              </div>

              <div class="space-y-1.5">
                <Label class="text-xs">最大迭代轮次</Label>
                <Input
                  v-model="maxIterations"
                  type="number"
                  :min="10"
                  :max="200"
                  class="bg-background/50 h-8 text-sm"
                />
                <p class="text-[10px] text-muted-foreground">
                  方案生成 Agent 的 ReAct 推理上限：每轮可调用一次工具（如代码检索、verify_plan），
                  到达上限仍未产出方案即停止，防止死循环。一般 50 足够，复杂跨仓需求可调高。
                </p>
              </div>
            </CollapsibleContent>
          </Collapsible>
        </div>
      </div>

      <!-- ============================================================== -->
      <!-- : 自动验证 -->
      <!-- ============================================================== -->
      <div class="relative pb-5">
        <div class="absolute -left-6 top-0.5 flex items-center justify-center w-[19px] h-[19px] rounded-full bg-primary/15 border border-primary/30">
          <span class="text-[10px] font-bold text-primary">4</span>
        </div>

        <div>
          <h5 class="text-sm font-medium flex items-center gap-1.5">
            <span class="icon-[lucide--shield-check] text-primary text-sm" />
            自动验证
            <span class="px-1.5 py-0.5 rounded bg-primary/10 text-primary text-[9px] font-medium">自动</span>
          </h5>
          <p class="text-[11px] text-muted-foreground mt-0.5">
            调用 <code class="text-[10px] px-1 py-0.5 bg-muted rounded">verify_plan</code> 验证方案格式和完整性，失败自动重试（最多 3 轮）
          </p>
        </div>
      </div>

      <!-- ============================================================== -->
      <!-- : 飞书澄清提问（可选） -->
      <!-- ============================================================== -->
      <div class="relative">
        <div class="absolute -left-6 top-0.5 flex items-center justify-center w-[19px] h-[19px] rounded-full bg-primary/15 border border-primary/30">
          <span class="text-[10px] font-bold text-primary">5</span>
        </div>

        <div class="space-y-2.5">
          <div>
            <h5 class="text-sm font-medium flex items-center gap-1.5">
              <span class="icon-[lucide--message-circle-question] text-primary text-sm" />
              飞书澄清提问
              <span class="px-1.5 py-0.5 rounded bg-muted text-muted-foreground text-[9px] font-medium">可选</span>
            </h5>
            <p class="text-[11px] text-muted-foreground mt-0.5">
              需求不清晰时 AI 经飞书向用户提问澄清（ask_user_question）。方案文档生成、
              审批与推送已解耦到下游节点，本节点不再自动推送方案卡片。
            </p>
          </div>

          <div class="space-y-1.5">
            <Label class="text-xs flex items-center gap-1.5">
              飞书群聊 ID
            </Label>
            <SmartTextarea
              v-model="chatId"
              :workflow-nodes="workflowNodes"
              :workflow-edges="workflowEdges"
              :current-node-id="currentNodeId"
              placeholder="输入 {{ 选择变量，如 fetch_project.fields..."
              :min-rows="1"
              class="bg-background/50"
            />
            <p class="text-[10px] text-muted-foreground">
              AI 澄清提问卡片发送的目标群聊，支持变量引用；留空则不启用澄清提问
            </p>
          </div>
        </div>
      </div>
    </div>

    <!-- ================================================================== -->
    <!-- Modals -->
    <!-- ================================================================== -->
    <MarkdownEditorModal
      v-model:open="systemPromptModalOpen"
      v-model="systemPrompt"
      title="编辑系统提示词"
      description="追加到系统默认提示词末尾的自定义指令"
      :workflow-nodes="workflowNodes"
      :workflow-edges="workflowEdges"
      :current-node-id="currentNodeId"
      placeholder="追加到系统默认提示词末尾的自定义指令..."
    />

    <MarkdownEditorModal
      v-model:open="userPromptModalOpen"
      v-model="userPrompt"
      title="编辑用户提示词"
      description="描述需求内容，输入 {{ 引用上游节点变量"
      :workflow-nodes="workflowNodes"
      :workflow-edges="workflowEdges"
      :current-node-id="currentNodeId"
      placeholder="描述需求内容，输入 {{ 引用上游节点变量..."
    />
  </div>
</template>
