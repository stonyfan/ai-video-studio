import { useEffect, useState } from 'react'
import { Card, Col, Row, Statistic, Table, Tag, Typography, App, Button, Space } from 'antd'
import {
  UserOutlined, UsergroupDeleteOutlined, RocketOutlined,
  ThunderboltOutlined, AuditOutlined, ReloadOutlined, BarChartOutlined,
  DatabaseOutlined, CloudDownloadOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'

import { statsApi, type Stats } from '../api/stats'
import { auditApi, type AuditLog } from '../api/audit'
import { modelUsageApi, type ModelUsageSummary } from '../api/modelUsage'

const { Text, Title } = Typography

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

export default function Dashboard() {
  const { message } = App.useApp()
  const nav = useNavigate()
  const [stats, setStats] = useState<Stats | null>(null)
  const [recent, setRecent] = useState<AuditLog[]>([])
  const [usage, setUsage] = useState<ModelUsageSummary | null>(null)
  const [loading, setLoading] = useState(false)

  const refresh = async () => {
    setLoading(true)
    try {
      const [s, r, u] = await Promise.all([
        statsApi.get(),
        auditApi.list({ limit: 10 }),
        modelUsageApi.summary('today'),
      ])
      setStats(s)
      setRecent(r)
      setUsage(u)
    } catch (e) {
      message.error(`加载失败: ${(e as Error).message}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
  }, [])

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Title level={4} style={{ margin: 0 }}>Dashboard</Title>
        <Button icon={<ReloadOutlined />} onClick={refresh} loading={loading}>刷新</Button>
      </div>

      <Row gutter={[16, 16]}>
        <Col xs={12} sm={12} md={6}>
          <Card>
            <Statistic
              title="总用户数"
              value={stats?.users_total ?? '-'}
              prefix={<UserOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={12} md={6}>
          <Card>
            <Statistic
              title="启用用户"
              value={stats?.users_active ?? '-'}
              prefix={<UsergroupDeleteOutlined />}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={12} md={6}>
          <Card>
            <Statistic
              title="活跃版本"
              value={stats?.releases_active ?? '-'}
              suffix={`/ ${stats?.releases_total ?? '-'}`}
              prefix={<RocketOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={12} md={6}>
          <Card>
            <Statistic
              title="活跃 Session"
              value={stats?.sessions_active ?? '-'}
              prefix={<ThunderboltOutlined />}
              valueStyle={{ color: '#1677ff' }}
            />
          </Card>
        </Col>
      </Row>

      <Card
        style={{ marginTop: 16 }}
        title={
          <Space>
            <BarChartOutlined />
            <span>今日模型用量</span>
            <Text type="secondary" style={{ fontSize: 13, fontWeight: 'normal' }}>
              {usage?.window || '今日'}
            </Text>
          </Space>
        }
        extra={<Button type="link" onClick={() => nav('/usage')}>查看详情 →</Button>}
      >
        <Row gutter={[16, 16]}>
          <Col xs={12} md={6}>
            <Statistic
              title="请求数"
              value={usage?.total_requests ?? 0}
              prefix={<ThunderboltOutlined />}
            />
          </Col>
          <Col xs={12} md={6}>
            <Statistic
              title="总 Tokens"
              value={(usage?.total_input_tokens ?? 0) + (usage?.total_output_tokens ?? 0)}
              suffix={usage ? ` (in ${usage.total_input_tokens} / out ${usage.total_output_tokens})` : ''}
            />
          </Col>
          <Col xs={12} md={6}>
            <Statistic
              title="成本(¥)"
              value={usage?.total_cost_cny ?? 0}
              precision={4}
              valueStyle={{ color: '#cf1322' }}
            />
          </Col>
          <Col xs={12} md={6}>
            <Statistic
              title="错误 / 限速"
              value={usage?.error_count ?? 0}
              suffix={`/ ${usage?.rate_limited_count ?? 0}`}
              valueStyle={{ color: (usage?.error_count || usage?.rate_limited_count) ? '#fa8c16' : undefined }}
            />
          </Col>
        </Row>
      </Card>

      <Card
        style={{ marginTop: 16 }}
        title={
          <Space>
            <DatabaseOutlined />
            <span>系统健康</span>
          </Space>
        }
      >
        <Row gutter={[16, 16]}>
          <Col xs={12} md={8}>
            <Statistic
              title="数据库大小"
              value={stats?.db_size_mb ?? 0}
              precision={2}
              suffix="MB"
              prefix={<DatabaseOutlined />}
            />
          </Col>
          <Col xs={12} md={16}>
            <Statistic
              title="最新备份"
              value={stats?.latest_backup
                ? `${stats.latest_backup.filename}（${(stats.latest_backup.size_kb / 1024).toFixed(2)} MB）`
                : '无备份'}
              prefix={<CloudDownloadOutlined />}
              valueStyle={stats?.latest_backup
                ? { fontSize: 14, color: '#52c41a' }
                : { fontSize: 14, color: '#cf1322' }}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              {stats?.latest_backup
                ? `备份时间：${dayjs(stats.latest_backup.mtime).format('YYYY-MM-DD HH:mm:ss')}`
                : 'backup 容器未启动或未生成备份'}
            </Text>
          </Col>
        </Row>
      </Card>

      <Card
        style={{ marginTop: 16 }}
        title={
          <Space>
            <AuditOutlined />
            <span>最近操作</span>
            <Text type="secondary" style={{ fontSize: 13, fontWeight: 'normal' }}>
              24h 内 {stats?.recent_audit_count ?? 0} 条
            </Text>
          </Space>
        }
        extra={<Button type="link" onClick={() => nav('/audit')}>查看全部 →</Button>}
      >
        <Table
          rowKey="id"
          size="small"
          loading={loading}
          dataSource={recent}
          pagination={false}
          columns={[
            {
              title: '时间', dataIndex: 'created_at', width: 150,
              render: (v: string) => dayjs(v).format('MM-DD HH:mm:ss'),
            },
            { title: '操作者', dataIndex: 'actor_username', width: 120 },
            {
              title: '动作', dataIndex: 'action', width: 160,
              render: (a: string) => <Tag color={ACTION_COLOR[a] || 'default'}>{a}</Tag>,
            },
            {
              title: '目标', width: 160,
              render: (_: unknown, r: AuditLog) => (
                <Text type="secondary">{r.target_type || '-'}{r.target_id ? ` #${r.target_id}` : ''}</Text>
              ),
            },
            {
              title: 'IP', dataIndex: 'ip', width: 130,
              render: (v: string | null) => v || '-',
            },
          ]}
        />
      </Card>
    </div>
  )
}
