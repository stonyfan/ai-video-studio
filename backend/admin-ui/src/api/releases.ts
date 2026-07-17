import client from './client'

export interface Release {
  id: number
  version: string
  download_url: string
  sha256: string
  min_supported: string
  release_notes: string | null
  is_active: boolean
  created_at: string
  rollout_percentage: number
  force_upgrade: boolean
  rolled_back_at: string | null
  grace_hours: number
  // Phase 11：counter 计数（无去重）
  download_count: number
  upgrade_success_count: number
}

export interface ReleaseCreatePayload {
  version: string
  download_url: string
  sha256: string
  min_supported: string
  release_notes?: string
  is_active?: boolean
  rollout_percentage?: number
  force_upgrade?: boolean
  grace_hours?: number
}

export interface ReleaseUpdatePayload {
  is_active?: boolean
  release_notes?: string
  rollout_percentage?: number
  force_upgrade?: boolean
  grace_hours?: number
}

export const releasesApi = {
  async list(limit = 100, offset = 0): Promise<Release[]> {
    const r = await client.get('/admin/releases', { params: { limit, offset } })
    return r.data
  },

  async create(payload: ReleaseCreatePayload): Promise<Release> {
    const r = await client.post('/admin/releases', payload)
    return r.data
  },

  async update(id: number, payload: ReleaseUpdatePayload): Promise<Release> {
    const r = await client.patch(`/admin/releases/${id}`, payload)
    return r.data
  },

  async rollback(id: number): Promise<Release> {
    const r = await client.post(`/admin/releases/${id}/rollback`)
    return r.data
  },
}
