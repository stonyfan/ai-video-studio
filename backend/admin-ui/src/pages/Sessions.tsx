import { useEffect, useState, useCallback } from 'react'
import {
  Table, Button, Space, Tag, Popconfirm, App, Card, Typography, Select, Switch, Form,
} from 'antd'
import { ReloadOutlined, StopOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'

import { sessionsApi, type Session } from '../api/sessions'
import { usersApi, type UserListResponse } from '../api/users'

const { Text, Paragraph } = Typography

interface Filter {
  user_id?: number
  active_only: boolean
}

function fmtRelative(iso: string): string {
  const d = dayjs(iso)
  const diffSec = dayjs().diff(d, 'second')
  if (diffSec < 60) return `${diffSec}s 前`
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m 前`
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h 前`
  return d.format('MM-DD HH:mm')
}

function fmtUa(ua: string | null): string {
  if (!ua) return '-'
  if (ua.length <= 60) return ua
  return ua.slice(0, 57) + '…'
}

export default function Sessions() {
  const { message } = App.useApp()
  const [data, setData] = useState<Session[]>([])
  const [users, setUsers] = useState<UserListResponse[]>([])
  const [loading, setLoading] = useState(false)
  const [filter, setFilter] = useState<Filter>({ active_only: true })

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const [list, userList] = await Promise.all([
        sessionsApi.list({ ...filter, limit: 200 }),
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

  const onRevoke = async (s: Session) => {
    try {
      await sessionsApi.revoke(s.id)
      message.success(`已吊销 ${s.username || `user#${s.user_id}`} 的 session`)
      refresh()
    } catch (e) {
      message.error(`操作失败: ${(e as Error).message}`)
    }
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 70 },
    { title: '用户', dataIndex: 'username', width: 120,
      render: (v: string | null, r: Session) => v || `user#${r.user_id}` },
    {
      title: '状态', width: 90,
      render: (_: unknown, s: Session) =>
        s.revoked_at
          ? <Tag>已吊销</Tag>
          : <Tag color="green">活跃</Tag>,
    },
    {
      title: 'IP', dataIndex: 'ip', width: 130,
      render: (v: string | null) => v || '-',
    },
    {
      title: '设备指纹', dataIndex: 'device_fp', width: 130,
      render: (v: string | null) =>
        v ? <Text code style={{ fontSize: 12 }}>{v.slice(0, 8)}…</Text> : '-',
    },
    {
      title: 'UA', dataIndex: 'user_agent',
      render: (v: string | null) => <Text type="secondary" style={{ fontSize: 12 }}>{fmtUa(v)}</Text>,
    },
    {
      title: '创建', dataIndex: 'created_at', width: 130,
      render: (v: string) => <Text type="secondary">{fmtRelative(v)}</Text>,
    },
    {
      title: '最近心跳', dataIndex: 'last_heartbeat_at', width: 130,
      render: (v: string) => <Text type="secondary">{fmtRelative(v)}</Text>,
    },
    {
      title: '操作', width: 110,
      render: (_: unknown, s: Session) => (
        s.revoked_at ? <Text type="secondary">-</Text> : (
          <Popconfirm
            title="吊销此 session?"
            description="用户下次请求将被踢下线"
            okText="吊销"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            onConfirm={() => onRevoke(s)}
          >
            <Button size="small" danger icon={<StopOutlined />}>吊销</Button>
          </Popconfirm>
        )
      ),
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between' }}>
        <Typography.Title level={4} style={{ margin: 0 }}>Sessions</Typography.Title>
        <Button icon={<ReloadOutlined />} onClick={refresh} loading={loading}>刷新</Button>
      </div>

      <Card style={{ marginBottom: 16 }}>
        <Form layout="inline">
          <Form.Item label="用户">
            <Select
              allowClear
              style={{ width: 220 }}
              placeholder="全部用户"
              value={filter.user_id}
              onChange={(v) => setFilter(f => ({ ...f, user_id: v }))}
              options={users.map(u => ({ value: u.id, label: `${u.username} (#${u.id})` }))}
              showSearch
              optionFilterProp="label"
            />
          </Form.Item>
          <Form.Item label="仅活跃">
            <Switch
              checked={filter.active_only}
              onChange={(v) => setFilter(f => ({ ...f, active_only: v }))}
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
            expandedRowRender: (s: Session) => (
              <Space direction="vertical" size={2} style={{ width: '100%' }}>
                <Text type="secondary">Token hash：</Text>
                <Paragraph code copyable style={{ margin: 0, wordBreak: 'break-all' }}>{s.token_hash}</Paragraph>
                {s.device_fp && (<>
                  <Text type="secondary">完整设备指纹：</Text>
                  <Text code style={{ wordBreak: 'break-all' }}>{s.device_fp}</Text>
                </>)}
                {s.user_agent && (<>
                  <Text type="secondary">完整 UA：</Text>
                  <Text style={{ wordBreak: 'break-all' }}>{s.user_agent}</Text>
                </>)}
                {s.revoked_at && <Text type="danger">吊销于：{dayjs(s.revoked_at).format('YYYY-MM-DD HH:mm:ss')}</Text>}
              </Space>
            ),
          }}
        />
      </Card>
    </div>
  )
}
