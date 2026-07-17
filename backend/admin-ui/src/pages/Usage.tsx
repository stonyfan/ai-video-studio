import { useEffect, useState, useCallback } from 'react'
import {
  Card, Col, Row, Statistic, Table, Tag, Typography, App, Button, Space, Select, DatePicker, Form,
} from 'antd'
import { ReloadOutlined, AlertOutlined, ThunderboltOutlined } from '@ant-design/icons'
import type { Dayjs } from 'dayjs'
import dayjs from 'dayjs'

import { modelUsageApi, type ModelUsage, type ModelUsageSummary } from '../api/modelUsage'
import { usersApi, type UserListResponse } from '../api/users'

const { Text } = Typography
const { RangePicker } = DatePicker

const PROVIDER_OPTIONS = [
  { value: 'qwen-vl', label: 'Qwen-VL' },
  { value: 'glm', label: 'GLM' },
  { value: 'doubao', label: 'Doubao' },
]
const PROVIDER_COLOR: Record<string, string> = {
  'qwen-vl': 'blue',
  'glm': 'green',
  'doubao': 'orange',
}
const STATUS_COLOR: Record<string, string> = {
  success: 'green',
  error: 'red',
  rate_limited: 'orange',
}

interface Filter {
  user_id?: number
  provider?: string
  status?: string
  range?: [Dayjs, Dayjs] | null
}

