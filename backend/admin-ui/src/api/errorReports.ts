import client from './client'

export type ErrorReportStatus = 'open' | 'resolved' | 'ignored'

export interface ErrorReport {
  id: number
  user_id: number
  username: string | null
  job_id: string | null
  message: string
  file_size: number
  client_version: string | null
  client_platform: string | null
  status: ErrorReportStatus
  admin_note: string | null
  created_at: string
}

export interface ErrorReportListParams {
  user_id?: number
  status?: ErrorReportStatus
  since?: string
  until?: string
  limit?: number
  offset?: number
}

export interface ErrorReportUpdatePayload {
  status?: ErrorReportStatus
  admin_note?: string
}

/** 下载链接（带 Authorization 需要用同 axios 实例拉 blob，不能直接给 a href） */
export async function downloadReport(id: number): Promise<{ blob: Blob; filename: string }> {
  const r = await client.get(`/admin/error-reports/${id}/download`, { responseType: 'blob' })
  // 从 content-disposition 取 filename，否则兜底
  const cd = r.headers['content-disposition'] || ''
  const m = /filename="?([^";]+)"?/.exec(cd)
  const filename = m ? m[1] : `error_report_${id}.zip`
  return { blob: r.data, filename }
}

export const errorReportsApi = {
  async list(params: ErrorReportListParams = {}): Promise<ErrorReport[]> {
    const r = await client.get('/admin/error-reports', { params })
    return r.data
  },

  async update(id: number, payload: ErrorReportUpdatePayload): Promise<ErrorReport> {
    const r = await client.patch(`/admin/error-reports/${id}`, payload)
    return r.data
  },

  download: downloadReport,
}
