/**
 * 任务详情页 — 同时处理进行中 + 已完成 + 失败
 *
 * 进行中：7 阶段 Steps + 实时日志
 * 已完成：视频预览 + 打开目录
 * 失败：错误信息 + 日志链接
 */
import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Card, Steps, Typography, Tag, Button, Space, Result, Empty,
  Alert, Progress, message, Tabs, Tooltip
} from 'antd'
import {
  CheckCircleOutlined, CloseCircleOutlined, LoadingOutlined,
  FolderOpenOutlined, ArrowLeftOutlined, ReloadOutlined,
  PlusOutlined, PlayCircleOutlined
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'

import { workerApi } from '../api/client'
import type { JobResult, JobProgress } from '../../electron/types'

const { Title, Text, Paragraph } = Typography

// 7 阶段（与 worker job.py 的 logger.info("[N/7] xxx") 对应）
const STAGES = [
  { key: 'created', title: '已创建', idx: 0 },
  { key: 'preprocessed', title: '重编码', idx: 1 },
  { key: 'triplets_ready', title: '三联图', idx: 2 },
  { key: 'analyzed', title: 'AI 分析', idx: 3 },
  { key: 'planned', title: '编排', idx: 4 },
  { key: 'rendering', title: '渲染', idx: 5 },
  { key: 'completed', title: '完成', idx: 6 }
]

interface LogLine { ts: string; line: string; level?: string }

export default function JobDetail() {
  const { jobId } = useParams<{ jobId: string }>()
  const nav = useNavigate()
  const [progress, setProgress] = useState<JobProgress | null>(null)
  const [result, setResult] = useState<JobResult | null>(null)
  const [logs, setLogs] = useState<LogLine[]>([])
  const [live, setLive] = useState(true)    // 是否还在跑
  const logRef = useRef<HTMLDivElement>(null)

  // 初始加载（处理从 Dashboard 跳到已完成任务）
  useEffect(() => {
    if (!jobId) return
    workerApi.getJobDetail(jobId).then(d => {
      if (d.progress) setProgress(d.progress)
      if (d.result) {
        setResult(d.result)
        setLive(d.result.status !== 'completed' && d.result.status !== 'failed')
      }
    })
  }, [jobId])

  // 订阅实时事件
  useEffect(() => {
    if (!jobId) return
    const offP = workerApi.onProgress(p => {
      if (p.jobId !== jobId) return
      setProgress(p.progress as JobProgress)
    })
    const offL = workerApi.onLog(p => {
      if (p.jobId !== jobId) return
      setLogs(prev => [...prev.slice(-500), {
        ts: new Date().toLocaleTimeString(),
        line: p.line,
        level: p.level
      }])
    })
    const offD = workerApi.onDone(p => {
      if (p.jobId !== jobId) return
      setResult(p.result as JobResult)
      setLive(false)
      message.success('任务完成')
    })
    const offF = workerApi.onFailed(p => {
      if (p.jobId !== jobId) return
      setResult(p.result as JobResult || null)
      setLive(false)
      message.error(`任务失败: ${p.message}`)
    })
    return () => { offP(); offL(); offD(); offF() }
  }, [jobId])

  // 自动滚到底
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [logs])

  if (!jobId) return <Empty description="无效的 job ID" />

  const cancel = async () => {
    await workerApi.cancel(jobId)
    message.info('已发送取消信号')
  }

  const openFolder = async () => {
    const ok = await workerApi.openFolder(jobId)
    if (!ok) message.warning('任务目录不存在')
  }

  // 当前阶段 idx
  const currentStageIdx = progress
    ? STAGES.find(s => s.key === progress.status)?.idx ?? 0
    : 0

  const isFailed = result?.status === 'failed' || progress?.status === 'failed'
  const isCompleted = result?.status === 'completed'

  // Steps 状态
  const stepStatus = (idx: number): 'wait' | 'process' | 'finish' | 'error' => {
    if (isFailed && idx === currentStageIdx) return 'error'
    if (idx < currentStageIdx) return 'finish'
    if (idx === currentStageIdx) return 'process'
    return 'wait'
  }

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => nav('/')}>返回</Button>
        <Text code copyable>{jobId}</Text>
        {live && <Tag icon={<LoadingOutlined />} color="processing">进行中</Tag>}
        {isCompleted && <Tag icon={<CheckCircleOutlined />} color="success">已完成</Tag>}
        {isFailed && <Tag icon={<CloseCircleOutlined />} color="error">失败</Tag>}
      </Space>

      <Card style={{ marginBottom: 16 }}>
        <Steps
          size="small"
          current={currentStageIdx}
          items={STAGES.map((s, i) => ({
            title: s.title,
            status: stepStatus(i)
          }))}
        />
      </Card>

      {result?.error && (
        <Alert
          type="error"
          message={`失败阶段: ${result.error.stage}`}
          description={result.error.message}
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}

      <Tabs
        items={[
          {
            key: 'log',
            label: '实时日志',
            children: (
              <Card size="small" bodyStyle={{ padding: 0 }}>
                <div ref={logRef} style={{
                  background: '#1e1e1e',
                  color: '#d4d4d4',
                  padding: 12,
                  height: 360,
                  overflow: 'auto',
                  fontFamily: 'Consolas, "Courier New", monospace',
                  fontSize: 12,
                  lineHeight: 1.5
                }}>
                  {logs.length === 0 ? (
                    <Text style={{ color: '#888' }}>(等待日志...)</Text>
                  ) : (
                    logs.map((l, i) => (
                      <div key={i}>
                        <span style={{ color: '#888' }}>[{l.ts}]</span>{' '}
                        <span style={{
                          color: l.level === 'warn' ? '#ffaa00' :
                                 l.level === 'error' ? '#ff5555' : '#d4d4d4'
                        }}>{l.line}</span>
                      </div>
                    ))
                  )}
                </div>
              </Card>
            )
          },
          {
            key: 'history',
            label: '状态历史',
            children: (
              <Card size="small">
                {progress?.history?.length ? (
                  <Space direction="vertical">
                    {progress.history.map((h, i) => (
                      <Text key={i}>
                        <Tag>{h.status}</Tag>
                        <Text type="secondary">{h.ts}</Text>
                      </Text>
                    ))}
                  </Space>
                ) : <Text type="secondary">无</Text>}
              </Card>
            )
          }
        ]}
      />

      {isCompleted && result?.final_video && (
        <Card title="结果" style={{ marginTop: 16 }}>
          <Space direction="vertical" style={{ width: '100%' }}>
            <video
              src={`file:///${result.final_video.replace(/\\/g, '/')}`}
              controls
              style={{ maxWidth: '100%', maxHeight: 400, background: '#000' }}
            />
            <Space>
              <Button icon={<FolderOpenOutlined />} onClick={openFolder}>打开目录</Button>
              <Button type="primary" icon={<PlusOutlined />}
                      onClick={() => nav('/jobs/new')}>新建任务</Button>
            </Space>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {result.final_video}
            </Text>
          </Space>
        </Card>
      )}

      {live && (
        <div style={{ marginTop: 16, textAlign: 'right' }}>
          <Button danger onClick={cancel}>取消任务</Button>
        </div>
      )}

      {!live && !result?.final_video && (
        <Card style={{ marginTop: 16 }}>
          <Result
            status="warning"
            title="任务未生成最终视频"
            extra={
              <Button icon={<FolderOpenOutlined />} onClick={openFolder}>
                查看任务日志
              </Button>
            }
          />
        </Card>
      )}
    </div>
  )
}