export default function Usage() {
  const { message } = App.useApp()
  const [data, setData] = useState<ModelUsage[]>([])
  const [summary, setSummary] = useState<ModelUsageSummary | null>(null)
  const [users, setUsers] = useState<UserListResponse[]>([])
  const [loading, setLoading] = useState(false)
  const [filter, setFilter] = useState<Filter>({})
  const [windowSel, setWindowSel] = useState<'today' | '7d' | '30d' | 'all'>('today')

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const [list, sum, userList] = await Promise.all([
        modelUsageApi.list({
          user_id: filter.user_id,
          provider: filter.provider,
          status: filter.status,
          since: filter.range?.[0],
          until: filter.range?.[1],
          limit: 200,
        }),
        modelUsageApi.summary(windowSel),
        usersApi.list(200),
      ])
      setData(list)
      setSummary(sum)
      setUsers(userList)
    } catch (e) {
      message.error(`加载失败: ${(e as Error).message}`)
    } finally {
      setLoading(false)
    }
  }, [filter, windowSel])

  useEffect(() => {
    refresh()
  }, [refresh])

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 70 },
    {
      title: '时间', dataIndex: 'created_at', width: 160,
      render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm:ss'),
    },
    {
      title: '用户', dataIndex: 'username', width: 130,
      render: (v: string | null, r: ModelUsage) => v || `user#${r.user_id}`,
    },
    {
      title: 'Provider', dataIndex: 'provider', width: 110,
      render: (p: string) => <Tag color={PROVIDER_COLOR[p] || 'default'}>{p}</Tag>,
    },
    { title: '模型', dataIndex: 'model', width: 180,
      render: (v: string) => <Text code style={{ fontSize: 12 }}>{v}</Text> },
    {
      title: 'Tokens', width: 130,
      render: (_: unknown, r: ModelUsage) => (
        <Text>{r.input_tokens} / {r.output_tokens}</Text>
      ),
    },
    {
      title: '成本(¥)', dataIndex: 'estimated_cost_cny', width: 100,
      render: (v: number) => v.toFixed(4),
    },
    {
      title: '状态', dataIndex: 'status', width: 110,
      render: (s: string) => <Tag color={STATUS_COLOR[s] || 'default'}>{s}</Tag>,
    },
    {
      title: '延迟', dataIndex: 'latency_ms', width: 80,
      render: (v: number | null) => v != null ? `${v}ms` : <Text type="secondary">-</Text>,
    },
    {
      title: '错误', dataIndex: 'error_message',
      render: (v: string | null) =>
        v ? <Text type="danger" style={{ fontSize: 12 }}>{v}</Text> : <Text type="secondary">-</Text>,
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between' }}>
        <Typography.Title level={4} style={{ margin: 0 }}>模型用量</Typography.Title>
        <Space>
          <Select
            value={windowSel}
            onChange={(v) => setWindowSel(v)}
            options={[
              { value: 'today', label: '今日' },
              { value: '7d', label: '近 7 天' },
              { value: '30d', label: '近 30 天' },
              { value: 'all', label: '全部' },
            ]}
            style={{ width: 120 }}
          />
          <Button icon={<ReloadOutlined />} onClick={refresh} loading={loading}>刷新</Button>
        </Space>
      </div>

      <Row gutter={[16, 16]}>
        <Col xs={12} md={6}>
          <Card>
            <Statistic
              title={`${summary?.window || '今日'} 请求数`}
              value={summary?.total_requests ?? '-'}
              prefix={<ThunderboltOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Statistic
              title="总 Tokens"
              value={(summary?.total_input_tokens ?? 0) + (summary?.total_output_tokens ?? 0)}
              suffix={summary ? ` (in ${summary.total_input_tokens} / out ${summary.total_output_tokens})` : ''}
            />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Statistic
              title="成本(¥)"
              value={summary?.total_cost_cny ?? 0}
              precision={4}
              valueStyle={{ color: '#cf1322' }}
            />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Statistic
              title="错误 / 限速"
              value={summary?.error_count ?? 0}
              suffix={`/ ${summary?.rate_limited_count ?? 0}`}
              prefix={<AlertOutlined />}
              valueStyle={{ color: (summary?.error_count || summary?.rate_limited_count) ? '#fa8c16' : undefined }}
            />
          </Card>
        </Col>
      </Row>

      {summary && summary.by_provider.length > 0 && (
        <Card style={{ marginTop: 16 }} title="按 Provider 拆分">
          <Table
            rowKey="provider"
            size="small"
            pagination={false}
            dataSource={summary.by_provider}
            columns={[
              {
                title: 'Provider', dataIndex: 'provider', width: 140,
                render: (p: string) => <Tag color={PROVIDER_COLOR[p] || 'default'}>{p}</Tag>,
              },
              { title: '请求数', dataIndex: 'requests', width: 100 },
              { title: '入 tokens', dataIndex: 'input_tokens', width: 120 },
              { title: '出 tokens', dataIndex: 'output_tokens', width: 120 },
              {
                title: '成本(¥)', dataIndex: 'estimated_cost_cny', width: 120,
                render: (v: number) => v.toFixed(4),
              },
              { title: '错误数', dataIndex: 'errors' },
            ]}
          />
        </Card>
      )}

      <Card style={{ marginTop: 16, marginBottom: 16 }}>
        <Form layout="inline">
          <Form.Item label="用户">
            <Select
              allowClear
              style={{ width: 200 }}
              placeholder="全部"
              value={filter.user_id}
              onChange={(v) => setFilter(f => ({ ...f, user_id: v }))}
              options={users.map(u => ({ value: u.id, label: `${u.username} (#${u.id})` }))}
              showSearch
              optionFilterProp="label"
            />
          </Form.Item>
          <Form.Item label="Provider">
            <Select
              allowClear
              style={{ width: 140 }}
              placeholder="全部"
              value={filter.provider}
              onChange={(v) => setFilter(f => ({ ...f, provider: v }))}
              options={PROVIDER_OPTIONS}
            />
          </Form.Item>
          <Form.Item label="状态">
            <Select
              allowClear
              style={{ width: 140 }}
              placeholder="全部"
              value={filter.status}
              onChange={(v) => setFilter(f => ({ ...f, status: v }))}
              options={[
                { value: 'success', label: 'success' },
                { value: 'error', label: 'error' },
                { value: 'rate_limited', label: 'rate_limited' },
              ]}
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
        />
      </Card>
    </div>
  )
}
