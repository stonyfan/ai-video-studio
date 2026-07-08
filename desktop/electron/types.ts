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
  provider_keys: {
    'qwen-vl'?: { key: string; model?: string }
    doubao?: { key: string; model?: string }
  }
}

export type Platform = 'douyin' | 'xhs' | 'videohao' | 'general'
export type Style = 'fast_cut' | 'ambiance' | 'narrative'
export type Provider = 'qwen-vl' | 'doubao'

export interface JobOptions {
  input: string
  platform: Platform
  style: Style
  duration: number
  bgm?: string
  provider: Provider
  skip_vision?: boolean
  skip_render?: boolean
  job_id?: string
}

export interface JobProgress {
  job_id: string
  status: string
  timestamp: string
  history: Array<{ status: string; ts: string }>
  error?: { code: string; message: string }
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

export type IPCChannel =
  | 'auth:login'
  | 'auth:logout'
  | 'auth:getCurrentUser'
  | 'config:getAll'
  | 'config:setBackendUrl'
  | 'config:setProviderKey'
  | 'worker:startJob'
  | 'worker:cancel'
  | 'worker:listJobs'
  | 'worker:openFolder'
  | 'dialog:chooseFolder'
  | 'app:getVersion'
  | 'app:getBackendUrl'

/** 主 → 渲染 的事件 */
export type IPCEvent =
  | 'job:progress'
  | 'job:log'
  | 'job:done'
  | 'job:failed'
  | 'auth:session-invalid'
  | 'auth:license-expired'
