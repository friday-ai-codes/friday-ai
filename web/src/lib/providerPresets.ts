/**
 * 首启向导一键模型预设（Phase 3 PROV-02/03）。
 *
 * 全部以 Anthropic 兼容端点接入（Claude Code 必备 anthropic 类型凭证）：
 * provider_type 恒为 'anthropic'，靠 base_url 覆盖 + 指定 model 区分供应商。
 * 选中预设后自动填充 baseUrl + model（仍可编辑纠错），用户仅需填 API Key。
 * contextLength / supportsVision 用于在向导中展示模型能力，辅助选择。
 */

export interface ProviderPreset {
  /** 预设唯一 id。 */
  id: string
  /** 展示名。 */
  label: string
  /** Anthropic 兼容端点 base_url（custom 预设为空，需用户填写）。 */
  baseUrl: string
  /** 默认模型 id（custom 预设为空，需用户填写）。 */
  model: string
  /** 上下文长度（token），用于能力展示；custom 为 null。 */
  contextLength: number | null
  /** 是否支持图像/多模态输入。 */
  supportsVision: boolean
  /** 简短描述（i18n 兜底用中文常量，组件优先取 i18n）。 */
  description: string
  /** 是否为「自定义兼容端点」预设（baseUrl/model 需用户自填）。 */
  custom?: boolean
}

export const PROVIDER_PRESETS: ProviderPreset[] = [
  {
    id: 'deepseek',
    label: 'DeepSeek V4 Pro',
    baseUrl: 'https://api.deepseek.com/anthropic',
    model: 'deepseek-chat',
    contextLength: 128000,
    supportsVision: false,
    description: 'DeepSeek 官方 Anthropic 兼容端点，性价比高',
  },
  {
    id: 'mimo',
    label: 'MiMo V2.5 Pro',
    baseUrl: 'https://api.mimo.ai/anthropic',
    model: 'mimo-v2.5-pro',
    contextLength: 256000,
    supportsVision: true,
    description: 'MiMo 多模态大模型，支持图像输入',
  },
  {
    id: 'kimi',
    label: 'Kimi 2.6',
    baseUrl: 'https://api.moonshot.cn/anthropic',
    model: 'kimi-k2.6',
    contextLength: 256000,
    supportsVision: true,
    description: 'Moonshot Kimi，超长上下文，支持图像',
  },
  {
    id: 'anthropic',
    label: 'Anthropic 官方',
    baseUrl: 'https://api.anthropic.com',
    model: 'claude-sonnet-4-5',
    contextLength: 200000,
    supportsVision: true,
    description: 'Anthropic 官方 Claude，能力最完整',
  },
  {
    id: 'custom',
    label: '自定义兼容端点',
    baseUrl: '',
    model: '',
    contextLength: null,
    supportsVision: false,
    description: '填写任意 Anthropic 兼容端点的 Base URL 与模型',
    custom: true,
  },
]

/** 默认选中的预设（首个非自定义）。 */
export const DEFAULT_PRESET: ProviderPreset
  = PROVIDER_PRESETS.find(p => !p.custom) ?? PROVIDER_PRESETS[0]
