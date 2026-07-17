import { useEffect, useState } from 'react'
import {
  Table, Button, Space, Tag, Modal, Form, Input, Select, Popconfirm,
  App, Card, Typography, Dropdown,
} from 'antd'
import {
  DownloadOutlined, EditOutlined, ReloadOutlined, BugOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'

import {
  errorReportsApi,
  type ErrorReport, type ErrorReportStatus,
} from '../api/errorReports'

const { Text, Paragraph } = Typography

const STATUS_COLOR: Record<ErrorReportStatus, string> = {
  open: 'red',
  resolved: 'green',
  ignored: 'default',
}

const STATUS_LABEL: Record<ErrorReportStatus, string> = {
  open: '待处理',
  resolved: '已解决',
  ignored: '已忽略',
}

interface EditForm {
  status: ErrorReportStatus
  admin_note?: string
}

export default function ErrorReports() {
  const { message } = App.useApp()
  const [data, setData] = useState<ErrorReport[]>([])
  const [loading, setLoading] = useState(false)
  const [filter, setFilter] = useState<{ status?: ErrorReportStatus; user_id?: number }>({})
  const [editTarget, setEditTarget] = useState<ErrorReport | null>(null)
  const [downloadingId, setDownloadingId] = useState<number | null>(null)
  const [editForm] = Form.useForm<EditForm>()

  const refresh = async () => {
    setLoading(true)
    try {
      const list = await errorReportsApi.list({
        status: filter.status,
        user_id: filter.user_id,
        limit: 200,
      })
      setData(list)
    } catch (e) {
      message.error(`加载失败: ${(e as Error).message}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { refresh() }, [filter.status, filter.user_id])

  const onDownload = async (r: ErrorReport) => {
    setDownloadingId(r.id)
    try {
      const { blob, filename } = await errorReportsApi.download(r.id)
      // 触发浏览器下载
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (e) {
      message.error(`下载失败: ${(e as Error).message}`)
    } finally {
      setDownloadingId(null)
    }
  }

  const onEdit = async (values: EditForm) => {
    if (!editTarget) return
    try {
      await errorReportsApi.update(editTarget.id, {
        status: values.status,
        admin_note: values.admin_note,
      })
      message.success('已更新')
      setEditTarget(null)
      refresh()
    } catch (e) {
      message.error(`更新失败: ${(e as Error).message}`)
    }
  }

  const quickUpdate = async (r: ErrorReport, status: ErrorReportStatus) => {
    try {
      await errorReportsApi.update(r.id, { status })
      message.success(`已标记为 ${STATUS_LABEL[status]}`)
      refresh()
    } catch (e) {
      message.error(`操作失败: ${(e as Error).message}`)
    }
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    {
      title: '状态', dataIndex: 'status', width: 100,
      render: (s: ErrorReportStatus) => <Tag color={STATUS_COLOR[s]}>{STATUS_LABEL[s]}</Tag>,
    },
    {
      title: '用户', dataIndex: 'username', width: 120,
      render: (v: string | null, r: ErrorReport) =>
        v ? <Text>{v} <Text type="secondary">#{r.user_id}</Text></Text>
           : <Text type="secondary">#{r.user_id}</Text>,
    },
    {
      title: '问题描述', dataIndex: 'message',
      render: (m: string) => (
        <Paragraph ellipsis={{ rows: 2, expandable: true, symbol: '展开' }} style={{ margin: 0 }}>
          {m}
        </Paragraph>
      ),
    },
    {
      title: 'Job', dataIndex: 'job_id', width: 140,
      render: (v: string | null) => v ? <Text code style={{ fontSize: 12 }}>{v}</Text>
                                          : <Text type="secondary">-</Text>,
    },
    {
      title: '客户端', width: 130,
      render: (_: unknown, r: ErrorReport) => (
        <Space direction="vertical" size={0}>
          <Text style={{ fontSize: 12 }}>{r.client_version || '-'}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>{r.client_platform || ''}</Text>
        </Space>
      ),
    },
    {
      title: '文件', dataIndex: 'file_size', width: 90,
      render: (s: number) => {
        if (!s) return <Text type="secondary">-</Text>
        const kb = s / 1024
        if (kb < 1024) return <Text>{kb.toFixed(1)} KB</Text>
        return <Text>{(kb / 1024).toFixed(2)} MB</Text>
      },
    },
    {
      title: '上报时间', dataIndex: 'created_at', width: 140,
      render: (v: string) => dayjs(v).format('MM-DD HH:mm:ss'),
    },
    {
      title: '操作', width: 220,
      render: (_: unknown, r: ErrorReport) => (
        <Space size="small">
          <Button size="small" icon={<DownloadOutlined />}
            loading={downloadingId === r.id}
            onClick={() => onDownload(r)}>下载</Button>
          <Button size="small" icon={<EditOutlined />} onClick={() => {
            setEditTarget(r)
            editForm.setFieldsValue({
              status: r.status,
              admin_note: r.admin_note || '',
            })
          }}>编辑</Button>
          <Dropdown menu={{
            items: [
              { key: 'open', label: '标记待处理', disabled: r.status === 'open',
                onClick: () => quickUpdate(r, 'open') },
              { key: 'resolved', label: '标记已解决', disabled: r.status === 'resolved',
                onClick: () => quickUpdate(r, 'resolved') },
              { key: 'ignored', label: '标记已忽略', disabled: r.status === 'ignored',
                onClick: () => quickUpdate(r, 'ignored') },
            ],
          }}>
            <Button size="small">状态 ▾</Button>
          </Dropdown>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography.Title level={4} style={{ margin: 0 }}>
          <BugOutlined style={{ marginRight: 8 }} />
          错误报告
        </Typography.Title>
        <Space>
          <Select
            placeholder="按状态筛选"
            allowClear
            style={{ width: 140 }}
            value={filter.status}
            onChange={(v) => setFilter(f => ({ ...f, status: v }))}
            options={(Object.keys(STATUS_LABEL) as ErrorReportStatus[]).map(s => ({
              value: s, label: STATUS_LABEL[s],
            }))}
          />
          <Button icon={<ReloadOutlined />} onClick={refresh}>刷新</Button>
        </Space>
      </div>

      <Card>
        <Table
          rowKey="id"
          columns={columns as any}
          dataSource={data}
          loading={loading}
          pagination={{ pageSize: 50, showSizeChanger: false }}
          size="middle"
          expandable={{
            expandedRowRender: (r: ErrorReport) => (
              <div style={{ background: '#fafafa', padding: 12 }}>
                <Paragraph style={{ margin: 0 }}>
                  <Text strong>问题描述：</Text>
                </Paragraph>
                <Paragraph style={{ margin: '4px 0 8px', whiteSpace: 'pre-wrap' }}>
                  {r.message}
                </Paragraph>
                {r.admin_note && (
                  <>
                    <Text strong>管理员备注：</Text>
                    <Paragraph style={{ margin: '4px 0 0', whiteSpace: 'pre-wrap' }}>
                      {r.admin_note}
                    </Paragraph>
                  </>
                )}
              </div>
            ),
            rowExpandable: (r: ErrorReport) => r.message.length > 60 || !!r.admin_note,
          }}
        />
      </Card>

      <Modal
        title={`编辑 #${editTarget?.id || ''}`}
        open={!!editTarget}
        onCancel={() => setEditTarget(null)}
        onOk={() => editForm.submit()}
        footer={(_, { OkBtn, CancelBtn }) => (
          <Space><CancelBtn /><OkBtn /></Space>
        )}
      >
        <Form form={editForm} layout="vertical" onFinish={onEdit}>
          <Form.Item name="status" label="状态" rules={[{ required: true }]}>
            <Select
              options={(Object.keys(STATUS_LABEL) as ErrorReportStatus[]).map(s => ({
                value: s, label: STATUS_LABEL[s],
              }))}
            />
          </Form.Item>
          <Form.Item name="admin_note" label="管理员备注" rules={[{ max: 2000 }]}>
            <Input.TextArea rows={4} placeholder="可记录处理进展、修复版本号等" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
