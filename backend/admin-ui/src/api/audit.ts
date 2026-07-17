import client from './client'
import type { Dayjs } from 'dayjs'

export interface AuditLog {
  id: number
  actor_user_id: number
  actor_username: string
  action: string
  target_type: string | null
  target_id: string | null
  target_snapshot: string | null
  ip: string | null
  user_agent: string | null
  created_at: string
}

export interface AuditFilter {
  actor_user_id?: number
  action?: string
  target_type?: string
  since?: Dayjs
  until?: Dayjs
  limit?: number
  offset?: number
}

export const auditApi = {
  async list(filter: AuditFilter = {}): Promise<AuditLog[]> {
    const params: Record<string, unknown> = {
      limit: filter.limit ?? 100,
      offset: filter.offset ?? 0,
    }
    if (filter.actor_user_id != null) params.actor_user_id = filter.actor_user_id
    if (filter.action) params.action = filter.action
    if (filter.target_type) params.target_type = filter.target_type
    if (filter.since) params.since = filter.since.toISOString()
    if (filter.until) params.until = filter.until.toISOString()
    const r = await client.get('/admin/audit-logs', { params })
    return r.data
  },
}
