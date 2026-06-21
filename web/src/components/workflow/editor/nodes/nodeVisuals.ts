/**
 * 节点视觉配置 — 图标和颜色的唯一数据源
 *
 * 侧边栏节点库和画布节点都从这里读取，确保一致。
 */
import type { Component } from 'vue'
import {
  Bot,
  Briefcase,
  CheckCircle,
  Clock,
  CloudUpload,
  Combine,
  FileCode,
  FileText,
  FolderSearch,
  GitBranch,
  GitFork,
  GitMerge,
  GitPullRequest,
  Globe,
  Hourglass,
  MessageSquare,
  MessagesSquare,
  Play,
  Repeat,
  SearchCode,
  Send,
  Sparkles,
  Terminal,
  UserPlus,
  Users,
  Variable,
  Webhook,
  Zap,
} from 'lucide-vue-next'

export type NodeColorKey = 'blue' | 'green' | 'purple' | 'orange'

interface NodeVisual {
  icon: Component
  color: NodeColorKey
}

const NODE_VISUALS: Record<string, NodeVisual> = {
  // 触发器 (blue)
  manual_trigger: { icon: Play, color: 'blue' },
  webhook_trigger: { icon: Webhook, color: 'blue' },
  feishu_event_trigger: { icon: MessageSquare, color: 'blue' },

  // 数据获取 (orange)
  fetch_work_item: { icon: Briefcase, color: 'orange' },
  fetch_space_info: { icon: FolderSearch, color: 'orange' },
  context_retrieval: { icon: SearchCode, color: 'orange' },

  // 操作 (green)
  http_request: { icon: Globe, color: 'green' },
  wait_feishu_field: { icon: Hourglass, color: 'green' },
  code: { icon: Terminal, color: 'green' },

  // 集成 (blue)
  create_branch: { icon: GitBranch, color: 'blue' },
  create_pr: { icon: GitPullRequest, color: 'blue' },
  merge_pr: { icon: GitMerge, color: 'blue' },
  mcp_deploy: { icon: CloudUpload, color: 'blue' },

  // 群聊 (orange)
  fetch_group_chat: { icon: MessageSquare, color: 'orange' },
  create_group_chat: { icon: Users, color: 'orange' },
  create_work_item_chat: { icon: MessagesSquare, color: 'orange' },
  join_group_chat: { icon: UserPlus, color: 'orange' },
  group_chat_question: { icon: MessageSquare, color: 'orange' },

  // 通知 (orange)
  notify_feishu: { icon: Send, color: 'orange' },
  notify_feishu_im: { icon: Send, color: 'orange' },
  feishu_doc_create: { icon: FileText, color: 'orange' },

  // AI (purple)
  ai_prompt: { icon: Sparkles, color: 'purple' },
  ai_coding_dispatcher: { icon: Bot, color: 'purple' },
  ai_variable_extractor: { icon: Variable, color: 'purple' },
  variable_extractor: { icon: Variable, color: 'purple' },
  ai_plan_generation: { icon: FileCode, color: 'purple' },
  ai_coding: { icon: Terminal, color: 'purple' },

  // 控制流 (purple)
  condition: { icon: GitBranch, color: 'purple' },
  human_approval: { icon: CheckCircle, color: 'purple' },
  delay: { icon: Clock, color: 'purple' },
  parallel: { icon: GitFork, color: 'purple' },
  join: { icon: GitMerge, color: 'purple' },
  foreach: { icon: Repeat, color: 'purple' },
  aggregate: { icon: Combine, color: 'purple' },
}

const FALLBACK: NodeVisual = { icon: Zap, color: 'blue' }

export function getNodeVisual(nodeType: string): NodeVisual {
  return NODE_VISUALS[nodeType] ?? FALLBACK
}

/** 所有已注册的节点类型键（用于生成 Vue Flow nodeTypes） */
export const allNodeTypeKeys = Object.keys(NODE_VISUALS)
