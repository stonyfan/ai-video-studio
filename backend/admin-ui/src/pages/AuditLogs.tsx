import { useEffect, useState, useCallback } from 'react'
import {
  Table, Button, Card, Typography, App, Tag, Select, DatePicker, Space, Form,
} from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import type { Dayjs } from 'dayjs'
import dayjs from 'dayjs'

import { auditApi, type AuditLog } from '../api/audit'
import { usersApi, type UserListResponse } from '../api/users'

const { Text, Paragraph } = Typography
const { RangePicker } = DatePicker

const ACTION_OPTIONS = [
  { value: 'user.create', label: 'user.create' },
  { value: 'user.update', label: 'user.update' },
  { value: 'user.delete', label: 'user.delete' },
  { value: 'user.reset_password', label: 'user.reset_password' },
  { value: 'release.create', label: 'release.create' },
  { value: 'release.update', label: 'release.update' },
  { value: 'release.rollback', label: 'release.rollback' },
  { value: 'session.revoke', label: 'session.revoke' },
]

const TARGET_OPTIONS = [
  { value: 'user', label: 'user' },
  { value: 'release', label: 'release' },
  { value: 'session', label: 'session' },
]

const ACTION_COLOR: Record<string, string> = {
  'user.create': 'green',
  'user.update': 'blue',
  'user.delete': 'red',
  'user.reset_password': 'orange',
  'release.create': 'green',
  'release.update': 'blue',
  'release.rollback': 'red',
  'session.revoke': 'red',
}

interface Filter {
  actor_user_id?: number
  action?: string
  target_type?: string
  range?: [Dayjs, Dayjs] | null
}

function parseSnapshot(raw: string | null): any {
  if (!raw) return null
  try {
    return JSON.parse(raw)
  } catch {
    return raw
  }
}

export default function AuditLogs() {
  const { message } = App.useApp()
  const [data, setData] = useState<AuditLog[]>([])
  const [users, setUsers] = useState<UserListResponse[]>([])
  const [loading, setLoading] = useState(false)
  const [filter, setFilter] = useState<Filter>({})

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const [list, userList] = await Promise.all([
        auditApi.list({
          actor_user_id: filter.actor_user_id,
          action: filter.action,
          target_type: filter.target_type,
          since: filter.range?.[0] || undefined,
          until: filter.range?.[1] || undefined,
          limit: 200,
        }),
        usersApi.list(200),
      ])
      setData(list)
      setUsers(userList)
    } catch (e) {
      message.error(`加载失败: ${(e as Error).message}`)
    } finally {
      setLoading(false)
    }
  }, [filter])

  useEffect(() => {
    refresh()
  }, [refresh])

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 70 },
    {
      title: '时间', dataIndex: 'created_at', width: 160,
      render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm:ss'),
    },
    { title: '操作者', dataIndex: 'actor_username', width: 130 },
    {
      title: '动作', dataIndex: 'action', width: 170,
      render: (a: string) => <Tag color={ACTION_COLOR[a] || 'default'}>{a}</Tag>,
    },
    {
      title: '目标', width: 160,
      render: (_: unknown, r: AuditLog) => (
        <Text type="secondary">{r.target_type || '-'}{r.target_id ? ` #${r.target_id}` : ''}</Text>
      ),
    },
    {
      title: 'IP', dataIndex: 'ip', width: 140,
      render: (v: string | null) => v || '-',
    },
    {
      title: 'UA', dataIndex: 'user_agent',
      render: (v: string | null) => v
        ? <Text type="secondary" style={{ fontSize: 12 }}>{v.length > 60 ? v.slice(0, 57) + '…' : v}</Text>
        : '-',
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between' }}>
        <Typography.Title level={4} style={{ margin: 0 }}>审计日志</Typography.Title>
        <Button icon={<ReloadOutlined />} onClick={refresh} loading={loading}>刷新</Button>
      </div>

      <Card style={{ marginBottom: 16 }}>
        <Form layout="inline">
          <Form.Item label="操作者">
            <Select
              allowClear
              style={{ width: 200 }}
              placeholder="全部"
              value={filter.actor_user_id}
              onChange={(v) => setFilter(f => ({ ...f, actor_user_id: v }))}
              options={users.map(u => ({ value: u.id, label: `${u.username} (#${u.id})` }))}
              showSearch
              optionFilterProp="label"
            />
          </Form.Item>
          <Form.Item label="动作">
            <Select
              allowClear
              style={{ width: 180 }}
              placeholder="全部"
              value={filter.action}
              onChange={(v) => setFilter(f => ({ ...f, action: v }))}
              options={ACTION_OPTIONS}
            />
          </Form.Item>
          <Form.Item label="目标类型">
            <Select
              allowClear
              style={{ width: 130 }}
              placeholder="全部"
              value={filter.target_type}
              onChange={(v) => setFilter(f => ({ ...f, target_type: v }))}
              options={TARGET_OPTIONS}
            />
          </Form.Item>
          <Form.Item label="时间">
            <RangePicker
              showTime
              value={filter.range as any}
              onChange={(range) => setFilter(f => ({
                ...f,
                range: (range as [Dayjs, Dayjs] | null) || null,
              }))}
            />
          </Form.Item>
        </Form>
      </Card>

      <Card>
        <Table
          rowKey="id"
          columns={columns as any}
          dataSource={data}
          loading={loading}
          pagination={{ pageSize: 50, showSizeChanger: false }}
          size="middle"
          expandable={{
            expandedRowRender: (r: AuditLog) => {
              const snap = parseSnapshot(r.target_snapshot)
              return (
                <Space direction="vertical" size={4} style={{ width: '100%' }}>
                  <Text type="secondary">目标快照：</Text>
                  {snap === null ? (
                    <Text type="secondary">（无）</Text>
                  ) : typeof snap === 'string' ? (
                    <Paragraph code style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{snap}</Paragraph>
                  ) : (
                    <Paragraph code copyable style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                      {JSON.stringify(snap, null, 2)}
                    </Paragraph>
                  )}
                  {r.user_agent && (
                    <Text type="secondary" style={{ wordBreak: 'break-all' }}>UA: {r.user_agent}</Text>
                  )}
                </Space>
              )
            },
          }}
        />
      </Card>
    </div>
  )
}
