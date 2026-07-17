import client from './client'

export type ProviderName = 'qwen-vl' | 'glm' | 'doubao'

export interface ProviderKey {
  id: number
  provider: ProviderName
  name: string
  api_key_masked: string
  base_url: string | null
  is_active: boolean
  last_used_at: string | null
  created_at: string
  updated_at: string
}

export interface ProviderKeyCreatePayload {
  provider: ProviderName
  name: string
  api_key: string
  base_url?: string
  is_active?: boolean
}

export interface ProviderKeyUpdatePayload {
  name?: string
  base_url?: string
  is_active?: boolean
}

export interface ProviderKeyTestResult {
  ok: boolean
  status_code: number | null
  message: string
  latency_ms: number | null
}

export const providerKeysApi = {
  async list(provider?: ProviderName): Promise<ProviderKey[]> {
    const params: Record<string, unknown> = {}
    if (provider) params.provider = provider
    const r = await client.get('/admin/provider-keys', { params })
    return r.data
  },

  async create(payload: ProviderKeyCreatePayload): Promise<ProviderKey> {
    const r = await client.post('/admin/provider-keys', payload)
    return r.data
  },

  async update(id: number, payload: ProviderKeyUpdatePayload): Promise<ProviderKey> {
    const r = await client.patch(`/admin/provider-keys/${id}`, payload)
    return r.data
  },

  async delete(id: number): Promise<void> {
    await client.delete(`/admin/provider-keys/${id}`)
  },

  async test(id: number): Promise<ProviderKeyTestResult> {
    const r = await client.post(`/admin/provider-keys/${id}/test`)
    return r.data
  },
}
