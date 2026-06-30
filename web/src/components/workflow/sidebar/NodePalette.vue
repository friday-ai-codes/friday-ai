<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ALL_NODE_DEFINITIONS } from '~/types/workflow/node-definitions'
import { getRecentNodes } from '../editor/composables/useDragAndDrop'
import { getNodeVisual } from '../editor/nodes/nodeVisuals'
import NodePaletteItem from './NodePaletteItem.vue'

/**
 * 节点分组定义 — 组名和节点列表在这里维护。
 * : 已迁移节点的 name/description 从 ALL_NODE_DEFINITIONS 自动读取，
 * legacy 节点保留硬编码。后续 Phase 迁移更多节点后逐步移除硬编码。
 */
interface PaletteItem {
  type: string
  name: string
  description: string
}

interface PaletteGroup {
  name: string
  items: PaletteItem[]
}

/**
 * 从 ALL_NODE_DEFINITIONS 解析节点信息
 * 保留 `type: 'xxx'` 格式以便 CI 正则提取节点类型列表
 */
function fromDef(type: string, name: string, description: string): PaletteItem {
  const def = ALL_NODE_DEFINITIONS[type]
  return { type, name: def?.displayName ?? name, description: def?.description ?? description }
}

const nodeGroups = computed<PaletteGroup[]>(() => [
  {
    name: '触发器',
    items: [
      fromDef('manual_trigger', '手动触发', '手动启动工作流'),
      fromDef('webhook_trigger', 'Webhook', '通过 HTTP 请求触发'),
      { type: 'feishu_event_trigger', name: '飞书事件', description: '飞书事件触发' },
    ],
  },
  {
    name: '数据获取',
    items: [
      { type: 'fetch_work_item', name: '获取工作项', description: '从空间获取工作项信息' },
      { type: 'fetch_space_info', name: '获取空间信息', description: '获取空间/项目详细信息' },
      { type: 'context_retrieval', name: '上下文检索', description: '检索相关上下文信息' },
      { type: 'delivery_knowledge_search', name: '交付知识检索', description: '检索相似历史交付' },
    ],
  },
  {
    name: '操作',
    items: [
      fromDef('http_request', 'HTTP 请求', '发送 HTTP 请求'),
      fromDef('code', '代码执行', '执行 Python 代码片段'),
      { type: 'wait_feishu_field', name: '等待飞书', description: '等待飞书消息响应' },
    ],
  },
  {
    name: '集成',
    items: [
      { type: 'create_branch', name: '创建分支', description: '创建 Git 分支' },
      { type: 'ai_create_branch', name: 'AI 创建分支', description: '基于方案/feature list 给多仓建分支并绑项目' },
      { type: 'create_project_workspace', name: '创建项目', description: '创建项目并建 5 文件、绑定/AI 拆分 feature list' },
      { type: 'create_pr', name: '创建 PR', description: '创建 Pull Request' },
      fromDef('merge_pr', '合并 PR', '合并 Pull Request'),
      fromDef('mcp_deploy', 'MCP 部署', 'MCP 服务部署'),
      fromDef('fetch_group_chat', '获取群聊', '从飞书工作项获取群聊 ID'),
      fromDef('create_group_chat', '创建群聊', '创建飞书群并拉入成员，输出 chat_id'),
      { type: 'create_work_item_chat', name: '创建工作项群聊', description: '飞书原生自动建群并绑定到工作项，输出 chat_id' },
      fromDef('join_group_chat', '加入群聊', 'Bot 加入目标群聊'),
      fromDef('group_chat_question', '群聊提问', '向群聊发送提问卡片等待回答'),
    ],
  },
  {
    name: '通知',
    items: [
      fromDef('notify_feishu', '飞书通知', '发送飞书消息通知'),
      fromDef('notify_feishu_im', '飞书通知(IM)', '向群聊或个人发送通知'),
      fromDef('feishu_doc_create', '飞书文档生成', '把 Markdown 生成为飞书文档'),
    ],
  },
  {
    name: 'AI',
    items: [
      { type: 'ai_prompt', name: 'AI Prompt', description: '调用 AI 大语言模型' },
      { type: 'ai_coding_dispatcher', name: 'AI 编码指派', description: '分析需求分配编码任务' },
      { type: 'ai_variable_extractor', name: 'AI 变量提取', description: 'AI 提取变量' },
      { type: 'variable_extractor', name: '变量提取', description: '提取变量值' },
      { type: 'ai_plan_research', name: 'AI 方案研究', description: '统一编排生成技术方案' },
      { type: 'ai_coding', name: 'AI 编码执行', description: 'AI 自动编码并创建 MR' },
      { type: 'clarification_card', name: '澄清卡', description: '发送澄清交互卡并等待回答' },
    ],
  },
  {
    name: '控制流',
    items: [
      fromDef('condition', '条件判断', '根据条件分支'),
      fromDef('human_approval', '人工审批', '等待人工审批'),
      fromDef('delay', '延时', '等待指定时长后继续'),
      fromDef('parallel', '并行分支', '并行执行多个分支'),
      fromDef('join', '汇聚', '等待所有并行分支完成'),
      fromDef('foreach', 'ForEach 循环', '对列表中的每个元素执行操作'),
      fromDef('aggregate', '变量聚合', '将多个上游节点输出绑定为结构化变量'),
    ],
  },
])

// 搜索功能
const searchQuery = ref('')

function handleSearchKeydown(event: KeyboardEvent) {
  // 阻止浏览器默认搜索行为（Ctrl+F 和 /）
  const isModifier = event.ctrlKey || event.metaKey
  if ((isModifier && event.key === 'f') || event.key === '/') {
    event.preventDefault()
  }
}

