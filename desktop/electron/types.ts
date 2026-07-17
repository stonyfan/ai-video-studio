/**
 * 主进程/渲染进程共享类型
 * preload 通过 contextBridge 暴露这些类型给 renderer
 */

export interface User {
  id: number
  username: string
  role: 'user' | 'admin'
  license_expires_at: string | null
  is_active: boolean
}

export interface LoginResponse {
  access_token: string
  refresh_token: string
  expires_in: number
  token_type: string
  user: User
}

export interface AppConfig {
  backend_url: string
  device_fp: string
  session_token: string | null
  refresh_token: string | null
  user: User | null
  /**
   * Phase 7：模型调用模式
   * - A: 直连（用户自带 API key，开发/自部署用）
   * - C: 云端代理（key 在后端，商业部署用）
   */
  model_mode: 'A' | 'C'
  provider_keys: {
    'qwen-vl'?: { key: string; model?: string }
    doubao?: { key: string; model?: string }
    'doubao-agent-plan'?: { key: string; model?: string }
    glm?: { key: string; model?: string }
  }
  /** Phase 5：已下载的安装包缓存（grace 期判断用） */
  update_cache?: {
    version: string
    installer_path: string
    downloaded_at: number       // epoch ms
    sha256: string
  } | null
  /** Phase 10：从后端拉的 prompt 集缓存（worker spawn 用） */
  prompt_set_cache?: {
    id: number
    version: number
    path: string                // %APPDATA%/ai-video-studio/prompts/<id>_<version>.yaml
  } | null
  /** Phase 11：升级成功上报的 pending 标记（install() 前写，新版本启动时上报后清空） */
  pending_upgrade_report?: {
    from_version: string
    to_version: string
    timestamp: number           // epoch ms
  } | null
}

export type Platform = 'douyin' | 'xhs' | 'videohao' | 'general'
export type Style = 'fast_cut' | 'ambiance' | 'narrative'
export type Provider = 'qwen-vl' | 'doubao' | 'doubao-agent-plan' | 'glm'
export type OrchestrationMode = 'timeline' | 'llm' | 'default'

export interface JobOptions {
  input: string
  platform: Platform
  style: Style
  duration: number
  bgm?: string
  provider: Provider
  orchestration_mode?: OrchestrationMode
  skill?: string
  skip_vision?: boolean
  skip_render?: boolean
  job_id?: string
  resume?: boolean
  variants?: number
}

export interface JobProgress {
  job_id: string
  status: string
  timestamp: string
  history: Array<{ status: string; ts: string }>
  error?: { code: string; message: string }
}

export interface VariantResult {
  index: number
  style_hint: string
  storyboard: string | null
  final_video: string | null
  narrative: string | null
  error: string | null
}

export interface JobResult {
  job_id: string
  status: 'completed' | 'failed'
  final_video: string | null
  storyboard: string | null
  log: string
  cost: {
    vision_calls: number
    estimated_cost_cny: number
    duration_sec: number
  }
  error: { stage: string; code: string; message: string } | null
  started_at: string
  finished_at: string
  narrative?: string | null
  variants?: VariantResult[]
}

export interface JobHandle {
  jobId: string
  pid: number
}

export interface JobSummary {
  job_id: string
  status: string                    // 从 result.json 或 progress.json 取
  created_at: string                // 任务目录 mtime
  final_video: string | null
  error_message: string | null
  duration_sec: number | null
}

export interface PromptSetOption {
  id: number
  name: string
  description: string | null
  version: number
  is_default: boolean
  is_current: boolean
}

export type IPCChannel =
  | 'auth:login'
  | 'auth:logout'
  | 'auth:getCurrentUser'
  | 'config:getAll'
  | 'config:setBackendUrl'
  | 'config:setProviderKey'
  | 'config:setModelMode'
  | 'worker:startJob'
  | 'worker:cancel'
  | 'worker:listJobs'
  | 'worker:openFolder'
  | 'dialog:chooseFolder'
  | 'app:getVersion'
  | 'app:getBackendUrl'
  | 'error-report:submit'
  | 'prompt-set:sync'
  | 'prompt-set:getState'
  | 'prompt-set:listOptions'
  | 'prompt-set:select'

/** 主 → 渲染 的事件 */
export type IPCEvent =
  | 'job:progress'
  | 'job:log'
  | 'job:done'
  | 'job:failed'
  | 'auth:session-invalid'
  | 'auth:license-expired'
