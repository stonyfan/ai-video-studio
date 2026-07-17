import client from './client'

export interface Session {
  id: number
  user_id: number
  username: string | null
  token_hash: string
  device_fp: string | null
  ip: string | null
  user_agent: string | null
  created_at: string
  last_heartbeat_at: string
  revoked_at: string | null
}

export interface SessionFilter {
  user_id?: number
  active_only?: boolean
  limit?: number
  offset?: number
}

export const sessionsApi = {
  async list(filter: SessionFilter = {}): Promise<Session[]> {
    const params: Record<string, unknown> = {
      limit: filter.limit ?? 100,
      offset: filter.offset ?? 0,
      active_only: filter.active_only ?? true,
    }
    if (filter.user_id != null) params.user_id = filter.user_id
    const r = await client.get('/admin/sessions', { params })
    return r.data
  },

  async revoke(id: number): Promise<Session> {
    const r = await client.post(`/admin/sessions/${id}/revoke`)
    return r.data
  },
}