const filteredGroups = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q)
    return nodeGroups.value
  return nodeGroups.value
    .map(group => ({
      ...group,
      items: group.items.filter(item =>
        item.name.toLowerCase().includes(q) || item.description.toLowerCase().includes(q),
      ),
    }))
    .filter(group => group.items.length > 0)
})

// 最近使用节点
const recentNodes = ref<PaletteItem[]>([])

function updateRecentNodes() {
  const recent = getRecentNodes()
  recentNodes.value = recent
    .map((type) => {
      const item = nodeGroups.value.flatMap(g => g.items).find(i => i.type === type)
      return item ?? null
    })
    .filter(Boolean) as PaletteItem[]
}

updateRecentNodes()

onMounted(() => window.addEventListener('friday:recent-nodes-changed', updateRecentNodes))
onUnmounted(() => window.removeEventListener('friday:recent-nodes-changed', updateRecentNodes))

/** 从 nodeVisuals 获取分组的主色 — 取第一个 item 的颜色 */
function getGroupColor(group: PaletteGroup): string {
  return getNodeVisual(group.items[0]?.type ?? '').color
}

/**
 * 分类标签胶囊配色 — 之前返回空字符串导致「白字 + 透明背景」完全不可见。
 * 现按节点色系给出柔和底色 + 同色系文字，保证可读且彼此区分。
 */
function getCategoryGradient(color: string): string {
  const styles: Record<string, string> = {
    blue: 'bg-blue-500/12 text-blue-600',
    green: 'bg-emerald-500/12 text-emerald-600',
    purple: 'bg-violet-500/12 text-violet-600',
    orange: 'bg-amber-500/15 text-amber-600',
  }
  return styles[color] || styles.blue
}

/** 分类标签前的小圆点颜色，与胶囊配色呼应 */
function getCategoryDot(color: string): string {
  const dots: Record<string, string> = {
    blue: 'bg-blue-500',
    green: 'bg-emerald-500',
    purple: 'bg-violet-500',
    orange: 'bg-amber-500',
  }
  return dots[color] || dots.blue
}
</script>

<template>
  <div class="h-full w-64 shrink-0 flex flex-col rounded-2xl bg-card/70 backdrop-blur-sm border border-border/50 overflow-hidden m-3">
    <!-- Header -->
    <div class="p-4 border-b border-border/50">
      <div class="flex items-center gap-3">
        <div class="p-2.5 rounded-xl bg-primary/10">
          <span class="icon-[lucide--boxes] text-xl text-primary" />
        </div>
        <div>
          <h3 class="text-base font-semibold flex items-center gap-2">
            <div class="w-2 h-2 rounded-full bg-primary animate-pulse" />
            节点库
          </h3>
          <p class="text-xs text-muted-foreground">
            拖拽节点到画布上
          </p>
        </div>
      </div>
    </div>

    <!-- Search -->
    <div class="px-3 pt-2 pb-1">
      <div class="relative">
        <span class="icon-[lucide--search] absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
        <input
          v-model="searchQuery"
          type="text"
          aria-label="搜索节点"
          placeholder="搜索节点..."
          class="w-full pl-8 pr-3 py-1.5 text-xs bg-muted/50 border border-border/30 rounded-lg focus:outline-none focus:ring-1 focus:ring-primary/30 focus:border-primary/30 placeholder:text-muted-foreground/50"
          @keydown="handleSearchKeydown"
        >
      </div>
    </div>

    <!-- Content: Scrollable list of categories -->
    <div class="flex-1 overflow-y-auto p-3 space-y-5">
      <!-- Recent Nodes -->
      <div v-if="recentNodes.length > 0 && !searchQuery">
        <div class="flex items-center gap-2 mb-2.5">
          <div class="inline-flex items-center gap-1.5 text-[10px] font-semibold px-2.5 py-1 rounded-full bg-muted text-muted-foreground">
            <span class="icon-[lucide--clock] text-[10px]" />
            最近使用
          </div>
          <div class="flex-1 h-px bg-border/60" />
        </div>
        <div class="space-y-1.5 mb-4">
          <NodePaletteItem
            v-for="item in recentNodes"
            :key="`recent-${item.type}`"
            :node-type="item.type"
            :name="item.name"
            :description="item.description"
          />
        </div>
      </div>

      <div v-for="group in filteredGroups" :key="group.name">
        <!-- Category Header -->
        <div class="flex items-center gap-2 mb-2.5">
          <div
            class="inline-flex items-center gap-1.5 text-[10px] font-semibold px-2.5 py-1 rounded-full"
            :class="getCategoryGradient(getGroupColor(group))"
          >
            <span class="size-1.5 rounded-full" :class="getCategoryDot(getGroupColor(group))" />
            {{ group.name }}
          </div>
          <div class="flex-1 h-px bg-border/60" />
        </div>

        <!-- Node Items -->
        <div class="space-y-1.5">
          <NodePaletteItem
            v-for="item in group.items"
            :key="item.type"
            :node-type="item.type"
            :name="item.name"
            :description="item.description"
          />
        </div>
      </div>
    </div>

    <!-- Footer hint -->
    <div class="p-3 border-t border-border/30">
      <div class="flex items-center justify-center gap-2 text-[10px] text-muted-foreground">
        <span class="icon-[lucide--grip-vertical]" />
        <span>拖拽手柄添加节点</span>
      </div>
    </div>
  </div>
</template>
