import client from './client'
import type { User } from './auth'

export interface UserListResponse {
  id: number
  username: string
  role: 'user' | 'admin'
  phone: string | null
  email: string | null
  display_name: string | null
  license_expires_at: string | null
  is_active: boolean
  prompt_set_id: number | null
  prompt_set_option_ids: number[]
  created_at: string
}

export interface UserCreatePayload {
  username: string
  password: string
  role?: 'user' | 'admin'
  license_expires_at?: string | null
  phone?: string
  email?: string
  display_name?: string
}

export interface UserUpdatePayload {
  password?: string
  license_expires_at?: string | null
  is_active?: boolean
  phone?: string
  email?: string
  display_name?: string
  // null = 解绑走默认；不传 = 不改
  prompt_set_id?: number | null
  // Phase 12: 不传=不改；[] = 清空；[1,2,3] = 设为这三套
  prompt_set_option_ids?: number[] | null
}

export const usersApi = {
  async list(limit = 100, offset = 0): Promise<UserListResponse[]> {
    const r = await client.get('/admin/users', { params: { limit, offset } })
    return r.data
  },

  async create(payload: UserCreatePayload): Promise<User> {
    const r = await client.post('/admin/users', payload)
    return r.data
  },

  async update(userId: number, payload: UserUpdatePayload): Promise<User> {
    const r = await client.patch(`/admin/users/${userId}`, payload)
    return r.data
  },

  async delete(userId: number): Promise<void> {
    await client.delete(`/admin/users/${userId}`)
  },

  async resetPassword(userId: number, newPassword: string): Promise<User> {
    const r = await client.post(`/admin/users/${userId}/reset_password`, {
      new_password: newPassword,
    })
    return r.data
  },
}
