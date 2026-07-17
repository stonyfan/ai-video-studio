import client from './client'
import type { Dayjs } from 'dayjs'

export interface ModelUsage {
  id: number
  user_id: number
  username: string | null
  provider: string
  model: string
  input_tokens: number
  output_tokens: number
  estimated_cost_cny: number
  status: 'success' | 'error' | 'rate_limited'
  error_message: string | null
  latency_ms: number | null
  created_at: string
}

export interface ModelUsageSummary {
  window: string
  total_requests: number
  total_input_tokens: number
  total_output_tokens: number
  total_cost_cny: number
  error_count: number
  rate_limited_count: number
  by_provider: {
    provider: string
    requests: number
    input_tokens: number
    output_tokens: number
    estimated_cost_cny: number
    errors: number
  }[]
}

export interface UsageFilter {
  user_id?: number
  provider?: string
  status?: string
  since?: Dayjs
  until?: Dayjs
  limit?: number
  offset?: number
}

export const modelUsageApi = {
  async list(filter: UsageFilter = {}): Promise<ModelUsage[]> {
    const params: Record<string, unknown> = {
      limit: filter.limit ?? 100,
      offset: filter.offset ?? 0,
    }
    if (filter.user_id != null) params.user_id = filter.user_id
    if (filter.provider) params.provider = filter.provider
    if (filter.status) params.status = filter.status
    if (filter.since) params.since = filter.since.toISOString()
    if (filter.until) params.until = filter.until.toISOString()
    const r = await client.get('/admin/model-usage', { params })
    return r.data
  },

  async summary(window: 'today' | '7d' | '30d' | 'all' = 'today'): Promise<ModelUsageSummary> {
    const r = await client.get('/admin/model-usage/summary', { params: { window } })
    return r.data
  },
}
