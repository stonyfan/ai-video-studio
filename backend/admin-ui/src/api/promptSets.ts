import client from './client'
import * as yaml from 'js-yaml'

export interface PromptSetSummary {
  id: number
  name: string
  description: string | null
  version: number
  is_default: boolean
  is_active: boolean
  bound_user_count: number
  updated_at: string
}

export interface PromptSetOut {
  id: number
  name: string
  description: string | null
  content_yaml: string
  version: number
  is_default: boolean
  is_active: boolean
  deleted_at: string | null
  created_at: string
  updated_at: string
}

export interface PromptSetCreatePayload {
  name: string
  description?: string | null
  content_yaml: string
  is_default?: boolean
  is_active?: boolean
}

export interface PromptSetUpdatePayload {
  name?: string
  description?: string | null
  content_yaml?: string
  is_default?: boolean
  is_active?: boolean
  expected_version?: number
}

/** 客户端 YAML 校验：与后端 _validate_yaml 同步
 *  - 能 safe_load
 *  - 顶层是 dict
 *  - templates.triplet_detect.default 存在且非空
 */
export function validatePromptYaml(content: string | null | undefined): string | null {
  if (!content || !content.trim()) return 'YAML 不能为空'
  let data: unknown
  try {
    data = yaml.load(content)
  } catch (e) {
    return `YAML 解析失败：${(e as Error).message}`
  }
  if (!data || typeof data !== 'object') return 'YAML 顶层必须是 mapping'
  const root = data as Record<string, unknown>
  const templates = root.templates
  if (!templates || typeof templates !== 'object') return '缺少 templates 段'
  const triplet = (templates as Record<string, unknown>).triplet_detect
  if (!triplet || typeof triplet !== 'object') return '缺少 templates.triplet_detect 段'
  const def = (triplet as Record<string, unknown>).default
  if (typeof def !== 'string' || !def.trim()) {
    return 'templates.triplet_detect.default 不能为空'
  }
  return null
}

export const promptSetsApi = {
  async list(includeDeleted = false): Promise<PromptSetSummary[]> {
    const r = await client.get('/admin/prompt-sets', { params: { include_deleted: includeDeleted } })
    return r.data
  },

  async get(id: number): Promise<PromptSetOut> {
    const r = await client.get(`/admin/prompt-sets/${id}`)
    return r.data
  },

  async create(payload: PromptSetCreatePayload): Promise<PromptSetOut> {
    const r = await client.post('/admin/prompt-sets', payload)
    return r.data
  },

  async update(id: number, payload: PromptSetUpdatePayload): Promise<PromptSetOut> {
    const r = await client.patch(`/admin/prompt-sets/${id}`, payload)
    return r.data
  },

  async delete(id: number): Promise<void> {
    await client.delete(`/admin/prompt-sets/${id}`)
  },

  async duplicate(id: number): Promise<PromptSetOut> {
    const r = await client.post(`/admin/prompt-sets/${id}/duplicate`)
    return r.data
  },
}
