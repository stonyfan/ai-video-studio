/**
 * Curate 业务类型 + typed API wrapper
 *
 * 类型与 electron/curate.ts 一致，前端用这个调用 window.api.curate.*
 *
 * 注意：subprocess 模式，submit 直接返 Promise<CurateResult>，无 task_id 轮询。
 * 进度通过 onLog/onProgress 事件订阅。
 */
import { curateApi } from './client'

export interface Scene {
  id: string
  source_id: string
  start: number
  end: number
  creation_time: string
  action_type: string
  main_objects: string[]
  highlight_score: number
  visual_quality: number
  motion_score: number
  preview_path: string
  preview_ready: boolean
}

export interface Stage {
  id: string
  title: string
  scene_ids: string[]
  representative: string | null
  size: number
}

export interface CurateData {
  job_id: string
  input_dir: string
  target_duration_default: number
  stages: Stage[]
  scenes_by_id: Record<string, Scene>
  previews_ready: boolean
  auto_selected_ids: string[]
}

export interface Selection {
  stage_id: string
  scene_ids: string[]
}

export interface CurateSubmitPayload {
  selections: Selection[]
  target_duration: number
  brief: string
  provider: string
  llm_model: string
}

export interface RegeneratePayload {
  instruction: string
  target_duration: number
  provider: string
  llm_model: string
}

export interface CurateResultItem {
  order: number
  id: string
  cut_duration: number
  use_start: number
  use_end: number
  reason: string
}

export interface CurateResult {
  final_video: string
  narrative: string
  items: CurateResultItem[]
  total_duration: number
}

export interface CurateLogEvent {
  jobId: string
  level: string
  msg: string
}

export interface CurateProgressEvent {
  jobId: string
  done: number
  todo: number
  stage: string
  msg: string
}

export { curateApi }
