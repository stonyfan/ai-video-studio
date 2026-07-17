/**
 * 任务列表
 *
 * 数据来源：worker.listJobs() 扫描 %APPDATA%/ai-video-studio/jobs/ 下的任务目录
 * 每个任务卡片显示：job_id + 状态徽章 + 创建时间 + 视频路径 + 操作
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Table, Tag, Button, Space, Empty, Tooltip, App, Typography } from 'antd'
import { ReloadOutlined, FolderOpenOutlined, PlusOutlined, PlayCircleOutlined, RedoOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'

import { workerApi } from '../api/client'
import type { JobSummary } from '../../electron/types'

const { Title, Text } = Typography

const STATUS_COLORS: Record<string, string> = {
  created: 'blue',
  preprocessed: 'cyan',
  triplets_ready: 'geekblue',
  analyzed: 'gold',
  planned: 'orange',
  completed: 'green',
  failed: 'red',
  unknown: 'default'
}

const STATUS_LABELS: Record<string, string> = {
  created: '已创建',
  preprocessed: '已预处理',
  triplets_ready: '三联图就绪',
  analyzed: '已分析',
  planned: '已编排',
  completed: '已完成',
  failed: '失败',
  unknown: '未知'
}

export default function Dashboard() {
  const nav = useNavigate()
  const { message } = App.useApp()
  const [jobs, setJobs] = useState<JobSummary[]>([])
  const [loading, setLoading] = useState(false)

  const refresh = async () => {
    setLoading(true)
    try {
      const list = await workerApi.listJobs() as JobSummary[]
      setJobs(list)
    } catch (e) {
      message.error(`加载失败: ${(e as Error).message}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { refresh() }, [])

  const openFolder = async (jobId: string) => {
    const ok = await workerApi.openFolder(jobId)
    if (!ok) message.warning('任务目录不存在')
  }

  const resume = async (jobId: string) => {
    const result = await workerApi.resumeJob(jobId) as
      { ok: true; handle: { jobId: string; pid: number } } |
      { ok: false; error: string }
    if (!result.ok) {
      message.error(`续跑失败: ${result.error}`)
      return
    }
    message.success(`已开始续跑: ${result.handle.jobId}`)
    nav(`/jobs/${result.handle.jobId}`)
  }

  const columns: ColumnsType<JobSummary> = [
    {
      title: '任务 ID',
      dataIndex: 'job_id',
      key: 'job_id',
      render: (id: string) => <Text code copyable>{id}</Text>
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (s: string) => (
        <Tag color={STATUS_COLORS[s] || 'default'}>
          {STATUS_LABELS[s] || s}
        </Tag>
      )
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at'
    },
    {
      title: '耗时',
      dataIndex: 'duration_sec',
      key: 'duration_sec',
      render: (d: number | null) => d ? `${d.toFixed(0)}s` : '-'
    },
    {
      title: '操作',
      key: 'actions',
      render: (_, r) => (
        <Space>
          {(r.status === 'completed' || r.status === 'failed') && (
            <Button size="small" onClick={() => nav(`/jobs/${r.job_id}`)}>
              查看详情
            </Button>
          )}
          {r.status !== 'completed' && (
            <Tooltip title="用同样的 job_id 续跑，已完成的步骤会跳过">
              <Button size="small" type="primary" ghost icon={<RedoOutlined />}
                      onClick={() => resume(r.job_id)}>
                续跑
              </Button>
            </Tooltip>
          )}
          <Tooltip title="打开任务目录">
            <Button size="small" icon={<FolderOpenOutlined />}
                    onClick={() => openFolder(r.job_id)} />
          </Tooltip>
        </Space>
      )
    }
  ]

  return (
    <Card
      title={
        <Space>
          <Title level={4} style={{ margin: 0 }}>任务列表</Title>
          <Text type="secondary">共 {jobs.length} 个</Text>
        </Space>
      }
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={refresh} loading={loading}>
            刷新
          </Button>
          <Button type="primary" icon={<PlusOutlined />}
                  onClick={() => nav('/jobs/new')}>
            新建任务
          </Button>
        </Space>
      }
    >
      {jobs.length === 0 ? (
        <Empty
          description="还没有任务"
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        >
          <Button type="primary" icon={<PlayCircleOutlined />}
                  onClick={() => nav('/jobs/new')}>
            开始第一个任务
          </Button>
        </Empty>
      ) : (
        <Table
          columns={columns}
          dataSource={jobs}
          rowKey="job_id"
          pagination={{ pageSize: 20 }}
          loading={loading}
        />
      )}
    </Card>
  )
}
