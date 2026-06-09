/**
 * 首启向导供应商预设（Phase 3 PROV-02/03，多模型版）。
 *
 * 这里是一份「可直接更新 GitHub 即可新增供应商」的预设清单：
 * 每个供应商以 Anthropic 兼容端点接入（Claude Code 必备 anthropic 类型凭证），
 * provider_type 恒为 'anthropic'，靠 base_url 覆盖 + 指定 model 区分供应商。
 *
 * 选中预设后自动填充 baseUrl，并把该供应商的预设模型加载为可选模型列表；
 * 用户仍可点「获取模型列表」从供应商 /models 端点实时拉取（与系统设置里新建
 * Provider 的获取逻辑一致），或手动增删模型。contextLength / supportsVision
 * 仅用于在向导中展示模型能力，辅助选择，最终以供应商实际返回为准。
 *
 * 新增供应商：在 PROVIDER_PRESETS 里追加一项即可，无需改组件代码。
 */

/** 预设模型（单个）。 */
export interface PresetModel {
  /** 模型 id（提交给后端、传给 Claude Code 的实际模型名）。 */
  id: string
  /** 上下文长度（token），用于能力展示；未知为 null。 */
  contextLength: number | null
  /** 是否支持图像/多模态输入。 */
  supportsVision: boolean
}

export interface ProviderPreset {
  /** 预设唯一 id（即供应商标识，如 deepseek / kimi）。 */
  id: string
  /** 供应商展示名（如 DeepSeek，而非具体模型名）。 */
  label: string
  /** Anthropic 兼容端点 base_url（custom 预设为空，需用户填写）。 */
  baseUrl: string
  /** 预设模型清单（custom 为空，需用户获取或手填）。 */
  models: PresetModel[]
  /** 简短描述（i18n 兜底用中文常量，组件优先取 i18n）。 */
  description: string
  /** 获取 API Key 的官方页面（引导用户去哪拿密钥）。 */
  apiKeyUrl?: string
  /** 是否为「自定义兼容端点」预设（baseUrl/model 需用户自填）。 */
  custom?: boolean
}

export const PROVIDER_PRESETS: ProviderPreset[] = [
  {
    id: 'deepseek',
    label: 'DeepSeek',
    baseUrl: 'https://api.deepseek.com/anthropic',
    models: [
      { id: 'deepseek-v4-pro', contextLength: 1_000_000, supportsVision: false },
      { id: 'deepseek-v4-flash', contextLength: 1_000_000, supportsVision: false },
    ],
    description: 'DeepSeek 官方 Anthropic 兼容端点，超长上下文、性价比高',
    apiKeyUrl: 'https://platform.deepseek.com/api_keys',
  },
  {
    id: 'mimo',
    label: 'MiMo（小米）',
    baseUrl: 'https://api.mimo.ai/anthropic',
    models: [
      { id: 'mimo-v2.5', contextLength: 256_000, supportsVision: true },
      { id: 'mimo-v2.5-pro', contextLength: 256_000, supportsVision: true },
    ],
    description: '小米 MiMo 多模态大模型，支持图像输入',
    apiKeyUrl: 'https://xiaomimimo.com',
  },
  {
    id: 'kimi',
    label: 'Kimi（Moonshot）',
    baseUrl: 'https://api.moonshot.cn/anthropic',
    models: [
      { id: 'kimi-k2.6', contextLength: 256_000, supportsVision: true },
    ],
    description: 'Moonshot Kimi，超长上下文，支持图像',
    apiKeyUrl: 'https://platform.moonshot.cn/console/api-keys',
  },
  {
    id: 'anthropic',
    label: 'Anthropic 官方',
    baseUrl: 'https://api.anthropic.com',
    models: [
      { id: 'claude-sonnet-4-5', contextLength: 200_000, supportsVision: true },
    ],
    description: 'Anthropic 官方 Claude，能力最完整',
    apiKeyUrl: 'https://console.anthropic.com/settings/keys',
  },
  {
    id: 'custom',
    label: '自定义兼容端点',
    baseUrl: '',
    models: [],
    description: '填写任意 Anthropic 兼容端点的 Base URL，再获取或手填模型',
    custom: true,
  },
]

/** 默认选中的预设（首个非自定义）。 */
export const DEFAULT_PRESET: ProviderPreset
  = PROVIDER_PRESETS.find(p => !p.custom) ?? PROVIDER_PRESETS[0]
