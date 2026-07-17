import client from './client'

export interface BackupInfo {
  filename: string
  size_kb: number
  mtime: string
}

export interface Stats {
  users_total: number
  users_active: number
  releases_total: number
  releases_active: number
  sessions_active: number
  recent_audit_count: number
  db_size_mb: number
  latest_backup: BackupInfo | null
}

export const statsApi = {
  async get(): Promise<Stats> {
    const r = await client.get('/admin/stats')
    return r.data
  },
}
